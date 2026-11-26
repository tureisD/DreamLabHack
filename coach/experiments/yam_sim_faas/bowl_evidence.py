"""Record simulator ground truth for apple-in-bowl evaluation."""

import numpy as np

from teach_task_coach.yam_goals import (
    BOWL_HEIGHT_M,
    BOWL_LIFT_M,
    BOWL_RADIUS_M,
    BOWL_SETTLE_SECONDS,
    BOWL_SPEED_M_S,
)

PLACEMENT_COLUMN = "observation.apple_bowl_state"


def observe_placement(env) -> tuple[float, float, float, int, int]:
    apple = env.data.body("apple")
    bowl = env.data.body("bowl")
    relative = apple.xpos - bowl.xpos
    speed = np.linalg.norm(env.data.joint("apple_free").qvel[:3])
    has_support = has_other_contact = False
    for contact in env.data.contact:
        if contact.dist > 0 or contact.efc_address < 0 or min(contact.geom1, contact.geom2) < 0:
            continue
        first, second = env.model.geom_bodyid[[contact.geom1, contact.geom2]]
        if apple.id not in (first, second):
            continue
        other = second if first == apple.id else first
        has_support |= other == bowl.id
        has_other_contact |= other != bowl.id
    return float(np.linalg.norm(relative[:2])), float(relative[2]), float(speed), int(has_support), int(has_other_contact)


def evaluate_placement(samples, peak_lift_m: float, fps: int) -> dict:
    samples = np.asarray(samples, dtype=float)
    if (samples.ndim != 2 or samples.shape[1] != 5 or len(samples) < fps + 1
        or not np.isfinite(samples).all() or (samples[:, [0, 2]] < 0).any()
        or not np.isin(samples[:, 3:], (0, 1)).all()):
        raise ValueError("The rollout has invalid recorded bowl evidence.")
    distance, height, speed, supported, other_contact = samples.T
    inside = (distance <= BOWL_RADIUS_M) & (height > BOWL_HEIGHT_M[0]) & (height < BOWL_HEIGHT_M[1])
    settled = inside & (speed <= BOWL_SPEED_M_S) & (supported == 1) & (other_contact == 0)
    breaks = np.flatnonzero(~settled)
    sample_count = len(samples) - int(breaks[-1]) - 1 if len(breaks) else len(samples)
    duration = max(0, sample_count - 1) / fps
    passed = peak_lift_m >= BOWL_LIFT_M and duration >= BOWL_SETTLE_SECONDS
    if passed:
        code, title, next_step = "bowl_placed", "Apple released and settled in the bowl", None
    elif peak_lift_m < BOWL_LIFT_M:
        code, title, next_step = "bowl_no_lift", "Apple was not lifted high enough", "Review the approach and grasp before teaching placement."
    elif not inside[-1]:
        code, title, next_step = "bowl_outside", "Apple finished outside the bowl", "Review the transfer and release position."
    elif other_contact[-1] or not supported[-1]:
        code, title, next_step = "bowl_unreleased", "Bowl placement was not supported after release", "Check that the gripper releases the apple and clears the bowl."
    else:
        code, title, next_step = "bowl_unsettled", "Apple did not settle for a full second", "Inspect the release and allow the apple time to settle."
    return {
        "success": passed,
        "bowl_placement": {
            "settled_s": duration, "final_distance_m": float(distance[-1]),
            "final_height_m": float(height[-1]),
        },
        "diagnosis": {
            "code": code, "title": title,
            "summary": f"The recorded apple was settled in the bowl for the final {duration:.2f} seconds.",
            "evidence": [f"Peak lift: {100 * peak_lift_m:.1f} cm.",
                         f"Final distance from bowl center: {100 * distance[-1]:.1f} cm.",
                         f"Bowl contact at the final sample: {'yes' if supported[-1] else 'no'}."],
            "next_step": next_step,
        },
    }
