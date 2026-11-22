"""Explain recorded YAM apple-pickup outcomes from signals in a verified replay."""

import math

import numpy as np

FPS = 20
WARMUP_ROWS = 33
REQUEST_ROWS = 48
HOLD_ROWS = 2 * FPS + 1
TARGET_RISE_M = 0.08
OLD_HORIZON = 9
GRASP_ALIGN_M = 0.06
SIDES = ("right", "left")


class GraspReplay:
    """Sample gripper geometry before each action, as the model saw it."""

    def __init__(self, env):
        self.apple = env.model.body("apple").id
        self.sites = [env.model.site(f"{side}_tcp").id for side in SIDES]
        self.fingers = [
            frozenset(env.model.body(f"{side}_tip_{tip}").id for tip in ("left", "right"))
            for side in SIDES
        ]
        self.gaps: list[np.ndarray] = []
        self.contacts: list[list[int]] = []

    def observe(self, env) -> None:
        center = env.data.xpos[self.apple]
        self.gaps.append(np.linalg.norm(env.data.site_xpos[self.sites] - center, axis=1))
        touching = set()
        for contact in env.data.contact:
            first, second = env.model.geom_bodyid[[contact.geom1, contact.geom2]]
            if first == self.apple:
                touching.add(second)
            elif second == self.apple:
                touching.add(first)
        self.contacts.append([len(fingers & touching) for fingers in self.fingers])


def _result(code: str, title: str, summary: str, evidence: list[str], next_step: str | None) -> dict:
    return {
        "code": code, "title": title, "summary": summary,
        "evidence": evidence, "next_step": next_step,
    }


def _contact_evidence(contacts: np.ndarray) -> str:
    paired = contacts == 2
    if not np.any(paired):
        return (
            "Replay showed finger contact, with no simultaneous two-finger contact at the sampled steps."
            if np.any(contacts) else "Replay showed no finger contact at the sampled steps."
        )
    counts = []
    for arm in paired.T:
        transitions = np.flatnonzero(np.diff(np.r_[False, arm, False]))
        counts.extend(transitions[1::2] - transitions[::2])
    span = (max(counts) - 1) / FPS
    return f"Longest continuous two-finger contact seen in replay was {span:.2f} s."


def _lift_diagnosis(
    rise: np.ndarray, held_windows: np.ndarray, contacts: np.ndarray, evidence: list[str],
) -> dict | None:
    passing = np.flatnonzero(held_windows >= TARGET_RISE_M)
    if passing.size:
        first_request = max(1, math.ceil((int(passing[0]) + HOLD_ROWS - WARMUP_ROWS) / REQUEST_ROWS))
        if first_request > OLD_HORIZON:
            prefix = WARMUP_ROWS + OLD_HORIZON * REQUEST_ROWS
            old_held = float(np.max(held_windows[:prefix - HOLD_ROWS + 1]))
            evidence.append(f"After {OLD_HORIZON} requests, best two-second lift was {100 * old_held:.2f} cm.")
            evidence.append(f"The two-second hold first qualified during request {first_request}.")
            return _result(
                "extended_rollout_pass", "Passed with the longer rollout",
                "The same trajectory would have missed at the original cutoff. The extra actions "
                "gave the gripper time to complete the hold.",
                evidence, None,
            )
        return _result(
            "pass", "Lift and hold passed",
            "The apple stayed at least 8 cm above its starting height for two continuous seconds.",
            evidence, None,
        )

    above = rise >= TARGET_RISE_M
    if np.any(above):
        transitions = np.flatnonzero(np.diff(np.r_[False, above, False]))
        longest = (int(np.max(transitions[1::2] - transitions[::2])) - 1) / FPS
        evidence.append(f"Longest continuous hold at 8 cm was {longest:.2f} s. The goal is 2.00 s.")
        evidence.append(_contact_evidence(contacts))
        if above[-1]:
            return _result(
                "hold_cut_short", "Trial ended during the hold",
                "The apple was above the target height when the rollout ended. The recording "
                "ended before it showed a two-second hold.",
                evidence, "Give both checkpoints the same longer trial budget and check the hold again.",
            )
        return _result(
            "short_hold", "Reached the height but lost the hold",
            "The apple reached 8 cm and dropped below the target before the two-second hold was complete.",
            evidence, "Record a correction that keeps the grip steady at the top of the lift.",
        )

    if float(np.max(rise)) >= 0.01:
        evidence.append(_contact_evidence(contacts))
        if rise[-1] - rise[-11] >= 0.01 and np.max(rise) - rise[-1] < 0.005:
            return _result(
                "lift_cut_short", "Trial ended while the apple was rising",
                "The apple was still rising at the end of the rollout and had yet to reach 8 cm.",
                evidence, "Check whether a longer, equal budget lets both checkpoints finish the lift.",
            )
        return _result(
            "lift_too_low", "The lift fell short",
            "The apple moved upward, but its peak stayed below the required 8 cm.",
            evidence, "Review the lift path and record a correction that reaches and holds the target height.",
        )
    return None


def diagnose_rollout(actions: np.ndarray, rise: np.ndarray, replay: GraspReplay, height_source: str) -> dict:
    """Separate observed task failures from likely causes suggested by gripper replay."""
    held_windows = np.min(np.lib.stride_tricks.sliding_window_view(rise, HOLD_ROWS), axis=1)
    peak_lift = max(0.0, float(np.max(rise)))
    held_lift = max(0.0, float(np.max(held_windows)))
    evidence = [
        f"Peak lift {100 * peak_lift:.2f} cm. Best two-second lift {100 * held_lift:.2f} cm.",
        "Lift measured from the recorded trace." if height_source == "recorded" else "Lift measured in replay.",
    ]
    contacts = np.asarray(replay.contacts[WARMUP_ROWS:])
    lift = _lift_diagnosis(rise, held_windows, contacts, evidence)
    if lift:
        return lift

    # A threshold crossing describes the commanded action, not measured finger travel.
    closed = actions[WARMUP_ROWS:, [6, 13]] < 0.5
    gaps = np.asarray(replay.gaps[WARMUP_ROWS:])
    closures = np.argwhere(closed & ~np.vstack((np.zeros(2, dtype=bool), closed[:-1])))
    if not closures.size:
        evidence.append("Neither gripper was commanded below half open during the model actions.")
        return _result(
            "no_close_command", "The model did not command a firm close",
            "The apple barely lifted and the command trace shows no close past halfway.",
            evidence, "Record a correction that closes the gripper once it is centered on the apple.",
        )

    # Use the closest commanded close from either arm instead of assuming that the left arm is active.
    row, side = min(closures, key=lambda item: gaps[tuple(item)])
    nearest = float(gaps[row, side])
    evidence.append(
        f"Closest close command: {SIDES[side]} gripper at {row / FPS:.2f} s, "
        f"{nearest * 100:.1f} cm from the apple center in replay."
    )
    first_row, first_side = closures[0]
    first_gap = float(gaps[first_row, first_side])
    if first_row < row and first_gap >= GRASP_ALIGN_M:
        evidence.append(
            f"First close command: {SIDES[first_side]} gripper at {first_row / FPS:.2f} s, "
            f"{first_gap * 100:.1f} cm from the apple center in replay."
        )
    paired = bool(np.any(contacts == 2))
    evidence.append(_contact_evidence(contacts))
    if paired:
        return _result(
            "contact_without_lift", "Finger contact did not turn into a lift",
            "The fingers reached the apple, but it barely moved upward. The trace cannot confirm a secure grip.",
            evidence, "Review the grip and upward motion, then record a correction with a steady lift.",
        )
    if nearest >= GRASP_ALIGN_M:
        return _result(
            "close_outside_grasp", "The gripper closed away from the apple",
            "Even the closest close command was away from the apple. The replay suggests a missed grasp.",
            evidence, "Record a correction that approaches with the gripper open and closes only when centered.",
        )
    return _result(
        "no_secure_grasp", "The gripper did not secure the apple",
        "The model commanded a close near the apple. Replay showed no simultaneous two-finger contact "
        "and the apple barely lifted.",
        evidence, "Review the approach angle and record a centered grip before the lift.",
    )
