"""Exercise the chat routes with local YAM evidence and an offline Dream fixture."""

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from teach_task_coach import yam_workflow
from teach_task_coach.api import create_app
from teach_task_coach.faas import FaaSStore, FineTuneRequest
from teach_task_coach.preflight import PreflightService
from teach_task_coach.simulator_process import SimulatorProcessCancelled
from teach_task_coach.simulator_setup import SimulatorStatus
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.yam_workflow import BASE, MIN_ACTION_ROWS, PROMPT, SUCCESS_RULE, YamWorkflow

CANDIDATE = "test/apple-checkpoint"
VERIFIED_CANDIDATE = "dream-1-ft:7820aef9-apple-varied24-500"


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

    def export(rollouts, collect_flag, output, max_demos_flag, count, *, timeout, cancel):
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
        assert client.get("/api/simulator/workflow").json()["state"] == "running"
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
    assert client.post("/api/simulator/session/reset").json() == {
        "yam_active": False, "recorder_active": False,
    }
    assert client.get("/api/simulator/workflow").json() is None
    assert client.get(url).json()["report"] == report
    assert client.get(f"/api/tasks/{task_id}/demos").json() == [demo]
    reloaded = TestClient(create_app(store=EpisodeStore(tmp_path)))
    assert reloaded.get("/api/simulator/workflow").json() is None
    assert reloaded.get(url).json()["report"] == report


def test_saved_comparison_diagnostics_replay_verified_trace_once(tmp_path, monkeypatch):
    client = TestClient(create_app(store=EpisodeStore(tmp_path)))
    task_id, evaluation_id = "0" * 32, "1" * 32
    seed = 2**31 + 5
    folder = tmp_path / "yam-workflow" / task_id
    folder.mkdir()
    url = f"/api/simulator/comparisons/{task_id}"
    assert client.get(f"{url}/diagnostics").json() is None

    def saved_attempt(role, checkpoint):
        trial = f"{evaluation_id}-{seed}-{role}"
        source = folder / trial / "recorded"
        source.mkdir(parents=True)
        (source / "rollout.json").write_text(json.dumps({
            "status": "complete",
            "simulation": {"source": "model", "seed": seed},
            "checkpoint": checkpoint if role == "baseline" else "test/wrong-checkpoint",
        }), encoding="utf-8")
        return {
            "trial_id": trial, "episode_id": trial, "checkpoint_id": checkpoint,
            "source_uri": f"local-rollout://{trial}", "session_id": trial,
            "outcome": "failure", "training_exposure": "held_out",
            "model_action_rows": MIN_ACTION_ROWS, "held_lift_m": 0.02, "peak_lift_m": 0.09,
            "height_source": "recorded",
        }

    baseline = saved_attempt("baseline", BASE)
    candidate = saved_attempt("candidate", CANDIDATE)
    proof = folder / "comparison-evidence.json"
    proof.write_text(json.dumps({
        "plan": {
            "evaluation_id": evaluation_id, "task": PROMPT, "success_rule": SUCCESS_RULE,
            "baseline_checkpoint": BASE, "candidate_checkpoint": CANDIDATE,
            "collection_mode": "simulation", "planned_pairs": 1,
            "reset_protocol": "Repeat seed.", "assignment_protocol": "Base first.",
            "simulator_hold_threshold_m": 0.08, "required_model_rows": MIN_ACTION_ROWS,
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
        },
        "pairs": [{"pair_id": str(seed), "scenario_id": str(seed), "baseline": baseline, "candidate": candidate}],
    }), encoding="utf-8")
    original = proof.read_bytes()
    diagnosis = {
        "code": "grip_lost", "title": "Lift was too brief",
        "summary": "The recorded height dropped below the threshold.",
        "evidence": ["The peak lift was 9 cm."], "next_step": "Inspect the grasp while lifting.",
    }
    scored = []

    def replay(trial, *options, **_kwargs):
        assert Path(trial).name == baseline["trial_id"]
        assert options == ("--held-out-seed", str(seed), "--diagnose")
        scored.append(trial)
        return {
            "seed": seed, "checkpoint": BASE, "model_action_rows": MIN_ACTION_ROWS,
            "height_source": "recorded", "success": False, "held_lift_m": 0.02,
            "diagnosis": diagnosis,
        }

    monkeypatch.setattr(yam_workflow, "workflow_result", replay)
    response = client.get(f"{url}/diagnostics")
    assert response.status_code == 200
    result = response.json()
    assert result["evaluation_id"] == evaluation_id
    assert result["trials"][baseline["trial_id"]] == diagnosis
    fallback = result["trials"][candidate["trial_id"]]
    assert fallback["code"] == "saved_score_only"
    assert fallback["summary"] == "The apple reached 8 cm but did not stay there for two continuous seconds."
    assert client.get(f"{url}/diagnostics").json() == result
    assert len(scored) == 1
    assert proof.read_bytes() == original


def test_bundled_data_is_available_without_dream_access(tmp_path):
    client = TestClient(create_app(store=EpisodeStore(tmp_path)))
    response = client.post("/api/simulator/collect", json={"source": "bundled"})
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert wait_for_job(client, timeout=15)["demos"] == 24
    rows = client.get(f"/api/tasks/{task_id}/demos").json()
    assert len(rows) == 24
    assert all(row["decision"] == "unreviewed" for row in rows)


@pytest.mark.parametrize("reset_route", ["/api/simulator/session/reset", "/api/simulator/workflow/quit"])
def test_session_reset_stops_live_rollout_and_retains_completed_pairs(tmp_path, monkeypatch, reset_route):
    ready = SimpleNamespace(status=lambda: SimulatorStatus(state="ready", message="Offline fixture"))
    preflight = PreflightService(model_loader=lambda: [
        SimpleNamespace(id=id_, owner="test", embodiment="yam", servable=True, cameras=None)
        for id_ in (BASE, VERIFIED_CANDIDATE)
    ])
    client = TestClient(create_app(
        preflight, EpisodeStore(tmp_path), simulator_setup=ready, dream_gateway=SimpleNamespace(finetunes=list)
    ))
    third_recording = Event()
    reset_requested = Event()
    allow_worker_exit = Event()
    scores = {}

    def run(args, *, cancel, **kwargs):
        assert cancel is not None
        if Path(args[1]).name == "score_workflow_rollout.py":
            return SimpleNamespace(returncode=0, stdout="WORKFLOW_RESULT=" + json.dumps(scores[args[2]]))
        assert Path(args[1]).name == "record_dream_model_rollout.py"
        if len(scores) == 2:
            third_recording.set()
            assert cancel.wait(10)
            reset_requested.set()
            assert allow_worker_exit.wait(10)
            raise SimulatorProcessCancelled()
        checkpoint = args[args.index("--model") + 1]
        score = {
            "started_at": dt.datetime.now(dt.UTC).isoformat(),
            "seed": int(args[args.index("--seed") + 1]),
            "checkpoint": checkpoint, "success": checkpoint == VERIFIED_CANDIDATE,
            "held_lift_m": 0.11 if checkpoint == VERIFIED_CANDIDATE else 0,
            "peak_lift_m": 0.12 if checkpoint == VERIFIED_CANDIDATE else 0,
            "duration_s": 32, "model_action_rows": MIN_ACTION_ROWS, "height_source": "recorded",
            "replay_max_state_error": 0.001, "first_close_after_warmup_s": 2,
        }
        scores[args[args.index("--output") + 1]] = score
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(yam_workflow, "run_simulator_process", run)
    started = client.post("/api/simulator/compare-existing", json={"checkpoint": VERIFIED_CANDIDATE})
    assert started.status_code == 202
    task_id = started.json()["task_id"]
    assert third_recording.wait(10)
    url = f"/api/simulator/comparisons/{task_id}"
    before = client.get(url).json()
    assert before["report"]["usable_pairs"] == 1

    with ThreadPoolExecutor(max_workers=1) as executor:
        reset = executor.submit(client.post, reset_route)
        try:
            assert reset_requested.wait(10)
            assert not reset.done()
            assert client.post("/api/simulator/collect", json={"source": "bundled"}).status_code == 409
        finally:
            allow_worker_exit.set()
        response = reset.result(timeout=10)
        assert response.status_code == 200
        if reset_route.endswith("/quit"):
            assert response.json() is None

    assert client.get("/api/simulator/workflow").json() is None
    assert client.get(url).json() == before
    assert client.post("/api/simulator/collect", json={"source": "bundled"}).status_code == 202
    assert wait_for_job(client)["demos"] == 24


def test_existing_checkpoint_choices_join_accessible_models_and_verified_training(tmp_path, monkeypatch):
    unsupported = "dream-1-ft:beef1234-apples"
    eligible = "dream-1-ft:abcd1234-coach-apple"
    ready = SimpleNamespace(status=lambda: SimulatorStatus(state="ready", message="Offline fixture"))
    preflight = PreflightService(model_loader=lambda: [
        SimpleNamespace(id=id_, owner="test", embodiment="yam", servable=True, cameras=None)
        for id_ in (BASE, VERIFIED_CANDIDATE, eligible, unsupported)
    ])
    remote = [
        {"id": "remote-eligible", "status": "succeeded", "fine_tuned_model": eligible,
         "dataset": "fixture/coach-apples", "base_model": BASE, "hyperparameters": {"use_eef": False}},
        {"id": "remote-unsupported", "status": "succeeded", "fine_tuned_model": unsupported,
         "dataset": "fixture/apples-other", "base_model": BASE},
    ]
    client = TestClient(create_app(
        preflight, EpisodeStore(tmp_path), simulator_setup=ready,
        dream_gateway=SimpleNamespace(finetunes=lambda: remote),
    ))
    task_response = client.post("/api/tasks", json={
        "name": "Apple pickup · YAM simulator", "prompt": PROMPT,
        "baseline_checkpoint": BASE, "success_rule": SUCCESS_RULE,
    })
    assert task_response.status_code == 201
    task_id = task_response.json()["id"]
    folder = tmp_path / "yam-workflow" / task_id
    folder.mkdir()
    (folder / "scenes.json").write_text('{"training":[],"heldout":[]}', encoding="utf-8")

    faas = FaaSStore(tmp_path)
    dataset = faas.create_dataset(task_id, "fixture/yam", [])
    faas.update_dataset(dataset.id, status="validated", remote_name="fixture/coach-apples")
    job = faas.create_finetune(dataset.id, FineTuneRequest(steps=700))
    faas.update_finetune(job.id, remote_job_id="remote-eligible", status="succeeded", checkpoint=eligible)

    assert client.get("/api/simulator/existing-checkpoints").json() == [
        {"checkpoint": VERIFIED_CANDIDATE, "dataset": "dima24kor/apple-grasp-varied-3374a5388381", "steps": 500},
        {"checkpoint": eligible, "dataset": "fixture/coach-apples", "steps": 700},
    ]
    assert client.post("/api/simulator/compare-existing", json={"checkpoint": unsupported}).status_code == 409
    compared = []

    def record_comparison(self, job, folder, seeds, checkpoint):
        compared.append(checkpoint)
        self._update(state="completed")

    monkeypatch.setattr(YamWorkflow, "_compare", record_comparison)
    assert client.post("/api/simulator/compare-existing", json={"checkpoint": eligible}).status_code == 202
    assert wait_for_job(client)["state"] == "completed"
    assert compared == [eligible]
