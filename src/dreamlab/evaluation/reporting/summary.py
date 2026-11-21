"""Render an already validated report as a human-readable summary."""

import json

from dreamlab.contracts import ArmSummary, EvaluationReport, Interval


def _estimate(value: float | None, interval: Interval | None, *, difference: bool) -> str:
    if value is None:
        return "unavailable"
    point = f"{value:+.6g} ({100 * value:+.4g} percentage points)" if difference else f"{value:.2%}"
    if interval is None:
        return f"{point} (interval unavailable)"
    if difference:
        bounds = f"{interval.lower:+.6g}, {interval.upper:+.6g}"
    else:
        bounds = f"{interval.lower:.2%}, {interval.upper:.2%}"
    return f"{point} [{bounds}] at {interval.confidence_level:.4%} confidence"


def _arm(label: str, arm: ArmSummary) -> str:
    return (
        f"{label} ({json.dumps(arm.checkpoint_id, ensure_ascii=False)}): {arm.attempted} attempts\n"
        f"  Successes: {arm.successes}, failures: {arm.failures}, "
        f"unknown: {arm.unknown}, invalid: {arm.invalid}\n"
        f"  Estimated success rate: "
        f"{_estimate(arm.success_rate, arm.success_interval, difference=False)}"
    )


def render_summary(report: EvaluationReport) -> str:
    return "\n".join(
        [
            f"Evaluation {json.dumps(report.evaluation_id, ensure_ascii=False)}",
            f"Decision: {report.decision}",
            f"Method: {report.method}",
            f"Canonical request SHA-256: {report.input_sha256}",
            "",
            f"Submitted attempts: {len(report.trial_ids)} total",
            _arm("Baseline", report.baseline),
            _arm("Candidate", report.candidate),
            "",
            "Candidate minus baseline (probability units): "
            + _estimate(report.difference, report.difference_interval, difference=True),
            "",
            report.rationale,
            "",
            *(f"Limitation: {warning}" for warning in report.warnings),
            "",
        ]
    )
