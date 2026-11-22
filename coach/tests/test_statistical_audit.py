"""The standalone evaluator is exposed without changing paired coach evaluations."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dreamlab.contracts import EvaluationRequest
from dreamlab.evaluation.engine import StatisticalEvaluator
from teach_task_coach.api import create_app

FIXTURE = Path(__file__).parent / "fixtures/statistical_evaluation_request.json"


def _request() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_independent_snapshot_matches_standalone_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    payload = _request()
    expected = StatisticalEvaluator().evaluate(EvaluationRequest.model_validate(payload))
    response = TestClient(create_app()).post("/api/statistical-evaluations/analyze", json=payload)
    assert response.status_code == 200
    assert response.json() == expected.model_dump(mode="json")
    assert response.json()["baseline"]["attempted"] == 2
    assert response.json()["candidate"]["attempted"] == 2


def test_paired_and_simulated_trials_are_not_reinterpreted_as_independent(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    paired = _request()
    paired["plan"]["design"] = "paired"
    for index, trial in enumerate(paired["trials"]):
        trial["pair_id"] = f"scene-{index // 2}"
    response = client.post("/api/statistical-evaluations/analyze", json=paired)
    assert response.status_code == 200
    assert response.json()["decision"] == "not_evaluable"
    assert response.json()["difference_interval"] is None

    simulated = _request()
    for trial in simulated["trials"]:
        trial["collection_mode"] = "simulation"
    response = client.post("/api/statistical-evaluations/analyze", json=simulated)
    assert response.status_code == 200
    assert response.json()["decision"] == "not_evaluable"


def test_snapshot_schema_rejects_duplicate_episode(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    payload = _request()
    payload["trials"][1]["episode_id"] = payload["trials"][0]["episode_id"]
    response = TestClient(create_app()).post("/api/statistical-evaluations/analyze", json=payload)
    assert response.status_code == 422


def test_sample_planner_reports_infeasible_budget_and_rejects_bad_assumptions(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    payload = {
        "baseline_rate": 0.375,
        "alternative_gain": 0.25,
        "minimum_improvement": 0.125,
        "max_trials_per_arm": 80,
    }
    result = client.post("/api/statistical-evaluations/plan", json=payload)
    assert result.status_code == 200
    assert result.json()["feasible"] is False
    assert result.json()["trials_per_arm"] is None
    assert 0.34 < result.json()["power_at_budget"] < 0.35

    payload["alternative_gain"] = 0.1
    result = client.post("/api/statistical-evaluations/plan", json=payload)
    assert result.status_code == 422
