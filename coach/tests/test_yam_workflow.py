"""Exercise the chat routes with local YAM evidence and an offline Dream fixture."""

import datetime as dt
import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi.testclient import TestClient

from teach_task_coach import yam_workflow
from teach_task_coach.api import create_app
from teach_task_coach.faas import FaaSStore, FineTuneRequest
from teach_task_coach.preflight import PreflightService
from teach_task_coach.simulator_setup import SimulatorStatus
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.yam_workflow import BASE, MIN_ACTION_ROWS, PROMPT, YamWorkflow

CANDIDATE = "test/apple-checkpoint"


def wait_for_job(client: TestClient, timeout: int = 15) -> dict:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = client.get("/api/simulator/workflow").json()
        if result["state"] not in ("running", "stopping"):
            return result
        sleep(0.25)
    raise AssertionError("The simulator fixture did not finish.")


def test_chat_collection_and_live_paired_comparison(tmp_path, monkeypatch):
    ready = SimpleNamespace(status=lambda: SimulatorStatus(state="ready", message="Offline fixture"))
    preflight = PreflightService(model_loader=lambda: [
        SimpleNamespace(id=id_, owner="test", embodiment="yam", servable=True, cameras=None)
        for id_ in (BASE, CANDIDATE)
    ])
    client = TestClient(create_app(preflight, EpisodeStore(tmp_path), simulator_setup=ready))
    first_result = Event()
    resume = Event()
    attempted = []

    def record(self, folder, checkpoint, seed, *, heldout=False):
        if heldout:
            attempted.append((seed, checkpoint))
            if len(attempted) == 2:
                first_result.set()
                assert resume.wait(10)
            success = checkpoint == CANDIDATE
            return {
                "started_at": dt.datetime.now(dt.UTC).isoformat(), "success": success,
                "held_lift_m": 0.11 if success else 0, "peak_lift_m": 0.12 if success else 0,
                "duration_s": 32, "model_action_rows": MIN_ACTION_ROWS,
                "replay_max_state_error": 0.001, "first_close_after_warmup_s": 2,
            }

        source = folder / f"fixture-{seed}"
        source.mkdir(parents=True)
        return {"folder": str(source), "success": False}

    def export(rollouts, collect_flag, output, max_demos_flag, count, *, timeout):
        # A separate collector test renders the real correction. Here, exercise
        # the API handoff with an audited LeRobot episode from the bundle.
        assert len(list(Path(rollouts).iterdir())) == 1
        assert (collect_flag, max_demos_flag, count) == ("--collect-into", "--max-demos", "1")
        with ZipFile(yam_workflow.SCRIPTS / "grasp_training/independent.zip") as archive:
            root = next(name.split("/")[0] for name in archive.namelist() if name.endswith("/meta/info.json"))
            archive.extractall(output, [name for name in archive.namelist() if name.startswith(root + "/")])
        return {"sessions": [{"demo_folder": root}]}

    monkeypatch.setattr(YamWorkflow, "_record", record)
    monkeypatch.setattr(yam_workflow, "workflow_result", export)
    assert client.get("/api/simulator/workflow").json() is None
    assert client.post("/api/simulator/collect", json={"scenes": 9}).status_code == 422
    response = client.post("/api/simulator/collect", json={"scenes": 1})
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert wait_for_job(client)["demos"] == 1
    [demo] = client.get(f"/api/tasks/{task_id}/demos").json()
    assert demo["decision"] == "unreviewed"
    assert demo["task_text"] == PROMPT
    assert client.get(f"/api/demos/{demo['id']}/video/overhead").status_code == 200
    split = json.loads((Path(tmp_path) / "yam-workflow" / task_id / "scenes.json").read_text())
    assert max(split["training"]) < min(split["heldout"])

    faas = FaaSStore(tmp_path)
    dataset = faas.create_dataset(task_id, "test/yam", [demo["id"]])
    job = faas.create_finetune(dataset.id, FineTuneRequest())
    value = {"task_id": task_id, "job_id": job.id, "pairs": 2}
    assert client.post("/api/simulator/compare", json=value).status_code == 409
    faas.update_finetune(job.id, status="succeeded", checkpoint=CANDIDATE)
    assert client.post("/api/simulator/compare", json=value).status_code == 202
    url = f"/api/simulator/comparisons/{task_id}"
    try:
        assert first_result.wait(10)
        assert client.post("/api/simulator/collect", json={"scenes": 1}).status_code == 409
        partial = client.get(url).json()["report"]
        assert (partial["baseline_attempted"], partial["candidate_attempted"]) == (1, 0)
        assert partial["decision"] == "not_evaluable"
    finally:
        resume.set()
    assert wait_for_job(client)["state"] == "completed"
    report = client.get(url).json()["report"]
    assert (report["baseline_successes"], report["candidate_successes"], report["usable_pairs"]) == (0, 2, 2)
    assert report["decision"] == "descriptive"
    assert report["difference_interval"] is None
    assert attempted == [
        (split["heldout"][0], BASE), (split["heldout"][0], CANDIDATE),
        (split["heldout"][1], CANDIDATE), (split["heldout"][1], BASE),
    ]


def test_bundled_data_is_available_without_dream_access(tmp_path):
    client = TestClient(create_app(store=EpisodeStore(tmp_path)))
    response = client.post("/api/simulator/collect", json={"source": "bundled"})
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert wait_for_job(client, timeout=15)["demos"] == 24
    rows = client.get(f"/api/tasks/{task_id}/demos").json()
    assert len(rows) == 24
    assert all(row["decision"] == "unreviewed" for row in rows)


def test_chat_reports_the_saved_session_replacement_reason(tmp_path, monkeypatch):
    ready = SimpleNamespace(status=lambda: SimulatorStatus(state="ready", message="Offline fixture"))
    preflight = PreflightService(model_loader=lambda: [
        SimpleNamespace(id=BASE, owner="test", embodiment="yam", servable=True, cameras=None)
    ])
    client = TestClient(create_app(preflight, EpisodeStore(tmp_path), simulator_setup=ready))

    def fail_recording(script, output_option, output, *args, timeout):
        assert script == "record_dream_model_rollout.py"
        assert output_option == "--output"
        folder = Path(output) / "fixture"
        folder.mkdir(parents=True)
        (folder / "rollout.json").write_text(json.dumps({
            "error": "DreamSessionExpired",
            "simulation": {
                "session_replacements": 4,
                "last_session_replacement_reason": "serve_died",
                "model_action_rows": 288,
            },
        }))
        raise yam_workflow.SimulatorRunError("Raw provider or subprocess details")

    monkeypatch.setattr(yam_workflow, "command", fail_recording)
    assert client.post("/api/simulator/collect", json={"scenes": 1}).status_code == 202
    job = wait_for_job(client)
    assert job["state"] == "failed"
    assert job["message"] == (
        "The rollout reached the retry limit after 4 Dream session replacements. "
        "Dream reported that the model server stopped. "
        "The partial recording saved 288 of 576 model actions."
    )
