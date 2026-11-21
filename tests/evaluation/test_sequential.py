"""Declared-look error allocation, chronological replay, and retained attempt clock."""

import pytest
from eval_cases import NON_DIRECTIONAL, assert_interval, evaluate, make_payload
from interval_reference import exact_interval


def assert_at_look(report, b, c, n, plan):
    alpha = plan["alpha"]
    arm_error = alpha / (2 * len(plan["planned_looks"]))
    b_lo, b_hi = exact_interval(b, n, arm_error)
    c_lo, c_hi = exact_interval(c, n, arm_error)
    assert report.baseline.success_rate == pytest.approx(b / n)
    assert report.candidate.success_rate == pytest.approx(c / n)
    assert report.difference == pytest.approx((c - b) / n)
    assert_interval(report.baseline.success_interval, (b_lo, b_hi), 1 - arm_error)
    assert_interval(report.candidate.success_interval, (c_lo, c_hi), 1 - arm_error)
    assert_interval(report.difference_interval, (c_lo - b_hi, c_hi - b_lo), 1 - alpha)


@pytest.mark.parametrize("look", [4, 10, 20])
def test_each_declared_look_uses_all_planned_looks_in_tail_allocation(look):
    b = ("1000" + "010010" + "1010010010")[:look]
    c = ("1001" + "111110" + "1110011110")[:look]
    payload = make_payload(b, c, budget=20, looks=(4, 10, 20), alpha=0.12)
    report = evaluate(payload)
    assert report.decision == "inconclusive"
    assert_at_look(report, b.count("1"), c.count("1"), look, payload["plan"])


@pytest.mark.parametrize(("b", "c"), [(14, 14), (29, 29), (30, 29), (29, 30)])
@pytest.mark.parametrize("reverse", [False, True])
def test_no_direction_before_or_between_balanced_looks(b, c, reverse):
    # The first look ties. The additional outcomes alone look compelling, but
    # neither an off-schedule count nor reaching the look in one arm is enough.
    b_code, c_code = ("1", "0") if reverse else ("0", "1")
    head = "10" if min(b, c) > 14 else ""
    looks = (2, 30, 60) if head else (15, 30, 60)
    payload = make_payload(
        head + b_code * (b - len(head)), head + c_code * (c - len(head)), budget=60, looks=looks
    )
    assert evaluate(payload).decision in NON_DIRECTIONAL


@pytest.mark.parametrize(
    "tail_b,tail_c", [("1", "0"), ("0", "1")], ids=["tied-final", "strong-final"]
)
def test_cannot_skip_or_reconstruct_a_missed_look(tail_b, tail_c):
    payload = make_payload(
        "0" * 16 + tail_b * 16, "1" * 16 + tail_c * 16, budget=32, looks=(16, 32)
    )
    rows = payload["trials"]
    times = [row["recorded_at"] for row in rows]
    # At the arrival of candidate 16, baseline 17 has already been observed.
    # Selecting just 16 rows per arm would retroactively claim improvement.
    # A strong final result must not hide the missing planned assessment either.
    rows[31], rows[32] = rows[32], rows[31]
    for row, timestamp in zip(rows, times, strict=True):
        row["recorded_at"] = timestamp
    for length in (33, 64):
        assert evaluate({**payload, "trials": rows[:length]}).decision in NON_DIRECTIONAL


@pytest.mark.parametrize("reverse", [False, True], ids=["improved", "regressed"])
def test_first_terminal_look_survives_all_later_rows(reverse):
    # Tie at 2, stop at 18. Later observations are strong enough to reverse the
    # sign of the raw effect at 60. No prior call/state is supplied to evaluate().
    b, c = "10" + "0" * 16 + "1" * 42, "10" + "1" * 16 + "0" * 42
    if reverse:
        b, c = c, b
    for length in (18, 19, 60):
        payload = make_payload(b[:length], c[:length], budget=60, looks=(2, 18, 60))
        report = evaluate(payload)
        assert report.decision == ("regressed" if reverse else "improved")
        assert_at_look(report, b[:18].count("1"), c[:18].count("1"), 18, payload["plan"])


@pytest.mark.parametrize("trailing", ["?", "x"])
def test_post_stop_unresolved_attempts_are_retained_but_not_inferential(trailing):
    payload = make_payload("0" * 18 + "1", "1" * 18 + trailing, budget=30, looks=(18, 30))
    payload["trials"][-1].update(human_verified=False, reviewer_id=None, label_source="vision")
    report = evaluate(payload)
    assert report.decision == "improved"
    assert_at_look(report, 0, 18, 18, payload["plan"])


def test_even_over_budget_tail_cannot_rewrite_a_prior_stop():
    payload = make_payload("0" * 18 + "111", "1" * 18 + "000", budget=20, looks=(18, 20))
    report = evaluate(payload)
    assert report.decision == "improved"
    assert_at_look(report, 0, 18, 18, payload["plan"])


def test_equality_at_regression_boundary_is_not_a_regression():
    # K=1, alpha=1/4 => each two-sided CP tail is 1/16. With four
    # successes vs four failures both inner endpoints are exactly (1/16)^(1/4) = 1/2.
    payload = make_payload("1111", "0000", budget=4, looks=(4,), alpha=0.25)
    report = evaluate(payload)
    assert report.decision == "inconclusive"
    assert_at_look(report, 4, 0, 4, payload["plan"])
    assert report.difference_interval.upper == 0
