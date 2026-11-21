"""Guard data integrity at the cross-branch boundary, not statistical validity."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dreamlab.contracts import ArmSummary, EvaluationRequest

FIXTURE = Path(__file__).parents[1] / "fixtures" / "evaluation_request.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_round_trip_preserves_outcomes_and_provenance():
    request = EvaluationRequest.model_validate(payload())
    assert EvaluationRequest.model_validate_json(request.model_dump_json()) == request
    assert request.trials[-1].outcome == "failure"
    assert request.trials[-1].stop_reason == "operator_stop"


@pytest.mark.parametrize("key", ["trial_id", "episode_id"])
def test_duplicate_import_cannot_inflate_sample_size(key):
    data = payload()
    data["trials"][1][key] = data["trials"][0][key]
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(data)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("checkpoint_id", "unrelated-model"),
        ("task_version", 2),
        ("scenario_id", "unplanned-location"),
        ("duration_s", float("nan")),
        ("duration_s", -1),
        ("reviewer_id", None),
        ("human_verified", "false"),
        ("interventions", True),
        ("recorded_at", "2026-11-21T10:00:00"),
    ],
)
def test_malformed_or_misattributed_trials_are_rejected(key, value):
    data = payload()
    data["trials"][0][key] = value
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(data)


def test_unknown_outcome_is_preserved_not_coerced_to_failure():
    data = payload()
    data["trials"][0].update(outcome="unknown", human_verified=False, reviewer_id=None)
    request = EvaluationRequest.model_validate(data)
    assert request.trials[0].outcome == "unknown"


def test_invalid_outcome_requires_documented_exclusion():
    data = payload()
    data["trials"][0]["outcome"] = "invalid"
    with pytest.raises(ValidationError, match="exclusion reason"):
        EvaluationRequest.model_validate(data)


def test_fixed_horizon_cannot_silently_become_repeated_testing():
    data = payload()
    data["plan"]["planned_looks"] = [1, 2]
    with pytest.raises(ValidationError, match="interim"):
        EvaluationRequest.model_validate(data)


@pytest.mark.parametrize("looks", [[], [2, 1], [1, 1, 2], [1]])
def test_sequential_schedule_must_be_ordered_and_reach_budget(looks):
    data = payload()
    data["plan"].update(mode="group_sequential", planned_looks=looks)
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(data)


def test_arm_summary_cannot_hide_unaccounted_attempts():
    with pytest.raises(ValidationError, match="every attempted trial"):
        ArmSummary(
            checkpoint_id="baseline", attempted=3, successes=1, failures=1, unknown=0, invalid=0
        )
