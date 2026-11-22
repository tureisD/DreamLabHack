"""Prospective IID binomial planning for the fixed Wilson/Newcombe decision rule."""

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real
from typing import Literal

import numpy as np
from scipy.stats import binom

from dreamlab.evaluation.methods.intervals import confidence_level, newcombe_bounds, wilson_bounds

# Scanning all sizes with Bisection per baseline count costs O(B^3 log B).
# This cap keeps worst-case planning bounded on a developer machine.
MAX_TRIALS_PER_ARM = 512


@dataclass(frozen=True)
class SampleSizePlan:
    """First qualifying integer, or None if no size in the budget qualifies."""

    baseline_rate: float
    alternative_gain: float
    minimum_improvement: float
    alpha: float
    target_power: float
    max_trials_per_arm: int
    trials_per_arm: int | None
    power_at_recommendation: float | None
    power_at_budget: float

    @property
    def feasible(self) -> bool:
        return self.trials_per_arm is not None


def _real(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    return float(value)


def _size(name: str, n: int) -> int:
    if isinstance(n, bool) or not isinstance(n, Integral) or not 1 <= n <= MAX_TRIALS_PER_ARM:
        raise ValueError(f"{name} must be an integer in [1, {MAX_TRIALS_PER_ARM}]")
    return int(n)


def _inputs(baseline_rate, candidate_rate, minimum_improvement, alpha, design):
    if design != "independent":
        raise ValueError("only independent, equal-arm fixed-horizon planning is supported")
    pb = _real("baseline_rate", baseline_rate)
    pc = _real("candidate_rate", candidate_rate)
    margin = _real("minimum_improvement", minimum_improvement)
    alpha = _real("alpha", alpha)
    if not (0 <= pb <= 1 and 0 <= pc <= 1 and 0 <= margin < 1):
        raise ValueError("rates must be in [0, 1] and minimum_improvement in [0, 1)")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    confidence_level(alpha)
    return pb, pc, margin, alpha


def _probability(n: int, pb: float, pc: float, margin: float, alpha: float) -> float:
    counts = np.arange(n + 1)
    rates = counts / n
    arm_bounds = wilson_bounds(rates, n, alpha)
    arm_low, arm_high = arm_bounds

    # The shared interval kernels widen a floating-point-collapsed endpoint
    # outwards to adjacent representable bounds. Search the same Newcombe lower
    # endpoint as the evaluator, rather than a surrogate p-value or overlap rule.
    first_passing = np.zeros(n + 1, dtype=int)
    last_nonpassing = np.full(n + 1, n + 1, dtype=int)
    while np.any(first_passing < last_nonpassing):
        middle = (first_passing + last_nonpassing) // 2
        index = np.minimum(middle, n)
        lower, _ = newcombe_bounds(
            rates,
            rates[index],
            arm_bounds,
            (arm_low[index], arm_high[index]),
        )
        passes = (middle <= n) & (lower > margin)
        active = first_passing < last_nonpassing
        last_nonpassing = np.where(active & passes, middle, last_nonpassing)
        first_passing = np.where(active & ~passes, middle + 1, first_passing)

    tails = binom.sf(first_passing - 1, n, pc)
    probability = np.sum(binom.pmf(counts, n, pb) * tails)
    return float(np.clip(probability, 0.0, 1.0))


def fixed_horizon_power(
    *,
    trials_per_arm: int,
    baseline_rate: float,
    candidate_rate: float,
    minimum_improvement: float,
    alpha: float = 0.05,
    design: Literal["independent"] = "independent",
) -> float:
    """P(Newcombe lower bound > margin), summing finite binomial mass (float64).

    Inputs are absolute probabilities; this also computes false improvement
    probability under a null. No peeking, replacement, attrition or clustering.
    This is conditional on the supplied true rates, not on observed pilot rates.
    """
    n = _size("trials_per_arm", trials_per_arm)
    values = _inputs(baseline_rate, candidate_rate, minimum_improvement, alpha, design)
    return _probability(n, *values)


def plan_fixed_horizon(
    *,
    baseline_rate: float,
    alternative_gain: float,
    minimum_improvement: float,
    max_trials_per_arm: int,
    target_power: float = 0.80,
    alpha: float = 0.05,
    design: Literal["independent"] = "independent",
) -> SampleSizePlan:
    """Find the smallest equal-arm budget attaining target improvement power.

    alternative_gain is candidate_rate minus baseline_rate under the assumed
    alternative, and must EXCEED the practical margin. The caller must supply
    a budget; unsupported designs, invalid probabilities and out-of-range
    computational budgets raise ValueError instead of reporting infeasibility.
    No monotonicity of power in integer n is assumed. Total attempts = 2*n.
    """
    limit = _size("max_trials_per_arm", max_trials_per_arm)
    gain = _real("alternative_gain", alternative_gain)
    pb = _real("baseline_rate", baseline_rate)
    pb, pc, margin, alpha = _inputs(pb, pb + gain, minimum_improvement, alpha, design)
    if gain <= margin or pc <= pb or pc - pb <= margin:
        raise ValueError(
            "represented candidate_rate minus baseline_rate must strictly exceed the margin"
        )
    target = _real("target_power", target_power)
    if not 0 < target < 1:
        raise ValueError("target_power must be in (0, 1)")
    at_budget = _probability(limit, pb, pc, margin, alpha)
    for n in range(1, limit + 1):
        power = at_budget if n == limit else _probability(n, pb, pc, margin, alpha)
        if power >= target:
            return SampleSizePlan(pb, gain, margin, alpha, target, limit, n, power, at_budget)
    return SampleSizePlan(pb, gain, margin, alpha, target, limit, None, None, at_budget)
