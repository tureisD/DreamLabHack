"""Build deterministic v1 reports without mixing decision counts and raw totals."""

import hashlib
import json

from dreamlab.contracts import ArmSummary, EvaluationReport, EvaluationRequest, Interval
from dreamlab.evaluation.methods.intervals import Comparison
from dreamlab.evaluation.methods.validation import Counts, Evidence

ENGINE_VERSION = "1.0.0"


def _summary(
    checkpoint: str, counts: Counts, rate: float | None, interval: Interval | None
) -> ArmSummary:
    return ArmSummary(
        checkpoint_id=checkpoint,
        attempted=counts.attempted,
        successes=counts.outcomes["success"],
        failures=counts.outcomes["failure"],
        unknown=counts.outcomes["unknown"],
        invalid=counts.outcomes["invalid"],
        success_rate=rate,
        success_interval=interval,
    )


def build_report(
    request: EvaluationRequest,
    evidence: Evidence,
    comparison: Comparison | None,
    history: list[str],
) -> EvaluationReport:
    plan = request.plan
    fixed = plan.mode == "fixed_horizon"
    method = (
        "Fixed-horizon: two-sided Wilson score arm intervals and Newcombe difference (method 10)"
        if fixed
        else "Group-sequential: two-sided Clopper-Pearson arms at alpha/(2*K); "
        "simultaneous difference by subtraction (Bonferroni)"
    )
    b, c = evidence.baseline.attempted, evidence.candidate.attempted
    budget = plan.planned_trials_per_checkpoint
    status = "met" if b == c == budget else "exceeded" if max(b, c) > budget else "incomplete"
    details = [
        (
            f"Submitted totals: baseline {b}, candidate {c} attempts; "
            f"planned budget {budget} per checkpoint ({status})."
        )
    ]
    warnings = [
        (
            "Inference assumes independent binomial attempts under a common task and scenario mix. "
            "The plan, seed and IDs do not prove randomization, independence or reset compliance."
        ),
        (
            "A single planned comparison does not adjust for checkpoint selection. "
            "Task success alone does not establish safety, cost or readiness to deploy. "
            "Synthetic examples validate software, not robot performance."
        ),
    ]
    if history:
        details.append("Declared look history (attempts per arm): " + "; ".join(history) + ".")

    if comparison is None:
        decision = "not_evaluable"
        details.extend(sorted(evidence.problems))
        details.append("No inferential estimates are issued for this snapshot.")
        baseline_rate = candidate_rate = None
    else:
        decision = comparison.verdict(plan.minimum_improvement)
        n = comparison.n
        x, y = comparison.baseline_successes, comparison.candidate_successes
        baseline_rate, candidate_rate = x / n, y / n
        last_id = json.dumps(request.trials[2 * n - 1].trial_id, ensure_ascii=False)
        details.append(
            f"Decision-time prefix: first {2 * n} of {len(request.trials)} submitted trial IDs "
            f"in order, through {last_id} inclusive. Decision counts: baseline successes={x}, "
            f"failures={n - x}; candidate successes={y}, failures={n - y} ({n} attempts per arm; "
            "no unknown or invalid outcomes). Arm rates and intervals, and the candidate-minus-"
            "baseline difference and interval in probability units, refer to this prefix."
        )
        if 2 * n < len(request.trials):
            warnings.append(
                f"First terminal decision retained. The {len(request.trials) - 2 * n} post-stop "
                "attempts are included in all raw counts, trial IDs and checksum, but were not "
                "used to validate or change the decision-time estimates."
            )
        if fixed:
            details.append(
                f"The intervals have nominal fixed-sample confidence 1 - {plan.alpha!r}; "
                "they do not provide repeated-look error control."
            )
        else:
            details.append(
                f"K={len(plan.planned_looks)} predeclared looks; each arm interval has two-sided "
                f"error {plan.alpha / (2 * len(plan.planned_looks))!r}. The difference interval "
                f"has simultaneous coverage of at least 1 - {plan.alpha!r} under the assumptions."
            )
        if decision == "improved":
            details.append(
                f"The lower difference bound exceeds the margin {plan.minimum_improvement}."
            )
        elif decision == "regressed":
            details.append("The upper difference bound is below zero.")
        else:
            interim = not fixed and n < budget
            details.append(
                f"Neither directional threshold is crossed (improvement margin "
                f"{plan.minimum_improvement}, regression threshold 0); this is not equivalence."
            )
            if interim:
                details.append("Interim look: continue to the next declared look.")

    payload = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return EvaluationReport(
        evaluation_id=plan.evaluation_id,
        decision=decision,
        baseline=_summary(
            plan.baseline_checkpoint,
            evidence.baseline,
            baseline_rate,
            comparison.baseline_interval if comparison else None,
        ),
        candidate=_summary(
            plan.candidate_checkpoint,
            evidence.candidate,
            candidate_rate,
            comparison.candidate_interval if comparison else None,
        ),
        difference=comparison.difference if comparison else None,
        difference_interval=comparison.difference_interval if comparison else None,
        method=method,
        engine_version=ENGINE_VERSION,
        input_sha256=hashlib.sha256(payload).hexdigest(),
        trial_ids=tuple(trial.trial_id for trial in request.trials),
        warnings=tuple(warnings),
        rationale=" ".join(details),
    )
