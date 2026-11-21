"""Well-formed but unsuitable evidence must be refused, not selectively filtered."""

import pytest
from eval_cases import assert_refused, evaluate, make_payload


@pytest.mark.parametrize(
    "change",
    [
        {"outcome": "unknown", "stop_reason": "task_completed"},
        {"outcome": "invalid", "exclusion_reason": "missing final frame"},
        {"human_verified": False, "label_source": "human", "reviewer_id": None},
        {"human_verified": False, "label_source": "vision", "reviewer_id": None},
        {"human_verified": False, "label_source": "triage", "reviewer_id": "annotator"},
        {"collection_mode": "simulation"},
        {"collection_mode": "deployment"},
        {"training_exposure": "used_for_training"},
        {"training_exposure": "unknown"},
        {"recorded_at": "2026-11-20T09:00:00+00:00"},  # Predates frozen plan.
        {"pair_id": "matched-pair"},  # Independent plan does not authorize pairing.
    ],
    ids=[
        "unknown",
        "invalid",
        "unverified-human",
        "unverified-vision",
        "unverified-triage",
        "simulation",
        "deployment",
        "trained-on",
        "unknown-exposure",
        "pre-plan",
        "paired-row",
    ],
)
@pytest.mark.parametrize("looks", [(), (20, 30)], ids=["fixed", "sequential"])
def test_a_single_unsuitable_row_before_decision_blocks_inference(change, looks):
    payload = make_payload("0" * 30, "1" * 30, budget=30, looks=looks)
    payload["trials"][0].update(change)
    assert_refused(evaluate(payload))


@pytest.mark.parametrize("source", ["triage", "vision"])
def test_verified_machine_origin_outcomes_count_without_reinterpreting_stop_reason(source):
    payload = make_payload("0" * 24, "1" * 24, budget=24)
    for trial in payload["trials"]:
        trial.update(
            label_source=source,
            human_verified=True,
            reviewer_id="synthetic-reviewer",
            interventions=1,
            safety_stops=1,
            stop_reason="timeout" if trial["outcome"] == "success" else "completed",
        )
    report = evaluate(payload)
    assert report.decision == "improved"
    assert report.difference == 1.0
    assert report.candidate.success_rate == 1.0
    assert report.baseline.success_rate == 0.0


@pytest.mark.parametrize(
    "design,matched", [("paired", True), ("paired", False), ("observational", False)]
)
def test_design_cannot_fall_back_to_independent_comparison(design, matched):
    payload = make_payload("0" * 24, "1" * 24, budget=24)
    payload["plan"]["design"] = design
    if matched:
        for i, row in enumerate(payload["trials"]):
            row["pair_id"] = f"pair-{i // 2}"
    assert_refused(evaluate(payload))


@pytest.mark.parametrize(
    ("field", "other", "value"),
    [
        ("session_id", 1, None),
        ("session_id", 2, None),
        ("source_uri", 2, None),
        ("source_uri", 2, "file:///tmp/run.mp4"),
    ],
    ids=["same-session-first", "same-session-second", "same-source", "percent-encoded-file-uri"],
)
def test_known_repetition_is_not_independent_even_with_unique_episode_ids(field, other, value):
    payload = make_payload("0" * 24, "1" * 24, budget=24)
    rows = payload["trials"]
    rows[other][field] = rows[0][field]
    if field == "source_uri" and value:
        rows[0][field] = "file:///tmp/run.mp4"
        rows[other][field] = "file:///tmp/r%75n.mp4"
    assert_refused(evaluate(payload))


@pytest.mark.parametrize(
    ("path", "uri"),
    [("/tmp/run#1.mp4", "file:///tmp/run%231.mp4"), ("/tmp/run?1.mp4", "file:///tmp/run%3F1.mp4")],
)
def test_bare_filename_punctuation_matches_encoded_file_uri(path, uri):
    payload = make_payload("0" * 24, "1" * 24, budget=24)
    payload["trials"][0]["source_uri"] = path
    payload["trials"][1]["source_uri"] = uri
    report = evaluate(payload)
    assert_refused(report)
    assert "Duplicate source URI" in report.rationale


@pytest.mark.parametrize("path", ["/tmp/run#1.mp4", "/tmp/run?1.mp4", "/tmp/run%231.mp4"])
def test_bare_filename_punctuation_is_literal_not_a_uri_decoration(path):
    payload = make_payload("0" * 24, "1" * 24, budget=24)
    payload["trials"][0]["source_uri"] = path
    payload["trials"][1]["source_uri"] = "file:///tmp/run.mp4"
    assert evaluate(payload).decision == "improved"


@pytest.mark.parametrize(("b", "c"), [(25, 24), (24, 25), (25, 25)])
def test_fixed_overrun_is_refused_without_choosing_a_favorable_prefix(b, c):
    assert_refused(evaluate(make_payload("0" * b, "1" * c, budget=24)))


@pytest.mark.parametrize("looks", [(), (12, 24)], ids=["fixed", "sequential"])
@pytest.mark.parametrize("bad", ["x", "?"])
def test_replacement_cannot_turn_attempt_budget_into_eligible_label_budget(bad, looks):
    # Exactly 24 resolved labels per arm, but one additional attempted candidate.
    payload = make_payload("0" * 24, bad + "1" * 24, budget=24, looks=looks)
    assert_refused(evaluate(payload))


def test_backwards_timestamp_after_first_stop_withholds_snapshot_verdict():
    payload = make_payload("0" * 18 + "1", "1" * 18, budget=30, looks=(18, 30))
    payload["trials"][-1]["recorded_at"] = payload["trials"][0]["recorded_at"]
    report = evaluate(payload)
    assert_refused(report)
    assert report.baseline.attempted == 19 and report.candidate.attempted == 18
    assert "timestamps go backwards" in report.rationale
    assert "18: improved" in report.rationale


def test_chronological_unresolved_post_stop_row_does_not_rewrite_terminal_look():
    payload = make_payload("0" * 18, "1" * 18 + "?", budget=30, looks=(18, 30))
    payload["trials"][-1].update(outcome="unknown", human_verified=False, reviewer_id=None)
    report = evaluate(payload)
    assert report.decision == "improved"
    assert report.baseline.attempted == 18 and report.candidate.attempted == 19
    assert report.candidate.unknown == 1


def test_unresolved_and_unverified_counts_preserve_all_four_raw_outcomes():
    payload = make_payload("10?x", "x?01", budget=4)
    for row in payload["trials"]:
        row.update(
            human_verified=False,
            label_source="triage",
            reviewer_id=None,
            stop_reason="operator_stop",
        )
    report = evaluate(payload)
    assert_refused(report)
    for arm in (report.baseline, report.candidate):
        assert arm.attempted == 4
        assert (arm.successes, arm.failures, arm.unknown, arm.invalid) == (1, 1, 1, 1)
