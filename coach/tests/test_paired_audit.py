"""Matched-scene evidence stays descriptive for simulation and conservative for hardware."""

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from teach_task_coach.api import create_app

FIXTURE = Path(__file__).parents[1] / "src/teach_task_coach/examples/apple_paired_confirmation.json"


def _snapshot() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _analyze(client: TestClient, payload: dict):
    return client.post("/api/paired-evaluations/analyze", json=payload)


def test_saved_apple_confirmation_is_descriptive_and_replay_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    response = _analyze(TestClient(create_app()), _snapshot())
    assert response.status_code == 200
    report = response.json()
    assert report["decision"] == "descriptive"
    assert report["submitted_pairs"] == report["usable_pairs"] == 4
    assert (report["baseline_successes"], report["candidate_successes"]) == (0, 4)
    assert report["observed_difference"] == 1
    assert report["difference_interval"] is None
    assert len(report["input_sha256"]) == 64
    assert all(pair["candidate"]["held_lift_m"] >= 0.08 for pair in report["pairs"])
    demo = TestClient(create_app()).get("/api/paired-evaluations/demo")
    assert demo.status_code == 200
    assert demo.json() == _snapshot()


def test_incomplete_or_mislabeled_simulator_evidence_does_not_get_a_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    missing = _snapshot()
    missing["pairs"].pop()
    report = _analyze(client, missing).json()
    assert report["decision"] == "not_evaluable"
    assert report["candidate_successes"] == 3
    assert report["observed_difference"] is None
    assert any("budget" in problem for problem in report["problems"])

    missing_arm = _snapshot()
    missing_arm["pairs"][0]["candidate"] = None
    report = _analyze(client, missing_arm).json()
    assert report["decision"] == "not_evaluable"
    assert report["baseline_attempted"] == 4
    assert report["candidate_attempted"] == 3
    assert report["observed_difference"] is None

    wrong_label = _snapshot()
    wrong_label["pairs"][0]["candidate"]["outcome"] = "failure"
    report = _analyze(client, wrong_label).json()
    assert report["decision"] == "not_evaluable"
    assert any("held-lift rule" in problem for problem in report["problems"])

    bad_replay = _snapshot()
    bad_replay["pairs"][0]["candidate"]["replay_max_state_error_m"] = 0.006
    report = _analyze(client, bad_replay).json()
    assert report["decision"] == "not_evaluable"

    wrong_checkpoint = _snapshot()
    wrong_checkpoint["pairs"][0]["candidate"]["checkpoint_id"] = "unplanned-model"
    assert _analyze(client, wrong_checkpoint).status_code == 422


def test_four_real_pairs_are_inconclusive_but_thirty_can_clear_margin(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    payload = _snapshot()
    payload["plan"].update(collection_mode="prospective", minimum_improvement=0.15)
    for pair in payload["pairs"]:
        for trial in (pair["baseline"], pair["candidate"]):
            trial.update(human_verified=True, reviewer_id="operator-1")
    report = _analyze(client, payload).json()
    assert report["decision"] == "inconclusive"
    assert report["difference_interval"][0] < 0

    template = payload["pairs"][0]
    payload["pairs"] = []
    payload["plan"]["planned_pairs"] = 30
    for index in range(30):
        pair = copy.deepcopy(template)
        pair["pair_id"] = f"physical-scene-{index}"
        pair["scenario_id"] = pair["pair_id"]
        for role in ("baseline", "candidate"):
            trial = pair[role]
            trial["trial_id"] = f"{role}-{index}"
            trial["episode_id"] = f"episode-{role}-{index}"
            trial["session_id"] = f"session-{role}-{index}"
            trial["source_uri"] = f"robot://{role}/{index}"
        payload["pairs"].append(pair)
    report = _analyze(client, payload).json()
    assert report["decision"] == "improved"
    assert report["difference_interval"][0] > 0.15
    assert "Hoeffding" in report["interval_method"]

    payload["pairs"][0]["candidate"]["safety_stops"] = 1
    assert _analyze(client, payload).json()["decision"] == "inconclusive"


def test_repeated_sessions_or_unreviewed_physical_attempts_block_inference(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    payload = _snapshot()
    payload["plan"]["collection_mode"] = "prospective"
    for pair in payload["pairs"]:
        for trial in (pair["baseline"], pair["candidate"]):
            trial.update(human_verified=True, reviewer_id="operator-1")
    payload["pairs"][1]["candidate"]["session_id"] = payload["pairs"][0]["candidate"]["session_id"]
    payload["pairs"][2]["candidate"]["human_verified"] = False
    report = _analyze(client, payload).json()
    assert report["decision"] == "not_evaluable"
    assert len(report["problems"]) == 2
