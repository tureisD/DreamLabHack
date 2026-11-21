"""Synthetic contract examples for software validation only, not robot evidence."""

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from itertools import zip_longest
from pathlib import Path

import pytest

from dreamlab.contracts import EvaluationReport, EvaluationRequest, Interval
from dreamlab.evaluation.engine import StatisticalEvaluator

FIXTURE = Path(__file__).parents[1] / "fixtures" / "evaluation_request.json"
OUTCOMES = {"1": "success", "0": "failure", "?": "unknown", "x": "invalid"}
NON_DIRECTIONAL = {"not_evaluable", "inconclusive"}


def make_payload(baseline, candidate, *, budget, looks=(), alpha=0.05, margin=0.1):
    """Interleave two outcome strings in observed order; budget is never inferred."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plan = payload["plan"]
    plan.update(
        planned_trials_per_checkpoint=budget,
        mode="group_sequential" if looks else "fixed_horizon",
        planned_looks=list(looks),
        alpha=alpha,
        minimum_improvement=margin,
    )
    template = payload["trials"][0]
    start = datetime.fromisoformat(plan["created_at"])
    checkpoints = (plan["baseline_checkpoint"], plan["candidate_checkpoint"])
    trials = []
    for outcomes in zip_longest(baseline, candidate):
        for checkpoint, code in zip(checkpoints, outcomes, strict=True):
            if code is None:
                continue
            i = len(trials) + 1
            trials.append(
                dict(
                    template,
                    trial_id=f"trial-{i}",
                    episode_id=f"episode-{i}",
                    session_id=f"session-{i}",
                    source_uri=f"fixture://synthetic/episode-{i}",
                    checkpoint_id=checkpoint,
                    outcome=OUTCOMES[code],
                    exclusion_reason="recording incomplete" if code == "x" else None,
                    stop_reason=None,
                    recorded_at=(start + timedelta(minutes=i)).isoformat(),
                )
            )
    payload["trials"] = trials
    return payload


def digest(request: EvaluationRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assert_snapshot(report: EvaluationReport, request: EvaluationRequest):
    """Audit submitted rows independently of which prefix, if any, is inferential."""
    assert report.evaluation_id == request.plan.evaluation_id
    assert report.input_sha256 == digest(request)
    assert report.trial_ids == tuple(row.trial_id for row in request.trials)
    for summary, checkpoint in (
        (report.baseline, request.plan.baseline_checkpoint),
        (report.candidate, request.plan.candidate_checkpoint),
    ):
        counts = Counter(row.outcome for row in request.trials if row.checkpoint_id == checkpoint)
        assert summary.checkpoint_id == checkpoint
        assert summary.attempted == counts.total()
        assert (summary.successes, summary.failures, summary.unknown, summary.invalid) == (
            counts["success"],
            counts["failure"],
            counts["unknown"],
            counts["invalid"],
        )


def evaluate(payload):
    request = EvaluationRequest.model_validate(payload)
    report = StatisticalEvaluator().evaluate(request)
    assert_snapshot(report, request)
    return report


def assert_refused(report):
    assert report.decision == "not_evaluable"
    assert report.difference is None
    assert report.difference_interval is None
    for arm in (report.baseline, report.candidate):
        assert arm.success_rate is None
        assert arm.success_interval is None


def assert_interval(interval: Interval | None, expected, level):
    assert interval is not None
    assert (interval.lower, interval.upper) == pytest.approx(expected, rel=0, abs=1e-10)
    assert interval.confidence_level == pytest.approx(level, rel=0, abs=1e-12)
