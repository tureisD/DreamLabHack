"""Rebuild one training batch from the Coach raw simulator recordings into a fresh directory."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile
import mujoco
import numpy as np
import pyarrow.parquet as pq
from dream import datasets

from batch import HOLDOUT, ROOT, SEEDS, verify

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from record_yam_demos import CONFIG, TASK, YamEnv
from resample_yam_demos import export_session


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
        env.data.joint("apple_free").qpos[:2] = scene["apple_xy_m"]
        for side, offset in (("right", 0), ("left", 7)):
            for joint in range(6):
                name = f"{side}_joint{joint + 1}"
                env.data.joint(name).qpos[0] = states[0, offset + joint]
                env.data.actuator(name).ctrl[0] = states[0, offset + joint]
        mujoco.mj_forward(env.model, env.data)
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
    required = SEEDS[batch] - SEEDS["varied"] if batch == "pooled" else SEEDS[batch]
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
        if batch == "pooled":
            verify("varied", training)
            sessions.extend(json.loads((ROOT / "varied.json").read_text(encoding="utf-8"))["sessions"])
        for seed, (folder, info) in sorted(selected.items()):
            row = audit(folder, info)
            row["frames"] = export_session(folder, training / f"apple-seed-{seed}")
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
