"""Independent finite-binomial checks on deterministic equal-arm planning."""

from math import comb, inf, nan, nextafter

import numpy as np
import pytest
from eval_cases import evaluate, make_payload
from statsmodels.stats.proportion import confint_proportions_2indep

from dreamlab.evaluation.methods.planning import (
    MAX_TRIALS_PER_ARM,
    fixed_horizon_power,
    plan_fixed_horizon,
)


def brute(n, pb, pc, margin, alpha):
    k = np.arange(n + 1)
    low, _ = confint_proportions_2indep(
        k[:, None], n, k[None, :], n, method="newcomb", compare="diff", alpha=alpha
    )
    return sum(
        comb(n, c) * pc**c * (1 - pc) ** (n - c) * comb(n, b) * pb**b * (1 - pb) ** (n - b)
        for c, b in zip(*np.nonzero(low > margin), strict=True)
    )


@pytest.mark.parametrize("n", [1, 2, 7, 8, 19, 40])
@pytest.mark.parametrize(
    "pb,pc,margin,alpha",
    [
        (0, 1, 0, 0.05),
        (0.25, 0.75, 0.125, 0.1),
        (1, 0, 0.1, 0.01),
        (0.875, 0.875, 0, 0.05),
        (0.5, 0.625, 0.125, 0.05),
        (0.01, 0.99, 0.999, 0.2),
        (0.5, 0.25, 0, 0.9),
    ],
)
def test_power_is_probability_of_actual_strict_rule(n, pb, pc, margin, alpha):
    actual = fixed_horizon_power(
        trials_per_arm=n,
        baseline_rate=pb,
        candidate_rate=pc,
        minimum_improvement=margin,
        alpha=alpha,
    )
    assert actual == pytest.approx(brute(n, pb, pc, margin, alpha), abs=2e-12, rel=0)


def test_threshold_equality_is_not_an_improvement():
    margin, _ = confint_proportions_2indep(8, 8, 0, 8, method="newcomb", compare="diff")
    case = {"trials_per_arm": 8, "baseline_rate": 0, "candidate_rate": 1}
    assert fixed_horizon_power(**case, minimum_improvement=margin) == 0
    assert fixed_horizon_power(**case, minimum_improvement=nextafter(margin, -inf)) == 1


def test_planner_and_public_engine_share_machine_extreme_interval_rule():
    alpha = nextafter(1.0, 0.0)
    data = {
        "trials_per_arm": 4,
        "baseline_rate": 0.0,
        "candidate_rate": 1.0,
        "minimum_improvement": 0.0,
        "alpha": alpha,
    }
    request = make_payload("0" * 4, "1" * 4, budget=4, alpha=alpha, margin=0.0)
    report = evaluate(request)
    assert report.decision == "improved"
    assert report.difference_interval.lower > 0
    assert fixed_horizon_power(**data) == 1.0
    plan = plan_fixed_horizon(
        baseline_rate=0.0,
        alternative_gain=1.0,
        minimum_improvement=0.0,
        max_trials_per_arm=4,
        alpha=alpha,
    )
    assert plan.trials_per_arm == 1

    # The public endpoint is the single strict decision boundary for both the
    # evaluator and planner, including adjacent representable float margins.
    # alpha is at the machine limit here; immediately above the endpoint is
    # exactly 1.0 and therefore outside the contract's margin domain. Use the
    # ordinary alpha to verify adjacent legal margin floats in both public paths.
    request = make_payload("0" * 4, "1" * 4, budget=4, alpha=0.05, margin=0.0)
    report = evaluate(request)
    lower = report.difference_interval.lower
    boundary_data = {**data, "alpha": 0.05}
    for margin, decision, power in [
        (nextafter(lower, -inf), "improved", 1.0),
        (lower, "inconclusive", 0.0),
        (nextafter(lower, inf), "inconclusive", 0.0),
    ]:
        request["plan"]["minimum_improvement"] = margin
        assert evaluate(request).decision == decision
        assert fixed_horizon_power(**{**boundary_data, "minimum_improvement": margin}) == power


def test_extreme_alpha_planner_matches_every_public_count_cell():
    # The second reviewer suggested extending the machine-extreme-alpha probe
    # beyond perfect separation. Exercise every n=4 count pair through the public
    # contract, then independently sum binomial cell masses for the engine's
    # exact strict verdict and compare that total to the planner's power.
    alpha = nextafter(1.0, 0.0)
    baseline_rate, candidate_rate, margin = 0.25, 0.75, 0.125
    expected = 0.0
    n = 4
    for b in range(n + 1):
        for c in range(n + 1):
            request = make_payload(
                "1" * b + "0" * (n - b),
                "1" * c + "0" * (n - c),
                budget=n,
                alpha=alpha,
                margin=margin,
            )
            report = evaluate(request)
            low = report.difference_interval.lower
            high = report.difference_interval.upper
            decision = "improved" if low > margin else "regressed" if high < 0.0 else "inconclusive"
            assert report.decision == decision
            if decision == "improved":
                expected += (
                    comb(n, b)
                    * baseline_rate**b
                    * (1 - baseline_rate) ** (n - b)
                    * comb(n, c)
                    * candidate_rate**c
                    * (1 - candidate_rate) ** (n - c)
                )
    assert fixed_horizon_power(
        trials_per_arm=n,
        baseline_rate=baseline_rate,
        candidate_rate=candidate_rate,
        minimum_improvement=margin,
        alpha=alpha,
    ) == pytest.approx(expected, abs=2e-15, rel=0)


def test_minimal_plan_over_all_integers_and_infeasibility():
    settings = dict(
        baseline_rate=0.25,
        alternative_gain=0.5,
        minimum_improvement=0.125,
        alpha=0.1,
        target_power=0.8,
    )
    exact = [brute(n, 0.25, 0.75, 0.125, 0.1) for n in range(1, 41)]
    expected_n = next(n for n, power in enumerate(exact, 1) if power >= 0.8)
    result = plan_fixed_horizon(**settings, max_trials_per_arm=40)
    assert result.feasible and result.trials_per_arm == expected_n
    assert result.power_at_recommendation == pytest.approx(exact[expected_n - 1], abs=2e-12)
    assert result.power_at_budget == pytest.approx(exact[-1], abs=2e-12)
    short = plan_fixed_horizon(**settings, max_trials_per_arm=expected_n - 1)
    assert not short.feasible and short.trials_per_arm is None
    assert short.power_at_recommendation is None and short.power_at_budget < 0.8
    assert plan_fixed_horizon(**settings, max_trials_per_arm=expected_n).feasible


def test_nonmonotone_power_budget_must_not_be_used_to_rule_out_smaller_sizes():
    powers = [brute(n, 0.25, 0.75, 0.125, 0.05) for n in range(1, 41)]
    i = next(i for i in range(1, len(powers)) if powers[i] < max(powers[:i]) - 1e-6)
    target = (powers[i] + max(powers[:i])) / 2
    result = plan_fixed_horizon(
        baseline_rate=0.25,
        alternative_gain=0.5,
        minimum_improvement=0.125,
        target_power=target,
        max_trials_per_arm=i + 1,
    )
    assert result.feasible and result.power_at_budget < target
    assert result.trials_per_arm == next(n for n, q in enumerate(powers, 1) if q >= target)


@pytest.mark.parametrize(
    "key,value",
    [
        ("baseline_rate", True),
        ("baseline_rate", -0.1),
        ("baseline_rate", nan),
        ("alternative_gain", inf),
        ("alternative_gain", 0.125),
        ("alternative_gain", nextafter(0.125, 1.0)),
        ("alternative_gain", 0.9),
        ("alternative_gain", -0.25),
        ("minimum_improvement", 1),
        ("minimum_improvement", -0.1),
        ("alpha", 0),
        ("alpha", 1),
        ("alpha", 1e-300),
        ("target_power", 0),
        ("target_power", 1),
        ("max_trials_per_arm", 0),
        ("max_trials_per_arm", True),
        ("max_trials_per_arm", 5.0),
        ("max_trials_per_arm", MAX_TRIALS_PER_ARM + 1),
        ("design", "paired"),
        ("design", "observational"),
    ],
)
def test_invalid_plans_are_not_budget_infeasibility(key, value):
    case = dict(
        baseline_rate=0.25, alternative_gain=0.5, minimum_improvement=0.125, max_trials_per_arm=40
    )
    with pytest.raises(ValueError):
        plan_fixed_horizon(**{**case, key: value})


def test_cap_and_extreme_rates():
    assert (
        fixed_horizon_power(
            trials_per_arm=MAX_TRIALS_PER_ARM,
            baseline_rate=0,
            candidate_rate=1,
            minimum_improvement=0.125,
        )
        == 1
    )
    assert not plan_fixed_horizon(
        baseline_rate=0.8, alternative_gain=0.2, minimum_improvement=0.1, max_trials_per_arm=1
    ).feasible
