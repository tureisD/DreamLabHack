"""Pickup evidence is descriptive: never write a human label or score an unseen frame."""

import csv

import pytest

from teach_task_coach.pickup_evidence import COLUMNS, TRACE, assess_pickup

REST = (0.75, 0, 0, 1)
HELD = (0.85, 3, 0, 0)


def setup_trace(folder, frames, **extra):
    with (folder / TRACE).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerows((i, *sample) for i, sample in enumerate(frames))
    return {
        "collection_mode": "simulation",
        "body": "yam",
        "task": "pick up the apple",
        "fps": 20,
        "frames": len(frames),
        "status": "complete",
        "simulation": {
            "source": "model",
            "model_action_rows": len(frames),
            "warmup_rows": 0,
            **extra,
        },
    }


@pytest.mark.parametrize(
    ("motion", "expected"),
    [
        ([REST] * 32, "no_contact"),
        ([(0.75, 1, 0, 1)] * 60, "contact"),
        ([(0.85, 0, 0, 0)] * 60, "unverified_lift"),
        ([(0.85, 1, 2, 0)] * 60, "unverified_lift"),  # one fingertip on each hand
        ([(0.85, 3, 0, 1)] * 60, "unverified_lift"),  # supported by another object
        ([HELD] * 40, "brief_hold"),  # only 1.95 s between first and last samples
        ([HELD] * 20 + [REST] + [HELD] * 21, "brief_hold"),
        ([HELD] * 25 + [(0.85, 0, 3, 0)] * 25, "brief_hold"),
        ([HELD] * 41, "held"),
        ([(REST[0] + 0.08, 3, 0, 0)] * 41, "held"),
        ([(0.85, 0, 3, 0)] * 41, "held"),
    ],
)
def test_gestures(tmp_path, motion, expected):
    info = setup_trace(tmp_path, [REST, *motion])
    result = assess_pickup(tmp_path, info)
    assert result.observation == expected
    if expected == "held":
        assert result.longest_hold_s == 2 and result.evidence_s == 2.05
        assert result.first_contact_s == 0.05


def test_warmup_cannot_earn_or_extend_a_hold(tmp_path):
    info = setup_trace(
        tmp_path, [REST] + [HELD] * 43 + [REST] * 12, warmup_rows=44, model_action_rows=12
    )
    result = assess_pickup(tmp_path, info)
    assert result.observation == "no_contact" and result.analyzed_frames == 12
    assert result.first_contact_s is None


def test_model_event_uses_absolute_video_time(tmp_path):
    info = setup_trace(tmp_path, [REST] * 34 + [HELD] * 41, warmup_rows=33, model_action_rows=42)
    result = assess_pickup(tmp_path, info)
    assert result.evidence_s == 74 / 20 and result.first_contact_s == 34 / 20


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "short",
        "extra",
        "nan",
        "duplicate",
        "wrong mask",
        "wrong fps",
        "missing counter",
        "mixed counters",
    ],
)
def test_invalid_or_legacy_trace_is_not_evaluable(tmp_path, bad):
    info = setup_trace(tmp_path, [REST] + [HELD] * 41)
    path = tmp_path / TRACE
    if bad == "missing":
        path.unlink()
    elif bad == "short":
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    elif bad == "extra":
        path.write_text(path.read_text() + "42,0.85,3,0,0\n")
    elif bad == "nan":
        path.write_text(path.read_text().replace("41,0.85", "41,nan"))
    elif bad == "duplicate":
        path.write_text(path.read_text().replace("41,0.85", "40,0.85"))
    elif bad == "wrong mask":
        path.write_text(path.read_text().replace(",3,0,0", ",9,0,0"))
    elif bad == "wrong fps":
        info["fps"] = 10
    elif bad == "missing counter":
        del info["simulation"]["model_action_rows"]
    elif bad == "mixed counters":
        info["simulation"]["warmup_rows"] = 1
    assert assess_pickup(tmp_path, info).observation == "unavailable"


def test_different_task_and_physical_recording_are_out_of_scope(tmp_path):
    info = setup_trace(tmp_path, [REST])
    assert assess_pickup(tmp_path, {**info, "task": "put apple into the bowl"}) is None
    assert assess_pickup(tmp_path, {**info, "collection_mode": "station"}) is None


def test_technical_abort_and_camera_check_are_not_grasp_failures(tmp_path):
    info = setup_trace(tmp_path, [REST] * 33, warmup_rows=33, model_action_rows=0)
    for source in ("model", "observation dry run"):
        info["simulation"]["source"] = source
        result = assess_pickup(tmp_path, {**info, "status": "partial"})
        assert result.observation == "no_actions" and result.peak_lift_m is None
