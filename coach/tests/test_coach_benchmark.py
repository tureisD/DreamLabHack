import copy
import json
import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teach_task_coach.api import create_app

FIXTURES = Path(__file__).parents[1] / "benchmark"
analyze = runpy.run_path(str(FIXTURES / "coach_benchmark.py"))["analyze"]


def _files():
    plan = json.loads((FIXTURES / "plan.synthetic.json").read_text(encoding="utf-8"))
    outcomes = json.loads((FIXTURES / "outcomes.synthetic.json").read_text(encoding="utf-8"))
    return plan, outcomes


def test_synthetic_demo_is_descriptive_and_accounts_for_all_participants():
    plan, outcomes = _files()
    report = analyze(plan, outcomes)
    assert report["standard"]["validated_by_horizon"] == 1
    assert report["coach"]["validated_by_horizon"] == 3
    assert report["coach_minus_standard_validation_rate"] == 0.5
    assert report["coach_minus_standard_mean_restricted_minutes"] < 0
    assert report["coach"]["mean_faas_cost_usd"] is None
    assert report["fisher_two_sided_p"] > 0.05
    assert report["data_kind"] == "synthetic"
    assert report["coach_minus_standard_mean_demos"] < 0
    assert report["coach_minus_standard_mean_faas_steps"] < 0
    assert report["coach_minus_standard_mean_faas_cost_usd"] is None
    assert len(report["snapshot_sha256"]) == 64


def test_browser_analyzer_keeps_synthetic_example_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    example = client.get("/api/coach-effect/synthetic-example")
    assert example.status_code == 200
    report = client.post("/api/coach-effect/analyze", json=example.json())
    assert report.status_code == 200
    assert report.json()["data_kind"] == "synthetic"
    assert "no" in report.json()["warnings"][0].lower()
    altered = example.json()
    altered["plan"].pop("data_kind")
    assert client.post("/api/coach-effect/analyze", json=altered).status_code == 422


@pytest.mark.parametrize("mutation", [
    lambda plan, rows: rows.pop(),
    lambda plan, rows: rows.append(copy.deepcopy(rows[0])),
    lambda plan, rows: rows[0].update(validation_report_sha256="bad"),
    lambda plan, rows: rows[1].update(ended_at="2026-11-21T12:00:00+00:00"),
    lambda plan, rows: rows[0].update(started_at="2026-11-19T09:00:00+00:00"),
    lambda plan, rows: plan.update(assignment_method="observational"),
])
def test_incomplete_or_contradictory_study_refused(mutation):
    plan, outcomes = _files()
    mutation(plan, outcomes)
    with pytest.raises(ValueError):
        analyze(plan, outcomes)
