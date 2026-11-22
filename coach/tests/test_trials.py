import json

from fastapi.testclient import TestClient

from teach_task_coach.api import create_app
from teach_task_coach.episodes import RolloutScanner
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore, TrialInput


class FakeStation:
    def __init__(self):
        self.current_state = "idle"
        self.run_number = 0
        self.started_at = None
        self.prompt = None
        self.checkpoint = None

    def status(self):
        return {
            "state": self.current_state,
            "run": self.run_number,
            "started_at": self.started_at,
            "prompt": self.prompt,
            "checkpoint": self.checkpoint,
            "arms": {"left": True, "right": True},
            "cameras": {"overhead": 0.1},
        }

    def post(self, route, body=None):
        if route == "start":
            assert self.current_state == "idle"
            self.run_number += 1
            self.started_at = "2026-11-21T10:00:00+00:00"
            self.prompt = body["prompt"]
            self.checkpoint = body["checkpoint"]
            self.current_state = "running"
        elif route == "stop":
            self.current_state = "idle"
        return self.status()


def test_supervised_baseline_trial_attaches_rollout_and_label(tmp_path):
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    station = FakeStation()
    episode_store = EpisodeStore(tmp_path / "data")
    task_store = TaskStore(tmp_path / "data")
    client = TestClient(
        create_app(
            PreflightService(station, list),
            episode_store,
            RolloutScanner(rollouts),
            task_store,
        )
    )

    task_response = client.post(
        "/api/tasks",
        json={
            "name": "Block to bin",
            "prompt": "put block in bin",
            "baseline_checkpoint": "dreamlabs/dream-1-beta",
            "success_rule": "Block rests inside the bin at the end.",
        },
    )
    assert task_response.status_code == 201
    task_id = task_response.json()["id"]
    trial = client.post(
        f"/api/tasks/{task_id}/baseline-trials", json={"start_cell": 3}
    ).json()
    trial_id = trial["id"]

    assert client.post(f"/api/trials/{trial_id}/start").json()["status"] == "running"
    assert client.post(f"/api/trials/{trial_id}/start").status_code == 409
    assert client.post(f"/api/trials/{trial_id}/stop").json()["status"] == "awaiting_rollout"

    folder = rollouts / "2026-11-21T10-00-05_run1"
    folder.mkdir()
    (folder / "rollout.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "task": station.prompt,
                "checkpoint": station.checkpoint,
                "run": station.run_number,
                "started_at_utc": "2026-11-21T10:00:05+00:00",
                "frames": 100,
                "fps": 20,
                "stop_reason": "stopped",
            }
        )
    )
    synced = client.post(f"/api/trials/{trial_id}/sync")
    assert synced.status_code == 200
    assert synced.json()["status"] == "awaiting_label"
    assert synced.json()["episode_id"] is not None

    labelled = client.post(
        f"/api/trials/{trial_id}/label",
        json={"success": False, "failure_stage": "grasp", "note": "missed"},
    )
    assert labelled.status_code == 200
    assert labelled.json()["status"] == "completed"
    assert task_store.get_trial(trial_id).status == "completed"
    assert episode_store.get(synced.json()["episode_id"]).success is False


def test_trial_does_not_start_when_station_is_busy(tmp_path):
    station = FakeStation()
    station.current_state = "running"
    tasks = TaskStore(tmp_path)
    task = tasks.create_task(
        TaskInput(name="Task", prompt="put block in bin", baseline_checkpoint="base", success_rule="in bin")
    )
    trial = tasks.create_trial(task.id, TrialInput(start_cell=0))
    client = TestClient(
        create_app(PreflightService(station, list), EpisodeStore(tmp_path), RolloutScanner(tmp_path), tasks)
    )

    response = client.post(f"/api/trials/{trial.id}/start")
    assert response.status_code == 409
    assert tasks.get_trial(trial.id).status == "planned"


def test_missing_rollout_can_be_abandoned_after_stop(tmp_path):
    station = FakeStation()
    tasks = TaskStore(tmp_path)
    task = tasks.create_task(
        TaskInput(name="Task", prompt="put block in bin", baseline_checkpoint="base", success_rule="in bin")
    )
    trial = tasks.create_trial(task.id, TrialInput(start_cell=0))
    client = TestClient(
        create_app(PreflightService(station, list), EpisodeStore(tmp_path), RolloutScanner(tmp_path), tasks)
    )

    assert client.post(f"/api/trials/{trial.id}/start").status_code == 200
    assert client.post(f"/api/trials/{trial.id}/stop").status_code == 200
    assert client.post(f"/api/trials/{trial.id}/sync").json()["status"] == "awaiting_rollout"
    response = client.post(f"/api/trials/{trial.id}/abandon", json={"reason": "no recording"})
    assert response.json()["status"] == "abandoned"
    assert response.json()["last_error"] == "no recording"


def test_model_ready_rollout_is_preserved_and_trial_can_restart(tmp_path):
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    station = FakeStation()
    tasks = TaskStore(tmp_path / "data")
    task = tasks.create_task(TaskInput(
        name="Task", prompt="put block in bin", baseline_checkpoint="base", success_rule="in bin"
    ))
    trial = tasks.create_trial(task.id, TrialInput(start_cell=0))
    client = TestClient(create_app(
        PreflightService(station, list), EpisodeStore(tmp_path / "data"),
        RolloutScanner(rollouts), tasks,
    ))
    assert client.post(f"/api/trials/{trial.id}/start").status_code == 200
    assert client.post(f"/api/trials/{trial.id}/stop").status_code == 200
    folder = rollouts / "warmup_run1"
    folder.mkdir()
    (folder / "rollout.json").write_text(json.dumps({
        "status": "partial", "task": task.prompt, "checkpoint": "base", "run": 1,
        "started_at_utc": "2026-11-21T10:00:05+00:00", "frames": 0,
        "stop_reason": "ModelReady",
    }))
    synced = client.post(f"/api/trials/{trial.id}/sync").json()
    assert synced["status"] == "planned"
    assert synced["station_run"] is None
    warmups = client.get(f"/api/trials/{trial.id}/warmups").json()
    assert len(warmups) == 1
    assert warmups[0]["stop_reason"] == "ModelReady"
    assert client.post(f"/api/trials/{trial.id}/start").json()["station_run"] == 2


def test_browser_from_remote_origin_cannot_start_robot_or_submit_writes(tmp_path):
    client = TestClient(create_app(
        PreflightService(FakeStation(), list), EpisodeStore(tmp_path),
        RolloutScanner(tmp_path), TaskStore(tmp_path),
    ))
    body = {
        "name": "Task", "prompt": "put block in bin", "baseline_checkpoint": "base",
        "success_rule": "in bin",
    }
    assert client.post("/api/tasks", json=body, headers={"Origin": "https://other.example"}).status_code == 403
    assert client.post("/api/tasks", json=body, headers={"Origin": "http://localhost:5173"}).status_code == 201
