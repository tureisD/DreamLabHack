"""Independent numerical oracles; no evaluator or production interval APIs."""

from math import comb, fsum, hypot, sqrt
from statistics import NormalDist

from scipy.optimize import brentq


def score_interval(x, n, alpha):
    # Invert (x - n*p)^2 <= z^2*n*p*(1-p), solving the quadratic in p.
    z2 = NormalDist().inv_cdf(1 - alpha / 2) ** 2
    center = 2 * x + z2
    radius = sqrt(z2 * (4 * x * (n - x) / n + z2))
    denom = 2 * (n + z2)
    return (
        0.0 if x == 0 else (center - radius) / denom,
        1.0 if x == n else (center + radius) / denom,
    )


def newcombe_difference(b, c, n, alpha):
    # Newcombe's uncorrected independent-score combination (candidate minus baseline).
    b_lo, b_hi = score_interval(b, n, alpha)
    c_lo, c_hi = score_interval(c, n, alpha)
    p_b, p_c = b / n, c / n
    return (
        p_c - p_b - hypot(p_c - c_lo, b_hi - p_b),
        p_c - p_b + hypot(c_hi - p_c, p_b - b_lo),
    )


def exact_interval(x, n, arm_error):
    # Invert finite binomial tails, independently of a library's beta quantiles.
    tail = arm_error / 2

    def lower(k):
        if k == 0:
            return 0.0
        if k == n:
            return tail ** (1 / n)

        def upper_tail(p):
            return fsum(comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))

        return brentq(lambda p: upper_tail(p) - tail, 0.0, 1.0, xtol=1e-15)

    return lower(x), 1 - lower(n - x)
