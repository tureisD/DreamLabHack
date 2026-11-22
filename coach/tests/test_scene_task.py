"""A new pick-and-place scene should need JSON, not a new task adapter."""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mujoco")
pytest.importorskip("av")

SCENES = Path(__file__).parents[1] / "experiments/yam_sim_faas/scenes"
sys.path.insert(0, str(SCENES.parent))
from scene_task import TaskSpec, execute, make_env, scene_xml

from teach_task_coach.api import create_app
from teach_task_coach.demos import DemoScanner, DemoStore
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore


@pytest.mark.parametrize("name", ["red_block_to_blue_pad", "yellow_ball_to_green_pad"])
def test_two_new_tasks_use_same_scene_builder_and_planner(name):
    spec = TaskSpec.from_file(SCENES / f"{name}.json")
    xml = scene_xml(spec)
    assert 'name="task_object"' in xml and 'name="task_target"' in xml
    assert 'name="apple"' not in xml
    env = make_env(spec, 42)
    try:
        assert execute(env, spec)["passed"]
    finally:
        env.close()


def test_scene_api_previews_a_new_task_and_rejects_wrong_prompt(tmp_path):
    specification = json.loads((SCENES / "red_block_to_blue_pad.json").read_text())
    tasks = TaskStore(tmp_path)
    task = tasks.create_task(TaskInput(name="Another task", prompt="stack two blocks",
                                       baseline_checkpoint="dreamlabs/dream-1-beta",
                                       success_rule="Two blocks stacked"))
    app = create_app(store=EpisodeStore(tmp_path), task_store=tasks,
                     demo_store=DemoStore(tmp_path), demo_scanner=DemoScanner(tmp_path / "demos"))
    client = TestClient(app)
    response = client.post("/api/scene-task/preview", json={"spec": specification, "seed": 47})
    assert response.status_code == 200, response.text
    assert response.json()["image"].startswith("data:image/png;base64,")
    assert set(response.json()["markers"]) == {"object", "target"}
    response = client.post(f"/api/tasks/{task.id}/scene-task",
                           json={"spec": specification, "seed": 47})
    assert response.status_code == 422
    assert "place the red block on the blue pad" in response.json()["detail"]

    specification["goal"]["type"] = "fold_towel"
    response = client.post("/api/scene-task/preview", json={"spec": specification, "seed": 47})
    assert response.status_code == 422
    assert "place_on_target" in response.json()["detail"]
