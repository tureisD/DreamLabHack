"""Turn fresh YAM model failures into audited, failure-conditioned simulator demos.

No robot, Dream API call, or paid FaaS job is started by this command. The input
must contain completed model-controlled runs on *training-eligible* scene seeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from dream import datasets

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "grasp_training"))
from build_batch import audit, check_training_actions
from record_yam_demos import CONFIG, TASK, mock_pickups, recording
from resample_yam_demos import export_session
from score_rollouts import score


def source_sha256(folder: Path) -> str:
    digest = hashlib.sha256()
    for name in ("rollout.json", "data/chunk-000/episode_000000.parquet"):
        path = folder / name
        digest.update(name.encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def demo_sha256(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def failure_kind(result: dict) -> str:
    close = result["first_close_after_warmup_s"]
    if close is None:
        return "never_closed"
    if close < 3:
        return "early_close"
    if close > 15:
        return "late_close"
    if result["peak_lift_m"] >= 0.08:
        return "dropped_after_lift"
    return "failed_lift"


def eligible_failures(root: Path) -> list[dict]:
    found = []
    for sidecar in sorted(root.glob("*/rollout.json")):
        try:
            result = score(sidecar.parent, training_candidate=True)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
        if result["success"]:
            continue
        info = json.loads(sidecar.read_text(encoding="utf-8"))
        found.append({
            **result,
            "apple_xy_m": info["simulation"]["apple_xy_m"],
            "source_sha256": source_sha256(sidecar.parent),
            "failure_kind": failure_kind(result),
        })
    if not found:
        raise ValueError("No eligible complete failed model rollouts. Use fresh non-test seeds.")
    if len({row["seed"] for row in found}) != len(found):
        raise ValueError("Multiple eligible failures share a seed. Resolve duplicates explicitly.")
    if len({row["checkpoint"] for row in found}) != 1:
        raise ValueError("Collect one checkpoint's failures per batch.")
    return found


def select_diverse(failures: list[dict], limit: int) -> list[dict]:
    """Choose failure modes first, then spread selected apple positions."""
    if limit < 1:
        raise ValueError("max_demos must be positive")
    selected = []
    remaining = sorted(failures, key=lambda row: (row["held_lift_m"], row["seed"]))
    while remaining and len(selected) < limit:
        def priority(row: dict) -> tuple:
            unseen = row["failure_kind"] not in {item["failure_kind"] for item in selected}
            distance = min((float(np.linalg.norm(
                np.asarray(row["apple_xy_m"]) - np.asarray(item["apple_xy_m"])
            )) for item in selected), default=0)
            return (unseen, distance, -row["held_lift_m"], -row["seed"])

        chosen = max(remaining, key=priority)
        selected.append(chosen)
        remaining.remove(chosen)
    return selected


def corrective_recipe(row: dict) -> dict:
    """Vary timing around the observed failure, deterministically per scene."""
    rng = np.random.default_rng([row["seed"], 811])
    kind = row["failure_kind"]
    if kind == "early_close":
        return {"approach_steps": int(rng.integers(65, 91)),
                "descent_steps": int(rng.integers(55, 81)),
                "approach_height": float(rng.uniform(0.105, 0.14))}
    if kind == "late_close" or kind == "never_closed":
        return {"approach_steps": int(rng.integers(35, 56)),
                "descent_steps": int(rng.integers(38, 61)),
                "approach_height": float(rng.uniform(0.09, 0.12))}
    return {"approach_steps": int(rng.integers(45, 81)),
            "descent_steps": int(rng.integers(45, 81)),
            "approach_height": float(rng.uniform(0.095, 0.15))}


def collect(root: Path, output: Path, *, max_demos: int) -> dict:
    root, output = root.resolve(), output.resolve()
    if output == root or output.is_relative_to(root):
        raise ValueError("Choose an output outside the model rollout directory.")
    failures = eligible_failures(root)
    selected = select_diverse(failures, max_demos)
    output.mkdir(parents=True, exist_ok=True)
    names = [f"yam-failure-seed-{row['seed']}" for row in selected]
    if any((output / name).exists() for name in names):
        raise FileExistsError("One selected seed already has an output demo. Choose a fresh output.")
    source_list = [(row["seed"], row["source_sha256"]) for row in selected]
    collection_id = hashlib.sha256(json.dumps(source_list).encode()).hexdigest()[:12]
    manifest_name = f"failure-conditioned-{collection_id}.json"
    if (output / manifest_name).exists():
        raise FileExistsError("This collection manifest already exists.")

    rows = []
    with TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp)
        for row, name in zip(selected, names, strict=True):
            recipe = corrective_recipe(row)
            with recording(stage, TASK, "scripted-yam", row["seed"], "scripted",
                           start_pose="wrist-visible") as (env, details):
                details["approach"] = recipe
                result = mock_pickups.run_trial("apple", env=env, snapshot_dir=env.folder, **recipe)
                details["script_result"] = result
                (env.folder / "embodiment.json").write_text(json.dumps(CONFIG), encoding="utf-8")
            if not result["passed"]:
                raise ValueError(f"Corrective trajectory failed for seed {row['seed']}")
            raw = env.folder
            info = json.loads((raw / "rollout.json").read_text(encoding="utf-8"))
            raw_audit = audit(raw, info)
            demo = stage / name
            frames = export_session(raw, demo)
            replay_held_lift = check_training_actions(demo, info["simulation"])
            rows.append({
                "seed": row["seed"], "failure_kind": row["failure_kind"],
                "model_checkpoint": row["checkpoint"], "model_rollout": row["folder"],
                "model_source_sha256": row["source_sha256"],
                "model_held_lift_m": row["held_lift_m"],
                "corrective_recipe": recipe, "demo_folder": name, "demo_frames": frames,
                "demo_sha256": demo_sha256(demo),
                "raw_audit": raw_audit, "export_replay_held_lift_m": replay_held_lift,
            })
            # Raw 20 Hz recordings are not in the final dataset; only audited 10 Hz exports are.
            if not raw.resolve().is_relative_to(stage.resolve()):
                raise ValueError("Raw simulator session escaped the temporary collection directory.")
            shutil.rmtree(raw)
        report = datasets.validate_dataset(str(stage), CONFIG)
        if not report.ok or report.episodes != len(rows):
            raise ValueError(f"Dream dataset validation failed: {report}")
        manifest = {
            "method": "failure_conditioned_simulation",
            "task": TASK, "model_checkpoint": selected[0]["checkpoint"],
            "eligible_failed_rollouts": len(failures), "selected_demos": len(rows),
            "frames": report.frames, "fps": report.fps,
            "reserved_evaluation_seeds": "901-912 excluded",
            "previous_training_seeds": "41-48, 101-116, 201-224 excluded",
            "sessions": rows,
            "interpretation": "Validated simulator trajectories; not real-robot demonstrations or proof of model improvement.",
        }
        for name in names:
            (stage / name).rename(output / name)
        pending = output / f"{manifest_name}.tmp"
        pending.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        pending.replace(output / manifest_name)
    return {"manifest": str(output / manifest_name), **manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-rollouts", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(os.getenv(
        "COACH_DEMOS_DIR", str(Path(os.getenv("LOCALAPPDATA", Path.home())) / "TeachTaskCoach/demos")
    )))
    parser.add_argument("--max-demos", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(collect(args.model_rollouts, args.output, max_demos=args.max_demos), indent=2))


if __name__ == "__main__":
    main()
