"""Evaluate a single v1 JSON request and publish a new artifact directory."""

import argparse
import json
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from dreamlab.contracts import EvaluationReport, EvaluationRequest, EvaluationUnavailable
from dreamlab.evaluation.artifacts import OutputCollision, StagedBundle, staged_bundle
from dreamlab.evaluation.provenance import build_manifest
from dreamlab.evaluation.reporting.summary import render_summary

INVALID_INPUT = 2
EVALUATOR_ERROR = 3
REPORT_MISMATCH = 4
IO_ERROR = 5


def _authoritative_report(request: EvaluationRequest) -> EvaluationReport:
    # A missing evaluation extra should produce diagnostics, even though the
    # dependency is not needed to parse the command or validate its request.
    try:
        from dreamlab.evaluation.engine import StatisticalEvaluator
    except ModuleNotFoundError as exc:
        if exc.name in {"numpy", "scipy"}:
            raise EvaluationUnavailable(
                "Install the project's eval extra to run the evaluator."
            ) from exc
        raise

    return StatisticalEvaluator().evaluate(request)


def _evaluate(request: EvaluationRequest) -> EvaluationReport:
    return _authoritative_report(request)


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _validation_details(exc: ValidationError) -> list[dict]:
    return [
        {"field": list(error["loc"]), "code": error["type"], "message": error["msg"]}
        for error in exc.errors(include_input=False, include_context=False, include_url=False)
    ]


def _reject(
    staging: StagedBundle, exit_code: int, code: str, stage: str, message: str, details: list[dict]
) -> int:
    staging.write_bytes(
        "diagnostics.json",
        _json_bytes(
            {
                "schema_version": 1,
                "exit_code": exit_code,
                "code": code,
                "stage": stage,
                "message": message,
                "details": details,
            }
        ),
    )
    return exit_code


def _os_message(error: OSError) -> str:
    return error.strerror or str(error)


def _correspondence_errors(
    request: EvaluationRequest, report: EvaluationReport, canonical_hash: str
) -> list[dict]:
    plan = request.plan
    # The report has no separate v1 task field. The request validates membership
    # for every task/version, and the canonical hash binds that task and all rows.
    checks = [
        (["evaluation_id"], plan.evaluation_id, report.evaluation_id),
        (["input_sha256"], canonical_hash, report.input_sha256),
        (["trial_ids"], tuple(row.trial_id for row in request.trials), report.trial_ids),
    ]
    counts = Counter((trial.checkpoint_id, trial.outcome) for trial in request.trials)
    for arm, checkpoint, summary in (
        ("baseline", plan.baseline_checkpoint, report.baseline),
        ("candidate", plan.candidate_checkpoint, report.candidate),
    ):
        outcomes = {
            outcome: counts[checkpoint, outcome]
            for outcome in ("success", "failure", "unknown", "invalid")
        }
        checks.extend(
            [
                ([arm, "checkpoint_id"], checkpoint, summary.checkpoint_id),
                ([arm, "attempted"], sum(outcomes.values()), summary.attempted),
                ([arm, "successes"], outcomes["success"], summary.successes),
                ([arm, "failures"], outcomes["failure"], summary.failures),
                ([arm, "unknown"], outcomes["unknown"], summary.unknown),
                ([arm, "invalid"], outcomes["invalid"], summary.invalid),
            ]
        )
    errors = [
        _mismatch(field, expected, actual)
        for field, expected, actual in checks
        if expected != actual
    ]
    errors.extend(_estimate_errors(request, report))
    if errors:
        return errors
    try:
        expected_report = _authoritative_report(request)
    except Exception as exc:
        errors.append(
            _mismatch(
                ["authoritative_evaluation"],
                "successful deterministic evaluation",
                {"exception_type": type(exc).__name__, "message": str(exc)},
            )
        )
    else:
        expected_payload = expected_report.model_dump(mode="json")
        actual_payload = report.model_dump(mode="json")
        for field in (
            "decision",
            "baseline",
            "candidate",
            "difference",
            "difference_interval",
            "method",
            "engine_version",
            "warnings",
            "rationale",
        ):
            if expected_payload[field] != actual_payload[field]:
                errors.append(_mismatch([field], expected_payload[field], actual_payload[field]))
    return errors


def _mismatch(field: list[str], expected: object, actual: object) -> dict:
    return {"field": field, "expected": expected, "actual": actual}


def _estimate_errors(request: EvaluationRequest, report: EvaluationReport) -> list[dict]:
    # Raw counts can include trials after a terminal sequential look. Check
    # internal consistency using decision-time estimates, not those raw counts.
    arm_alpha = request.plan.alpha
    if request.plan.mode == "group_sequential":
        arm_alpha /= 2 * len(request.plan.planned_looks)
    estimates = (
        (
            ["baseline"],
            "success_rate",
            report.baseline.success_rate,
            "success_interval",
            report.baseline.success_interval,
            1.0 - arm_alpha,
        ),
        (
            ["candidate"],
            "success_rate",
            report.candidate.success_rate,
            "success_interval",
            report.candidate.success_interval,
            1.0 - arm_alpha,
        ),
        (
            [],
            "difference",
            report.difference,
            "difference_interval",
            report.difference_interval,
            1.0 - request.plan.alpha,
        ),
    )
    errors = []
    for prefix, point_field, point, interval_field, interval, level in estimates:
        if report.decision == "not_evaluable":
            if point is not None:
                errors.append(_mismatch([*prefix, point_field], None, point))
            if interval is not None:
                errors.append(_mismatch([*prefix, interval_field], None, interval.model_dump()))
            continue
        if point is None:
            errors.append(_mismatch([*prefix, point_field], "finite estimate", None))
        if interval is None:
            errors.append(_mismatch([*prefix, interval_field], "nonempty interval", None))
            continue
        if interval.lower >= interval.upper:
            errors.append(
                _mismatch([*prefix, interval_field], "lower < upper", interval.model_dump())
            )
        if point is not None and not interval.lower <= point <= interval.upper:
            errors.append(
                _mismatch([*prefix, point_field], [interval.lower, interval.upper], point)
            )
        if interval.confidence_level != level:
            errors.append(
                _mismatch(
                    [*prefix, interval_field, "confidence_level"], level, interval.confidence_level
                )
            )
    b, c = report.baseline.success_rate, report.candidate.success_rate
    if b is not None and c is not None and report.difference is not None:
        if report.difference != c - b:
            errors.append(_mismatch(["difference"], c - b, report.difference))
    if report.decision != "not_evaluable" and (interval := report.difference_interval) is not None:
        if interval.lower > request.plan.minimum_improvement:
            expected = "improved"
        elif interval.upper < 0.0:
            expected = "regressed"
        else:
            expected = "inconclusive"
        if report.decision != expected:
            errors.append(_mismatch(["decision"], expected, report.decision))
    return errors


def _read_input(input_path: str) -> bytes:
    if input_path != "-":
        return Path(input_path).read_bytes()
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        raise OSError("Binary standard input is unavailable.")
    return stream.read()


def _write_bundle(staging: StagedBundle, input_path: str) -> int:
    try:
        raw = _read_input(input_path)
    except (OSError, ValueError) as exc:
        message = _os_message(exc) if isinstance(exc, OSError) else str(exc)
        return _reject(staging, IO_ERROR, "input_unreadable", "read_input", message, [])
    staging.write_bytes("request.raw.json", raw)
    try:
        request = EvaluationRequest.model_validate_json(raw)
        canonical = json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except ValidationError as exc:
        return _reject(
            staging,
            INVALID_INPUT,
            "malformed_request",
            "validate_request",
            "Request must be valid EvaluationRequest v1 JSON.",
            _validation_details(exc),
        )
    except ValueError as exc:
        return _reject(
            staging, INVALID_INPUT, "malformed_request", "validate_request", str(exc), []
        )
    staging.write_bytes("request.json", canonical)

    try:
        result = _evaluate(request)
    except Exception as exc:
        code = (
            "evaluator_unavailable" if isinstance(exc, EvaluationUnavailable) else "evaluator_error"
        )
        return _reject(
            staging,
            EVALUATOR_ERROR,
            code,
            "evaluate",
            "Evaluator raised an exception.",
            [{"exception_type": type(exc).__name__, "message": str(exc)}],
        )

    try:
        if not isinstance(result, EvaluationReport):
            raise TypeError(f"Expected EvaluationReport, got {type(result).__name__}.")
        # Pydantic's JSON encoder can coerce a nonfinite float to null.
        # Reject it explicitly at the artifact boundary.
        payload = result.model_dump(mode="json", warnings="error")
        wire = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        )
        report = EvaluationReport.model_validate_json(wire, strict=True)
    except Exception as exc:
        details = (
            _validation_details(exc)
            if isinstance(exc, ValidationError)
            else [{"exception_type": type(exc).__name__, "message": str(exc)}]
        )
        return _reject(
            staging,
            REPORT_MISMATCH,
            "invalid_report",
            "validate_report",
            "Evaluator output failed report validation.",
            details,
        )
    if errors := _correspondence_errors(request, report, sha256(canonical).hexdigest()):
        return _reject(
            staging,
            REPORT_MISMATCH,
            "report_mismatch",
            "verify_report",
            "Report does not correspond to the submitted request.",
            errors,
        )

    manifest = build_manifest(request.plan, report, submitted=raw, canonical=canonical)
    staging.write_bytes("manifest.json", _json_bytes(manifest))
    staging.write_bytes("summary.txt", render_summary(report).encode("utf-8"))
    staging.write_bytes("report.json", wire)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dream-eval", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="evaluate one request snapshot")
    evaluate.add_argument(
        "--input", required=True, help="request JSON path or '-' for standard input"
    )
    evaluate.add_argument(
        "--output-dir", required=True, type=Path, help="new directory for artifacts"
    )
    args = parser.parse_args(argv)
    try:
        with staged_bundle(args.output_dir) as staging:
            status = _write_bundle(staging, args.input)
    except OutputCollision as exc:
        print(f"dream-eval: output_collision: {exc}", file=sys.stderr)
        return IO_ERROR
    except OSError as exc:
        print(
            f"dream-eval: output_error: could not write or finalize artifacts in "
            f"{str(args.output_dir)!r}: {_os_message(exc)}",
            file=sys.stderr,
        )
        return IO_ERROR
    if status:
        diagnostics = args.output_dir / "diagnostics.json"
        print(f"dream-eval: evaluation failed. See {str(diagnostics)!r}.", file=sys.stderr)
    return status
