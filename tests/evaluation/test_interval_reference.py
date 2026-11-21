"""Check the test-side numerical oracles without invoking an evaluator."""

import pytest
from interval_reference import exact_interval, newcombe_difference, score_interval


def test_score_and_newcombe_at_unit_normal_quantile():
    # alpha = 2*Phi(-1); z = 1. At x=1,n=2 the roots are (3 +/- sqrt(3))/6.
    # At opposite extremes with n=2 the score intervals are [0,1/3] and [2/3,1].
    alpha = 0.3173105078629141
    assert score_interval(1, 2, alpha) == pytest.approx((0.2113248654051871, 0.7886751345948129))
    assert newcombe_difference(0, 2, 2, alpha) == pytest.approx((0.5285954792089683, 1.0))
    assert newcombe_difference(2, 0, 2, alpha) == pytest.approx((-1.0, -0.5285954792089683))


def test_binomial_inversion_at_interior_and_boundary():
    # P_p(X>=1) = 1-(1-p)^2 for n=2. At tail=1/16, p=1-sqrt(15)/4.
    assert exact_interval(1, 2, 1 / 8) == pytest.approx((0.0317541634481458, 0.9682458365518543))
    assert exact_interval(0, 4, 1 / 8) == pytest.approx((0.0, 0.5))
    assert exact_interval(4, 4, 1 / 8) == pytest.approx((0.5, 1.0))
