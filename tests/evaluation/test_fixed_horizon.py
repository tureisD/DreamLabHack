"""Black-box fixed-horizon evidence and threshold tests on synthetic records."""

from itertools import product
from math import nextafter

import pytest
from eval_cases import NON_DIRECTIONAL, assert_interval, evaluate, make_payload
from interval_reference import newcombe_difference, score_interval


@pytest.mark.parametrize(
    ("n", "b", "c", "alpha", "margin", "decision"),
    [
        (30, 10, 19, 0.05, 0.04, "improved"),  # Wilson arm intervals overlap.
        (30, 10, 19, 0.05, 0.10, "inconclusive"),  # Same effect, different margin.
        (30, 19, 10, 0.05, 0.40, "regressed"),  # Regression compares to zero.
        (30, 10, 19, 0.01, 0.04, "inconclusive"),  # Cannot hardcode 95%.
        (1, 0, 1, 0.05, 0.0, "inconclusive"),
        (12, 0, 0, 0.05, 0.0, "inconclusive"),
        (12, 12, 12, 0.05, 0.0, "inconclusive"),
        (12, 0, 12, 0.05, 0.99, "inconclusive"),
        (12, 12, 0, 0.05, 0.99, "regressed"),
    ],
)
def test_completed_fixed_comparison(n, b, c, alpha, margin, decision):
    payload = make_payload(
        "1" * b + "0" * (n - b), "1" * c + "0" * (n - c), budget=n, alpha=alpha, margin=margin
    )
    report = evaluate(payload)
    assert report.decision == decision
    assert report.baseline.success_rate == pytest.approx(b / n)
    assert report.candidate.success_rate == pytest.approx(c / n)
    assert report.difference == pytest.approx((c - b) / n)
    assert_interval(report.baseline.success_interval, score_interval(b, n, alpha), 1 - alpha)
    assert_interval(report.candidate.success_interval, score_interval(c, n, alpha), 1 - alpha)
    assert_interval(report.difference_interval, newcombe_difference(b, c, n, alpha), 1 - alpha)


def test_small_sample_limitation_is_explicitly_reproducible_not_silenced():
    # Exhaust every equally likely four-outcome pair at p=.5, n=2. The two
    # fully separated patterns create opposite directional claims: this exact
    # method does not guarantee nominal 95% coverage for every tiny design.
    directional = 0
    covered = 0
    for baseline in product("01", repeat=2):
        for candidate in product("01", repeat=2):
            report = evaluate(
                make_payload("".join(baseline), "".join(candidate), budget=2, margin=0)
            )
            directional += report.decision in {"improved", "regressed"}
            interval = report.difference_interval
            assert interval is not None
            covered += interval.lower <= 0 <= interval.upper
    assert directional / 16 == pytest.approx(0.125)
    assert covered / 16 == pytest.approx(0.875)


def test_swapping_plan_arm_roles_reverses_effect_and_interval():
    payload = make_payload("0" * 30, "1" * 30, budget=30)
    positive = evaluate(payload)
    plan = payload["plan"]
    plan["baseline_checkpoint"], plan["candidate_checkpoint"] = (
        plan["candidate_checkpoint"],
        plan["baseline_checkpoint"],
    )
    negative = evaluate(payload)
    assert positive.decision == "improved" and negative.decision == "regressed"
    assert negative.difference == pytest.approx(-positive.difference)
    assert_interval(
        negative.difference_interval,
        (-positive.difference_interval.upper, -positive.difference_interval.lower),
        0.95,
    )


@pytest.mark.parametrize("looks", [(), (30,)], ids=["fixed", "declared-look"])
def test_improvement_requires_strictly_exceeding_margin(looks):
    payload = make_payload("0" * 30, "1" * 30, budget=30, looks=looks)
    first = evaluate(payload)
    assert first.decision == "improved"
    # The independent tests validate the numerical endpoint. Reuse its public value
    # here so different rounding of a reference formula cannot spoil exact equality.
    lower = first.difference_interval.lower
    for margin, decision in [
        (nextafter(lower, 0), "improved"),
        (lower, "inconclusive"),
        (nextafter(lower, 1), "inconclusive"),
    ]:
        payload["plan"]["minimum_improvement"] = margin
        assert evaluate(payload).decision == decision


@pytest.mark.parametrize(("b", "c"), [(30, 30), (40, 39), (39, 40)])
@pytest.mark.parametrize("reverse", [False, True], ids=["positive", "negative"])
def test_partial_fixed_budget_cannot_issue_direction(b, c, reverse):
    baseline, candidate = ("1", "0") if reverse else ("0", "1")
    report = evaluate(make_payload(baseline * b, candidate * c, budget=40))
    assert report.decision in NON_DIRECTIONAL


@pytest.mark.parametrize(("b", "c"), [(0, 0), (1, 0), (0, 2)])
def test_empty_arm_has_no_inference(b, c):
    report = evaluate(make_payload("0" * b, "1" * c, budget=2))
    assert report.decision in NON_DIRECTIONAL
    assert report.difference is None and report.difference_interval is None
    for arm in (report.baseline, report.candidate):
        if not arm.attempted:
            assert arm.success_rate is None and arm.success_interval is None
