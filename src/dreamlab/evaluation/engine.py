"""Pure protocol implementation for prospective independent two-checkpoint comparisons."""

from dreamlab.contracts import EvaluationReport, EvaluationRequest
from dreamlab.evaluation.methods.intervals import (
    Comparison,
    UnrepresentableInterval,
    fixed_horizon,
    sequential_look,
)
from dreamlab.evaluation.methods.validation import Evidence
from dreamlab.evaluation.reporting.report import build_report


class StatisticalEvaluator:
    def evaluate(self, request: EvaluationRequest) -> EvaluationReport:
        evidence = Evidence(request.plan)
        history: list[str] = []
        if request.plan.mode == "fixed_horizon":
            comparison = _fixed(request, evidence)
        else:
            comparison = _replay(request, evidence, history)
        # An otherwise terminal replay prefix cannot make contradictory source
        # chronology valid. Keep counts, IDs, checksum and history, but withhold
        # all snapshot inference when any supplied row predates an earlier row.
        if evidence.temporal_error:
            comparison = None
        return build_report(request, evidence, comparison, history)


def _fixed(request: EvaluationRequest, evidence: Evidence) -> Comparison | None:
    for trial in request.trials:
        evidence.record(trial)
    n = request.plan.planned_trials_per_checkpoint
    if (evidence.baseline.attempted, evidence.candidate.attempted) != (n, n):
        evidence.problems.add("Fixed-horizon inference requires the exact planned attempt budget.")
    else:
        evidence.check_scenarios()
    if not evidence.problems:
        try:
            return fixed_horizon(
                evidence.baseline.outcomes["success"],
                evidence.candidate.outcomes["success"],
                n,
                request.plan.alpha,
            )
        except UnrepresentableInterval as exc:
            evidence.problems.add(str(exc))
    return None


def _replay(
    request: EvaluationRequest, evidence: Evidence, history: list[str]
) -> Comparison | None:
    plan = request.plan
    looks = iter(plan.planned_looks)
    target = next(looks)  # v1 guarantees a nonempty schedule ending at the budget.
    comparison = None
    terminal = False
    blocked = False
    for trial in request.trials:
        evidence.record(trial, post_stop=terminal)
        if terminal or blocked:
            continue
        comparison = None  # An earlier nonterminal look is not evidence at an unplanned look.
        b, c = evidence.baseline.attempted, evidence.candidate.attempted
        if max(b, c) > target:
            evidence.problems.add(
                f"Skipped declared look at {target} attempts per arm in the submitted order; "
                "a balanced prefix cannot be reconstructed retrospectively."
            )
            blocked = True
            continue
        if (b, c) != (target, target):
            continue
        evidence.check_scenarios()
        if evidence.problems:
            blocked = True
            history.append(f"{target}: not_evaluable")
            continue
        try:
            comparison = sequential_look(
                evidence.baseline.outcomes["success"],
                evidence.candidate.outcomes["success"],
                target,
                plan.alpha,
                len(plan.planned_looks),
            )
        except UnrepresentableInterval as exc:
            evidence.problems.add(str(exc))
            blocked = True
            history.append(f"{target}: not_evaluable")
            continue
        decision = comparison.verdict(plan.minimum_improvement)
        history.append(f"{target}: {decision}")
        terminal = decision != "inconclusive" or target == plan.planned_trials_per_checkpoint
        if not terminal:
            target = next(looks)

    if comparison is None and not evidence.problems:
        evidence.problems.add(f"Not at a declared look; next look is {target} attempts per arm.")
    return comparison
