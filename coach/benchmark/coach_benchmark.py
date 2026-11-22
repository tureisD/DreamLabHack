"""Fixed-horizon, single-task comparison of the ordinary workflow and the coach.

This CLI never submits training jobs or starts a robot. It checks a predeclared
participant manifest and analyzes operator-entered outcomes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from scipy.stats import fisher_exact

ARMS = ("standard", "coach")


def _time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp needs a timezone: {value}")
    return parsed


def analyze(plan: dict, outcomes: list[dict]) -> dict:
    """Return descriptive fixed-horizon outcomes, or fail closed on incomplete data."""
    if plan.get("assignment_method") != "randomized_before_start":
        raise ValueError("Plan must state randomized assignment before any sessions start.")
    horizon = plan.get("horizon_minutes")
    if not isinstance(horizon, (int, float)) or isinstance(horizon, bool) or horizon <= 0:
        raise ValueError("horizon_minutes must be positive.")
    created = _time(plan["created_at"])
    if not plan.get("success_definition") or not plan.get("task_id") or not plan.get("robot_id"):
        raise ValueError("Freeze the task, robot, and validated success definition.")
    participants = plan["participants"]
    if not participants or any(p.get("arm") not in ARMS or not p.get("participant_id") for p in participants):
        raise ValueError("Each planned participant needs an ID and an assigned arm.")
    assigned = {p["participant_id"]: p["arm"] for p in participants}
    if len(assigned) != len(participants):
        raise ValueError("Duplicate planned participant ID.")
    if len(set(assigned.values())) != 2:
        raise ValueError("Both arms need planned participants.")
    counts = Counter(assigned.values())
    if abs(counts["standard"] - counts["coach"]) > 1:
        raise ValueError("This small fixed study requires balanced assignments.")
    observed = {row.get("participant_id"): row for row in outcomes}
    if len(observed) != len(outcomes) or set(observed) != set(assigned):
        raise ValueError("Provide exactly one outcome for every planned participant.")

    rows: dict[str, list[dict]] = {arm: [] for arm in ARMS}
    for participant_id, arm in assigned.items():
        row = observed[participant_id]
        started = _time(row["started_at"])
        ended = _time(row["ended_at"])
        if started <= created or ended < started:
            raise ValueError(f"Invalid chronology for {participant_id}.")
        succeeded = row.get("validated_at") is not None
        if succeeded:
            if not re.fullmatch(r"[0-9a-f]{64}", row.get("validation_report_sha256", "")):
                raise ValueError(f"Validated outcome needs an audit report SHA-256: {participant_id}.")
            validated = _time(row["validated_at"])
            if validated < started or validated > ended or (validated - started).total_seconds() / 60 > horizon:
                raise ValueError(f"Validated outcome outside the study horizon: {participant_id}.")
            time_to_success = (validated - started).total_seconds() / 60
        else:
            if (ended - started).total_seconds() / 60 < horizon:
                raise ValueError(f"Unresolved participant was not followed for the full horizon: {participant_id}.")
            time_to_success = horizon
        for key in ("demos_recorded", "faas_jobs", "faas_steps", "failed_evaluations"):
            if not isinstance(row.get(key), int) or isinstance(row[key], bool) or row[key] < 0:
                raise ValueError(f"{key} must be a nonnegative integer for {participant_id}.")
        if row["faas_steps"] > 0 and row["faas_jobs"] == 0:
            raise ValueError(f"Paid steps without a FaaS job: {participant_id}.")
        operator_minutes = row.get("operator_minutes")
        if not isinstance(operator_minutes, (int, float)) or isinstance(operator_minutes, bool) or operator_minutes < 0:
            raise ValueError(f"operator_minutes must be nonnegative for {participant_id}.")
        cost = row.get("faas_cost_usd")
        if cost is not None and (not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0):
            raise ValueError(f"faas_cost_usd must be nonnegative or null for {participant_id}.")
        rows[arm].append({**row, "validated": succeeded, "restricted_minutes": time_to_success})

    def summary(arm: str) -> dict:
        group = rows[arm]
        n = len(group)
        validated = sum(row["validated"] for row in group)
        successful_times = sorted(row["restricted_minutes"] for row in group if row["validated"])
        costs = [row["faas_cost_usd"] for row in group]
        return {
            "participants": n,
            "validated_by_horizon": validated,
            "validation_rate": validated / n,
            "mean_restricted_minutes": sum(row["restricted_minutes"] for row in group) / n,
            "successful_times_minutes": successful_times,
            "mean_demos_recorded": sum(row["demos_recorded"] for row in group) / n,
            "mean_faas_jobs": sum(row["faas_jobs"] for row in group) / n,
            "mean_faas_steps": sum(row["faas_steps"] for row in group) / n,
            "mean_failed_evaluations": sum(row["failed_evaluations"] for row in group) / n,
            "mean_operator_minutes": sum(row["operator_minutes"] for row in group) / n,
            "mean_faas_cost_usd": sum(costs) / n if all(cost is not None for cost in costs) else None,
        }

    standard = summary("standard")
    coach = summary("coach")
    table = [
        [coach["validated_by_horizon"], coach["participants"] - coach["validated_by_horizon"]],
        [standard["validated_by_horizon"], standard["participants"] - standard["validated_by_horizon"]],
    ]
    fingerprint = hashlib.sha256(json.dumps({"plan": plan, "outcomes": outcomes}, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    return {
        "study_id": plan["study_id"], "task_id": plan["task_id"], "robot_id": plan["robot_id"],
        "horizon_minutes": horizon, "plan_created_at": plan["created_at"],
        "assignment_method_claimed": plan["assignment_method"], "snapshot_sha256": fingerprint,
        "standard": standard, "coach": coach,
        "coach_minus_standard_validation_rate": coach["validation_rate"] - standard["validation_rate"],
        "coach_minus_standard_mean_restricted_minutes":
            coach["mean_restricted_minutes"] - standard["mean_restricted_minutes"],
        "fisher_two_sided_p": float(fisher_exact(table).pvalue),
        "warnings": [
            "Random assignment, validated outcomes, and costs are operator-supplied; this CLI cannot prove them.",
            "Time among only successful participants is descriptive and must not replace the fixed-horizon result.",
            "This single-task pilot does not establish benefit on other robots or tasks.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("outcomes", type=Path)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        outcomes = json.loads(args.outcomes.read_text(encoding="utf-8"))
        report = analyze(plan, outcomes)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Study cannot be analyzed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
