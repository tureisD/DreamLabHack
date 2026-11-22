"""Replay held-out model actions in MuJoCo and score the apple lift without video inference."""

import argparse
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from batch import CONFIRMATION, HOLDOUT
from build_batch import initialize_replay
from record_yam_demos import TASK, YamEnv


def score(folder: Path) -> dict:
    info = json.loads((folder / "rollout.json").read_text(encoding="utf-8"))
    scene = info["simulation"]
    if (
        info["status"] != "complete"
        or scene["source"] != "model"
        or scene["seed"] not in HOLDOUT | CONFIRMATION
        or scene["start_pose"] != "wrist-visible"
        or info["task"] != TASK
    ):
        raise ValueError(f"{folder}: not a complete held-out model rollout")
    table = pq.read_table(folder / "data/chunk-000/episode_000000.parquet")
    states = np.asarray(table["observation.state"].to_pylist(), dtype=float)
    actions = np.asarray(table["action"].to_pylist(), dtype=float)
    if len(actions) != info["frames"] or len(actions) != len(states) or len(actions) < 70:
        raise ValueError(f"{folder}: too few or mismatched action rows")
    if scene.get("model_action_rows", 0) < 40:
        raise ValueError(f"{folder}: no complete model action chunk")

    env = YamEnv()
    heights = []
    max_state_error = 0.0
    try:
        initialize_replay(env, scene, states[0])
        for index, row in enumerate(actions):
            measured = env.state()
            actual = np.r_[measured["right"], measured["left"]]
            max_state_error = max(max_state_error, float(np.max(np.abs(states[index] - actual))))
            env.step(row[7:], row[:7])
            heights.append(float(env.data.body("apple").xpos[2]))
    finally:
        env.close()
    has_recorded_height = "observation.apple_height_m" in table.column_names
    # Contact-rich replay can drift a few millimeters after a grasp. A score-only
    # rollout records the actual simulated apple height, so its outcome does not
    # depend on that replay drift; retain a 5 mm joint-state agreement check.
    state_tolerance = 0.005 if has_recorded_height else 0.002
    if max_state_error >= state_tolerance:
        raise ValueError(f"{folder}: replay diverged from recorded state by {max_state_error:.4f}")

    if has_recorded_height:
        heights = np.asarray(table["observation.apple_height_m"].to_pylist(), dtype=float)
    rise = np.asarray(heights) - heights[29]
    # The recorder warms the scene for 33 simulation steps before applying the
    # first model action. Report grasp timing so a late close is visible even
    # when a trial briefly lifts the apple.
    closing_rows = np.flatnonzero(actions[33:, 13] < 0.5)
    first_close_row = int(closing_rows[0] + 33) if len(closing_rows) else None
    held_by_start = np.min(np.lib.stride_tricks.sliding_window_view(rise, 41), axis=1)
    held_start = int(np.argmax(held_by_start))
    held = float(held_by_start[held_start])
    return {
        "folder": str(folder.resolve()),
        "seed": scene["seed"],
        "checkpoint": info["checkpoint"],
        "model_action_rows": scene["model_action_rows"],
        "duration_s": info["duration_s"],
        "replay_max_state_error": max_state_error,
        "height_source": "recorded" if has_recorded_height else "replayed",
        "peak_lift_m": float(np.max(rise)),
        "peak_time_s": float(np.argmax(rise) / 20),
        "first_close_time_s": first_close_row / 20 if first_close_row is not None else None,
        "first_close_after_warmup_s": (first_close_row - 33) / 20 if first_close_row is not None else None,
        "held_lift_m": held,
        "held_window_start_s": held_start / 20,
        "success": held >= 0.08,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", type=Path, help="Completed held-out model rollout folders")
    args = parser.parse_args()
    print(json.dumps([score(folder) for folder in args.folders], indent=2))


if __name__ == "__main__":
    main()
