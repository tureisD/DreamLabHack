import copy
import json
import runpy
from pathlib import Path

import pytest

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
    assert len(report["snapshot_sha256"]) == 64


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
