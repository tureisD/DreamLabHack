"""Descriptive, video-aligned evidence for one YAM simulator task. Never an operator label."""

import csv
import math
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

TRACE = "apple-evidence-v1.csv"
COLUMNS = ("frame", "apple_z_m", "left_fingers", "right_fingers", "other_contact")
FPS = 20
LIFT_M = 0.08
HOLD_S = 2
MAX_FRAMES = 72_000


class PickupEvidence(BaseModel):
    rule: Literal["yam-apple-v1"] = "yam-apple-v1"
    source: Literal["model", "scripted", "observation dry run"]
    observation: Literal[
        "no_actions",
        "unavailable",
        "no_contact",
        "contact",
        "unverified_lift",
        "brief_hold",
        "held",
    ]
    detail: str
    analyzed_frames: int = 0
    first_contact_s: float | None = None
    peak_lift_m: float | None = None
    longest_hold_s: float | None = None
    evidence_s: float | None = None


def _rows(path: Path, expected: int) -> Iterator[tuple[int, float, int, int, bool]]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 8_000_000:
        raise ValueError("Unsupported trace file")
    with path.open(encoding="ascii", newline="") as stream:
        rows = csv.reader(stream)
        if tuple(next(rows, ())) != COLUMNS:
            raise ValueError("Unknown trace columns")
        count = 0
        for index, row in enumerate(rows):
            frame, z, left, right, other = row
            z = float(z)
            if (
                int(frame) != index
                or index >= expected
                or not math.isfinite(z)
                or left not in ("0", "1", "2", "3")
                or right not in ("0", "1", "2", "3")
                or other not in ("0", "1")
            ):
                raise ValueError("Invalid evidence frame")
            yield index, z, int(left), int(right), other == "1"
            count += 1
        if count != expected:
            raise ValueError("Incomplete evidence trace")


def assess_pickup(folder: Path, info: dict) -> PickupEvidence | None:
    sim = info.get("simulation")
    if (
        info.get("collection_mode") != "simulation"
        or info.get("body") != "yam"
        or not isinstance(sim, dict)
        or info.get("task", "").strip().casefold() != "pick up the apple"
    ):
        return None
    source = sim.get("source")
    if source not in ("model", "scripted", "observation dry run"):
        return None

    def empty(observation, detail):
        return PickupEvidence(source=source, observation=observation, detail=detail)

    n = info.get("frames")
    moves = sim.get("model_action_rows")
    if source == "observation dry run":
        return empty("no_actions", "Camera warm-up only. No model controlled this recording.")
    if source == "model" and type(moves) is int and moves == 0:
        return empty(
            "no_actions", "No model action was executed. Check the run status before retrying."
        )
    if type(n) is not int or not 0 < n <= MAX_FRAMES or info.get("fps") != FPS:
        return empty("unavailable", "Missing or unsupported recording length or frame rate.")
    start = 0
    if source == "model":
        start = sim.get("warmup_rows")
        if (
            type(moves) is not int
            or type(start) is not int
            or moves < 1
            or start < 0
            or start + moves != n
        ):
            return empty(
                "unavailable", "Cannot separate camera warm-up from model motion in this recording."
            )
    z0 = None
    contact_frame = high_frame = held_frame = best_end = None
    peak = 0.0
    longest = 0
    streaks = [0, 0]
    try:
        for i, z, left, right, other in _rows(folder / TRACE, n):
            if i < start:
                continue
            if z0 is None:
                z0 = z
            height = z - z0
            if height > peak:
                peak, high_frame = height, i
            if (left or right) and contact_frame is None:
                contact_frame = i
            for hand, mask in enumerate((left, right)):
                qualifies = mask == 3 and not other and height > LIFT_M
                streaks[hand] = streaks[hand] + 1 if qualifies else 0
                # Distinct timestamps, not frame count: 41 samples span 2 s at 20 Hz.
                span = streaks[hand] - 1
                if span > longest or (qualifies and best_end is None):
                    longest, best_end = max(span, 0), i
                if held_frame is None and span >= FPS * HOLD_S:
                    held_frame = i
    except (OSError, ValueError, UnicodeError, csv.Error):
        return empty(
            "unavailable",
            "No complete, valid finger-contact and height trace. Review the video manually.",
        )
    if held_frame is not None:
        outcome, event = "held", held_frame
        detail = "Both fingertips of one hand held the apple over 8 cm up for at least 2 s without other contact."
    elif best_end is not None:
        outcome, event = "brief_hold", best_end
        detail = "The apple was elevated between two fingertips, but a continuous 2 s hold was not observed."
    elif peak > LIFT_M:
        outcome, event = "unverified_lift", high_frame
        detail = "The apple rose over 8 cm without a verified two-finger hold. Inspect this frame."
    elif contact_frame is not None:
        outcome, event = "contact", contact_frame
        detail = "A fingertip touched the apple. A lift over 8 cm was not observed in the recorded window."
    else:
        outcome, event = "no_contact", None
        detail = (
            "No fingertip contact was observed in the recorded frames. A longer attempt may differ."
        )
    return PickupEvidence(
        source=source,
        observation=outcome,
        detail=detail,
        analyzed_frames=n - start,
        first_contact_s=None if contact_frame is None else contact_frame / FPS,
        peak_lift_m=peak,
        longest_hold_s=longest / FPS,
        evidence_s=None if event is None else event / FPS,
    )
