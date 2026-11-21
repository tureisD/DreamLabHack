"""Public snapshot, checksum and report reproducibility; no hardware assertions."""

import json
from copy import deepcopy

from eval_cases import assert_snapshot, digest, evaluate, make_payload

from dreamlab.contracts import EvaluationReport, EvaluationRequest
from dreamlab.evaluation.engine import StatisticalEvaluator


def test_report_is_deterministic_json_and_evaluation_does_not_change_snapshot():
    payload = make_payload("01010", "11100", budget=5)
    payload["trials"][0]["reviewer_id"] = "r\u00e9viseur-1"
    request = EvaluationRequest.model_validate(payload)
    serialized = request.model_dump_json()
    engine = StatisticalEvaluator()
    report = engine.evaluate(request)
    assert_snapshot(report, request)
    assert request.model_dump_json() == serialized
    restored = EvaluationRequest.model_validate_json(serialized)
    assert engine.evaluate(restored) == report == StatisticalEvaluator().evaluate(restored)
    # allow_nan=False rejects non-standard numeric tokens instead of normalizing them to null.
    wire = json.dumps(report.model_dump(mode="json"), allow_nan=False)
    assert EvaluationReport.model_validate_json(wire) == report
    assert report.method.strip() and report.rationale.strip() and report.engine_version.strip()


def test_only_meaningful_input_differences_change_the_canonical_hash():
    data = make_payload("01", "10", budget=2)
    report = evaluate(data)
    # Reordering object keys does not change the public snapshot.
    reordered = {
        "trials": [dict(reversed(row.items())) for row in data["trials"]],
        "plan": dict(reversed(data["plan"].items())),
    }
    assert evaluate(reordered) == report
    # Reordering rows, even without changing any row, is a different input.
    permutation = deepcopy(data)
    permutation["trials"].reverse()
    exposure = deepcopy(data)
    exposure["trials"][0]["label_source"] = "vision"
    config = deepcopy(data)
    config["plan"]["random_seed"] += 1
    inputs = [EvaluationRequest.model_validate(v) for v in (data, permutation, exposure, config)]
    checksums = [evaluate(v).input_sha256 for v in (data, permutation, exposure, config)]
    assert checksums == [digest(request) for request in inputs]
    assert len(set(checksums)) == 4
