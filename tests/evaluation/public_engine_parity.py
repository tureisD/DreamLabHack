"""Parity probes use only the public evaluate method and shared contract types."""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from math import isclose

import numpy as np

from dreamlab.contracts import EvaluationPlan, EvaluationRequest, TaskSpec, Trial

STAMP = datetime(2026, 1, 1, tzinfo=UTC)
TASK = TaskSpec(
    task_id="synthetic-bernoulli",
    version=1,
    instruction="Software test only",
    success_rule="Generated Bernoulli label equals one",
    reset_protocol="IID draw",
    timeout_s=10,
)


@lru_cache(maxsize=2048)
def trial_for(arm, i, success):
    # These explicitly synthetic fixture IDs/URIs exercise the *eligible* API
    # branch. No real trial, human reviewer, or physical randomization is asserted.
    checkpoint = ("baseline", "candidate")[arm]
    ident = f"synthetic-{checkpoint}-{i}"
    return Trial(
        trial_id=ident,
        episode_id=ident,
        task_id=TASK.task_id,
        task_version=1,
        checkpoint_id=checkpoint,
        scenario_id="synthetic",
        session_id=ident,
        collection_mode="prospective",
        training_exposure="held_out",
        outcome="success" if success else "failure",
        label_source="human",
        human_verified=True,
        reviewer_id="synthetic-fixture",
        duration_s=1,
        source_uri=f"fixture://{ident}",
        recorded_at=STAMP + timedelta(seconds=2 * i + arm + 1),
    )


def plan_for(schedule, margin, alpha, seq):
    return EvaluationPlan(
        evaluation_id="synthetic-public-engine-parity",
        task=TASK,
        baseline_checkpoint="baseline",
        candidate_checkpoint="candidate",
        design="independent",
        scenario_ids=("synthetic",),
        random_seed=773,
        mode="group_sequential" if seq else "fixed_horizon",
        planned_looks=schedule if seq else (),
        planned_trials_per_checkpoint=schedule[-1],
        minimum_improvement=margin,
        alpha=alpha,
        created_at=STAMP,
    )


def audit_paths(engine, methods, plan, schedule, probes, tables, tol):
    """Compare every reached public look of these actual or constructed count paths."""
    checked = 0
    for path in probes:
        trials = []
        prev_n = prev_b = prev_c = 0
        for n, counts in zip(schedule, path, strict=True):
            b, c = map(int, counts)
            db, dc = b - prev_b, c - prev_c
            assert 0 <= min(db, dc) and max(db, dc) <= n - prev_n
            for i in range(prev_n, n):
                trials.extend((trial_for(0, i, i - prev_n < db), trial_for(1, i, i - prev_n < dc)))
            request = EvaluationRequest(plan=plan, trials=tuple(trials))
            report = engine.evaluate(request)
            methods.add(f"{report.method} ({report.engine_version})")
            seq = plan.mode == "group_sequential"
            tab = tables(n, seq)
            lo, hi = tab.low[b, c], tab.high[b, c]
            verdict = (
                "improved"
                if lo > plan.minimum_improvement
                else "regressed"
                if hi < 0
                else "inconclusive"
            )
            context = (
                plan.mode,
                n,
                b,
                c,
                plan.minimum_improvement,
                report.decision,
                report.rationale,
            )
            assert report.decision == verdict, context
            assert report.difference_interval is not None, context
            pairs = [
                (report.difference, c / n - b / n),
                (report.difference_interval.lower, lo),
                (report.difference_interval.upper, hi),
            ]
            for arm, k in ((report.baseline, b), (report.candidate, c)):
                assert (arm.attempted, arm.successes) == (n, k) and arm.success_interval, context
                pairs.extend(
                    [
                        (arm.success_rate, k / n),
                        (arm.success_interval.lower, tab.arm_low[k]),
                        (arm.success_interval.upper, tab.arm_high[k]),
                    ]
                )
            assert all(
                a is not None and isclose(a, ref, rel_tol=0, abs_tol=tol) for a, ref in pairs
            ), (context, pairs)
            checked += 1
            if verdict != "inconclusive":
                break  # Actual first stop. No assumptions about a post-stop transport policy.
            prev_n, prev_b, prev_c = n, b, c
    return checked


def boundary_probes(engine, methods, looks, alpha, tables, tol):
    checked = 0
    for n in (1, 8):
        plan = plan_for((n,), 0.125, alpha, False)
        paths = [[(b, c)] for b in range(n + 1) for c in range(n + 1)]
        checked += audit_paths(engine, methods, plan, (n,), paths, tables, tol)
    # On each production look, check adjacent count cells bracketing each
    # decision threshold. When possible, arrange nondirectional prior counts
    # so that a later boundary isn't masked by an earlier stop.
    for seq, schedule in [(False, (80,)), (True, looks)]:
        for margin in (0, 0.125):
            plan = plan_for(schedule, margin, alpha, seq)
            for j, n in enumerate(schedule):
                tab = tables(n, seq)
                prefix = schedule[: j + 1]
                paths = []
                for b in sorted({0, n // 8, n // 2, 7 * n // 8, n}):
                    for mask in [tab.low[b] > margin, tab.high[b] >= 0]:
                        k = int(np.searchsorted(mask, True))
                        for c in {max(0, k - 1), min(n, k)}:
                            path = []
                            for t in prefix:
                                # Move both early proportions toward 1/2 as much
                                # as the required final counts permit.
                                path.append(tuple(min(k, max(k - (n - t), t // 2)) for k in (b, c)))
                            paths.append(path)
                checked += audit_paths(engine, methods, plan, prefix, paths, tables, tol)
    return checked
