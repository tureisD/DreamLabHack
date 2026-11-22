"""Checks the task-specific click adapter against the actual YAM physics scene."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mujoco")
pytest.importorskip("av")

SIM = Path(__file__).parents[1] / "experiments/yam_sim_faas"
sys.path.insert(0, str(SIM))
from click_to_correct import Goal, execute, goal_from_clicks, scene_markers, seeded_env

from teach_task_coach.api import create_app
from teach_task_coach.demos import DemoScanner, DemoStore
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore


def test_click_goals_transfer_between_lift_and_bowl():
    env = seeded_env("apple", 41)
    try:
        markers = scene_markers(env)
        with pytest.raises(ValueError, match="visible fruit"):
            goal_from_clicks(env, "lift", "apple", (1, 1))
        goal = goal_from_clicks(env, "bowl", "apple", markers["apple"], markers["bowl"])
        assert goal.task_text == "put the apple in the bowl"
        assert execute(env, goal)["passed"]
    finally:
        env.close()

    env = seeded_env("banana", 42)
    try:
        markers = scene_markers(env)
        goal = goal_from_clicks(env, "lift", "banana", markers["banana"])
        assert goal.task_text == "pick up the banana"
        assert execute(env, goal)["passed"]
        with pytest.raises(ValueError, match="supports apple only"):
            Goal("bowl", "banana", (0.0, -0.04)).validate()
    finally:
        env.close()


def test_sim_api_previews_scene_and_rejects_wrong_task(tmp_path):
    tasks = TaskStore(tmp_path)
    task = tasks.create_task(TaskInput(name="Towels", prompt="fold a towel",
                                       baseline_checkpoint="dreamlabs/dream-1-beta",
                                       success_rule="Towel folded"))
    app = create_app(store=EpisodeStore(tmp_path), task_store=tasks,
                     demo_store=DemoStore(tmp_path), demo_scanner=DemoScanner(tmp_path / "demos"))
    client = TestClient(app)
    scene = client.get("/api/sim-correction/scene", params={"fruit": "apple", "seed": 41})
    assert scene.status_code == 200
    assert scene.json()["image"].startswith("data:image/png;base64,")
    assert scene.json()["supported"]["bowl"] == ["apple"]
    click = scene.json()["markers"]["apple"]
    response = client.post(f"/api/tasks/{task.id}/sim-correction", json={
        "kind": "lift", "fruit": "apple", "seed": 41, "object_pixel": click,
    })
    assert response.status_code == 409
    assert "pick up the apple" in response.json()["detail"]
