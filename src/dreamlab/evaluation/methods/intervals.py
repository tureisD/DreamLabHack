"""Two-arm binomial comparisons in candidate-minus-baseline probability units."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np
from scipy.special import betainccinv, betaincinv, ndtri

from dreamlab.contracts import Interval

type Verdict = Literal["improved", "regressed", "inconclusive"]


class UnrepresentableInterval(ValueError):
    """The requested confidence statement cannot be represented by contract v1."""


def confidence_level(alpha: float) -> float:
    level = 1.0 - alpha
    if not 0.0 < level < 1.0:
        raise UnrepresentableInterval("The requested confidence level is not representable.")
    return level


def _interval(lower: float, upper: float, level: float) -> Interval:
    if not (isfinite(lower) and isfinite(upper) and lower < upper):
        raise UnrepresentableInterval("The requested interval is not numerically representable.")
    return Interval(lower=lower, upper=upper, confidence_level=level)


@dataclass(frozen=True, slots=True)
class Comparison:
    # A comparison is possible only at a balanced, eligible prefix.
    n: int
    baseline_successes: int
    candidate_successes: int
    baseline_interval: Interval
    candidate_interval: Interval
    difference_interval: Interval

    @property
    def difference(self) -> float:
        return self.candidate_successes / self.n - self.baseline_successes / self.n

    def verdict(self, margin: float) -> Verdict:
        if self.difference_interval.lower > margin:
            return "improved"
        if self.difference_interval.upper < 0.0:
            return "regressed"
        return "inconclusive"


def _round_collapsed_bounds(lower, upper, minimum, maximum):
    # An interval narrower than one floating-point step can round to a point.
    # Widen that rounded point outward to the nearest representable bounds.
    collapsed = lower == upper
    if np.any(collapsed):
        with np.errstate(under="ignore"):
            lower = np.where(collapsed, np.maximum(minimum, np.nextafter(lower, -np.inf)), lower)
            upper = np.where(collapsed, np.minimum(maximum, np.nextafter(upper, np.inf)), upper)
    return lower, upper


def wilson_bounds(rate, n: int, alpha: float):
    """Wilson bounds for an observed rate or array of rates at one sample size."""
    confidence_level(alpha)
    z = -float(ndtri(alpha / 2))
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (rate + z2 / (2 * n)) / denominator
    radius = z * np.sqrt(rate * (1.0 - rate) / n + z2 / (4 * n**2)) / denominator
    lower = np.where(rate == 0.0, 0.0, np.maximum(0.0, center - radius))
    upper = np.where(rate == 1.0, 1.0, np.minimum(1.0, center + radius))
    return _round_collapsed_bounds(lower, upper, 0.0, 1.0)


def newcombe_bounds(baseline_rate, candidate_rate, baseline_bounds, candidate_bounds):
    """Newcombe method 10 bounds for scalar rates or broadcastable arrays."""
    b_lo, b_hi = baseline_bounds
    c_lo, c_hi = candidate_bounds
    effect = candidate_rate - baseline_rate
    lower = effect - np.sqrt((candidate_rate - c_lo) ** 2 + (b_hi - baseline_rate) ** 2)
    upper = effect + np.sqrt((c_hi - candidate_rate) ** 2 + (baseline_rate - b_lo) ** 2)
    return _round_collapsed_bounds(np.maximum(-1.0, lower), np.minimum(1.0, upper), -1.0, 1.0)


def fixed_horizon(
    baseline_successes: int, candidate_successes: int, n: int, alpha: float
) -> Comparison:
    """Wilson score arms and uncorrected Newcombe independent difference (method 10)."""
    level = confidence_level(alpha)
    b, c = baseline_successes / n, candidate_successes / n
    baseline_bounds = wilson_bounds(b, n, alpha)
    candidate_bounds = wilson_bounds(c, n, alpha)
    diff_bounds = newcombe_bounds(b, c, baseline_bounds, candidate_bounds)

    def interval(bounds):
        lower, upper = bounds
        return _interval(float(lower), float(upper), level)

    return Comparison(
        n,
        baseline_successes,
        candidate_successes,
        interval(baseline_bounds),
        interval(candidate_bounds),
        interval(diff_bounds),
    )


def _clopper_pearson(successes: int, n: int, tail: float, level: float) -> Interval:
    # Invert the survival function directly: 1 - tail can round to 1.
    lower = float(betaincinv(successes, n - successes + 1, tail)) if successes else 0.0
    upper = float(betainccinv(successes + 1, n - successes, tail)) if successes < n else 1.0
    return _interval(lower, upper, level)


def sequential_look(
    baseline_successes: int, candidate_successes: int, n: int, alpha: float, looks: int
) -> Comparison:
    """Two-sided exact arm intervals; union bound across BOTH arms and ALL looks."""
    level = confidence_level(alpha)
    arm_alpha = alpha / (2 * looks)
    arm_level = confidence_level(arm_alpha)
    baseline = _clopper_pearson(baseline_successes, n, arm_alpha / 2, arm_level)
    candidate = _clopper_pearson(candidate_successes, n, arm_alpha / 2, arm_level)
    effect = _interval(candidate.lower - baseline.upper, candidate.upper - baseline.lower, level)
    return Comparison(n, baseline_successes, candidate_successes, baseline, candidate, effect)
