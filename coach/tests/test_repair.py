"""A cheap repair can be planned, run, audited, and invalidated before paid training."""

import datetime as dt
import json
from pathlib import Path

from fastapi.testclient import TestClient
from test_trials import FakeStation

from teach_task_coach.api import create_app
from teach_task_coach.episodes import EpisodeSummary, RolloutScanner
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore


def setup_repair(tmp_path):
    data = tmp_path / "data"
    tasks = TaskStore(data)
    task = tasks.create_task(TaskInput(
        name="Apple grasp", prompt="pick up the apple", baseline_checkpoint="base",
        success_rule="apple held 8 cm for 2 seconds",
    ))
    episodes = EpisodeStore(data)
    station = FakeStation()
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    client = TestClient(create_app(
        PreflightService(station, list), episodes, RolloutScanner(rollouts), tasks,
    ))
    return client, tasks, episodes, task, station


def plan(client, task_id, *, pairs=12, kind="prompt"):
    body = {"kind": kind, "planned_pairs": pairs, "minimum_gain": 0.1}
    if kind == "prompt":
        body["candidate_prompt"] = "grasp and hold the apple"
    else:
        body["setup_change"] = "move the overhead camera to see the whole table"
    response = client.post(f"/api/tasks/{task_id}/repair-studies", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def populate(tasks, episodes, study, *, candidate_success):
    timestamp = (dt.datetime.fromisoformat(study["created_at"]) + dt.timedelta(seconds=1)).isoformat()
    for trial in tasks.list_repair_trials(study["id"]):
        success = candidate_success if trial.repair_role == "candidate" else False
        folder = tasks.db.data_dir / "repair-rollouts" / trial.id
        folder.mkdir(parents=True, exist_ok=True)
        task_text = trial.prompt_override or "pick up the apple"
        (folder / "rollout.json").write_text(json.dumps({
            "task": task_text, "checkpoint": "base", "status": "complete",
            "started_at_utc": timestamp,
        }), encoding="utf-8")
        episode = EpisodeSummary(
            id=trial.id, source_path=str(folder), status="complete", task=task_text,
            checkpoint="base", started_at_utc=timestamp, videos={}, findings=[], events=[],
            body=None, robot_name=None, frames=100, fps=20, duration_s=5,
            stop_reason="stopped", error=None, stalls=None, clamps=None,
        )
        episodes.upsert(episode)
        episodes.label(episode.id, success, None, None, "reviewer-1")
        tasks.transition(trial.id, "planned", "completed", episode_id=episode.id)


def test_prompt_repair_runs_same_checkpoint_with_one_changed_prompt(tmp_path):
    client, tasks, _episodes, task, station = setup_repair(tmp_path)
    study = plan(client, task.id, pairs=4)
    trials = client.get(f"/api/repair-studies/{study['id']}/trials").json()
    assert len(trials) == 8
    assert {trial["checkpoint"] for trial in trials} == {"base"}
    assert sum(trial["prompt_override"] is not None for trial in trials) == 4
    assert all(trials[index]["scene_index"] == trials[index + 1]["scene_index"]
               for index in range(0, len(trials), 2))
    assert client.post(f"/api/trials/{trials[1]['id']}/start").status_code == 409
    assert client.post(f"/api/trials/{trials[0]['id']}/start").status_code == 200
    assert station.prompt == (trials[0]["prompt_override"] or task.prompt)
    assert tasks.next_repair_trial(study["id"]).id == trials[0]["id"]


def test_repair_audit_recommends_cheap_fix_and_invalidates_changed_source(tmp_path):
    client, tasks, episodes, task, _station = setup_repair(tmp_path)
    study = plan(client, task.id, pairs=30)
    populate(tasks, episodes, study, candidate_success=True)
    url = f"/api/repair-studies/{study['id']}"
    assert client.get(f"{url}/report").json()["decision"] == "not_evaluable"
    result = client.post(f"{url}/audit", json={"reset_attested": True})
    assert result.status_code == 200
    assert result.json()["decision"] == "use_fix"
    assert result.json()["baseline_successes"] == 0
    assert result.json()["candidate_successes"] == 30
    assert result.json()["difference_interval"][0] > 0.1
    assert client.get(f"/api/tasks/{task.id}/repair/triage").json()["action"] == "use_fix"
    trial = tasks.list_repair_trials(study["id"])[0]
    episode = episodes.get(trial.episode_id)
    assert episode is not None
    (Path(episode.source_path) / "rollout.json").write_text("{}", encoding="utf-8")
    assert client.get(f"{url}/report").json()["decision"] == "not_evaluable"


def test_no_observed_cheap_gain_routes_to_targeted_demos(tmp_path):
    client, tasks, episodes, task, _station = setup_repair(tmp_path)
    study = plan(client, task.id, pairs=12, kind="setup")
    populate(tasks, episodes, study, candidate_success=False)
    result = client.post(f"/api/repair-studies/{study['id']}/audit", json={"reset_attested": True})
    assert result.status_code == 200
    assert result.json()["decision"] == "consider_faas"
    assert result.json()["observed_gain"] == 0
    assert "does not prove" in result.json()["recommendation"]
    assert client.get(f"/api/tasks/{task.id}/repair/triage").json()["action"] == "collect_demos"


def test_bad_repair_plan_and_missing_camera_do_not_recommend_training(tmp_path):
    client, _tasks, _episodes, task, station = setup_repair(tmp_path)
    assert client.post(f"/api/tasks/{task.id}/repair-studies", json={
        "kind": "prompt", "candidate_prompt": task.prompt,
    }).status_code == 409
    station.status = lambda: {"state": "idle", "arms": {"left": True}, "cameras": {"top": None}}
    result = client.get(f"/api/tasks/{task.id}/repair/triage").json()
    assert result["action"] == "fix_camera"
