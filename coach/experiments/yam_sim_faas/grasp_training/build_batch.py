"""Rebuild one training batch from the Coach raw simulator recordings into a fresh directory."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

import mujoco
import numpy as np
import pyarrow.parquet as pq
from batch import HOLDOUT, SEEDS
from dream import datasets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from record_yam_demos import CONFIG, TASK, YamEnv
from resample_yam_demos import export_session


def initialize_replay(env, scene, initial_state):
    apple = env.data.joint("apple_free").qpos
    expected_xy = apple[:2] + np.random.default_rng(scene["seed"]).uniform(-0.025, 0.025, 2)
    if not np.allclose(expected_xy, scene["apple_xy_m"], atol=1e-9, rtol=0):
        raise ValueError(f"Apple placement differs from seed {scene['seed']}")
    apple[:2] = expected_xy
    for side, offset in (("right", 0), ("left", 7)):
        for joint in range(6):
            name = f"{side}_joint{joint + 1}"
            angle = initial_state[offset + joint]
            env.data.joint(name).qpos[0] = angle
            env.data.actuator(name).ctrl[0] = angle
    mujoco.mj_forward(env.model, env.data)


def check_training_actions(folder, scene):
    """Replay the actual 10 Hz export at its recorded cadence before packaging it."""
    data = pq.read_table(folder / "data/chunk-000/episode_000000.parquet")
    env = YamEnv()
    heights = []
    try:
        initialize_replay(env, scene, data["observation.state"][0].as_py())
        for row in data["action"].to_pylist():
            for _ in range(2):
                env.step(row[7:], row[:7])
                heights.append(float(env.data.body("apple").xpos[2]))
    finally:
        env.close()
    # The source script settles the apple for 30 ticks before starting the approach.
    rise = np.asarray(heights) - heights[29]
    windows = np.lib.stride_tricks.sliding_window_view(rise, 41)  # 2 s between first and last sample
    held = float(np.max(np.min(windows, axis=1)))
    if held < 0.08 or np.max(rise) - rise[-1] < 0.06:
        raise ValueError(f"{folder}: exported actions failed the lift/hold/release replay")
    return held


def audit(folder, info):
    scene = info["simulation"]
    if info["status"] != "complete" or not scene["script_result"]["passed"]:
        raise ValueError(f"Incomplete or unsuccessful demonstration: {folder.name}")
    table = pq.read_table(folder / "data/chunk-000/episode_000000.parquet")
    states = np.asarray(table["observation.state"].to_pylist())
    actions = np.asarray(table["action"].to_pylist())
    closing = int(np.flatnonzero(actions[:, 13] < 0.99)[0])
    env = YamEnv()
    contact_rows = 0
    max_error = 0.0
    try:
        initialize_replay(env, scene, states[0])
        for index, row in enumerate(actions):
            measured = env.state()
            replay = np.r_[measured["right"], measured["left"]]
            max_error = max(max_error, float(np.max(np.abs(states[index] - replay))))
            if index == closing:
                gap = float(np.linalg.norm(env.data.site("left_tcp").xpos - env.data.body("apple").xpos))
            touching = set()
            for contact in env.data.contact:
                names = {env.model.body(env.model.geom_bodyid[g]).name for g in (contact.geom1, contact.geom2)}
                if "apple" in names:
                    touching.update(names)
            contact_rows += {"left_tip_left", "left_tip_right"} <= touching
            env.step(row[7:], row[:7])
    finally:
        env.close()
    if gap >= 0.015 or contact_rows < 40 or max_error >= 0.002:
        raise ValueError(f"Review {folder.name}: closing gap {gap}, contact rows {contact_rows}, replay error {max_error}")
    return {"seed": scene["seed"], "source": folder.name, "apple_xy_m": scene["apple_xy_m"],
            "approach": scene.get("approach"), "first_close_s": closing / 20, "closing_gap_mm": gap * 1000,
            "both_fingers_contact_rows_20hz": contact_rows, "held_lift_m": scene["script_result"]["lift_m"],
            "replay_max_state_error": max_error}


def build(batch, raw_root, output):
    selected = {}
    required = SEEDS[batch]
    for path in raw_root.glob("*/rollout.json"):
        info = json.loads(path.read_text(encoding="utf-8"))
        scene = info.get("simulation") or {}
        seed = scene.get("seed")
        if (seed not in required or scene.get("source") != "scripted"
                or scene.get("start_pose") != "wrist-visible" or info["task"] != TASK
                or bool(scene.get("approach")) != (seed >= 101)):
            continue
        if seed in selected:
            raise ValueError(f"Multiple eligible recordings for seed {seed}. Select one explicitly in the input directory.")
        selected[seed] = path.parent, info
    if set(selected) != required:
        raise ValueError(f"Missing training seeds {sorted(required - set(selected))}")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{batch}.zip"
    manifest = output / f"{batch}.json"
    if archive.exists() or manifest.exists():
        raise FileExistsError(f"Choose a fresh output for {batch}")
    with TemporaryDirectory(dir=output.parent) as tmp:
        scratch = Path(tmp)
        training = (scratch / "training").resolve()
        training.mkdir()
        sessions = []
        for seed, (folder, info) in sorted(selected.items()):
            row = audit(folder, info)
            episode = training / f"apple-seed-{seed}"
            row["frames"] = export_session(folder, episode)
            row["export_held_lift_m"] = check_training_actions(episode, info["simulation"])
            sessions.append(row)
            print(f"Verified seed {seed}, closure at {row['first_close_s']:.2f}s", flush=True)
        report = datasets.validate_dataset(str(training), CONFIG)
        if not report.ok or report.episodes != len(sessions):
            raise ValueError(str(report))
        if batch != "control" and len({r["first_close_s"] for r in sessions}) < 8:
            raise ValueError("Insufficient distinct grasp times for the varied training experiment")
        staged = scratch / archive.name
        with ZipFile(staged, "w", compression=ZIP_STORED) as z:
            for path in sorted(training.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(training).as_posix())
        data = {"sha256": hashlib.sha256(staged.read_bytes()).hexdigest(), "embodiment": CONFIG,
                "task": TASK, "start_pose": "wrist-visible", "sessions": sessions, "frames": report.frames,
                "fps": report.fps, "held_out_seeds": sorted(HOLDOUT)}
        staged_manifest = scratch / manifest.name
        staged_manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        staged.rename(archive)
        staged_manifest.rename(manifest)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("batch", choices=SEEDS)
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    build(args.batch, args.raw, args.output)
