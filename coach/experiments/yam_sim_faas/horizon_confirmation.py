"""Confirm the nine-versus-twelve-request boundary on fresh Dream-1 sim runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from closed_loop_repair_study import classify, now, write_json

HERE = Path(__file__).resolve().parent
PLAN = HERE / "horizon_confirmation_plan.json"


def load_plan(root: Path) -> dict:
    source = PLAN.read_bytes()
    root.mkdir(parents=True, exist_ok=True)
    frozen = root / "frozen_plan.json"
    if frozen.exists() and frozen.read_bytes() != source:
        raise ValueError("The committed plan changed after this study began.")
    if not frozen.exists():
        frozen.write_bytes(source)
    plan = json.loads(source)
    seeds = plan["seeds"]
    if (len(seeds) != len(set(seeds)) or min(seeds) < 921
            or plan["prefix_max_requests"] >= plan["full_max_requests"]):
        raise ValueError("Invalid confirmation plan.")
    return {**plan, "plan_sha256": hashlib.sha256(source).hexdigest()}


def held_lift(heights: np.ndarray, action_requests: int) -> float:
    end = 33 + 48 * action_requests
    if len(heights) < end:
        raise ValueError(f"Incomplete trace for {action_requests} requests.")
    rise = heights[:end] - heights[29]
    windows = np.lib.stride_tricks.sliding_window_view(rise, 41)
    return float(np.max(np.min(windows, axis=1)))


def prefix_evidence(folder: Path, plan: dict) -> dict:
    sidecars = list(folder.glob("*/rollout.json"))
    if len(sidecars) != 1:
        raise ValueError("Expected one completed rollout.")
    data = sidecars[0].parent / "data/chunk-000/episode_000000.parquet"
    table = pq.read_table(data, columns=["observation.apple_height_m"])
    heights = np.asarray(table["observation.apple_height_m"].to_numpy(), dtype=float)
    full = plan["full_max_requests"]
    prefix = plan["prefix_max_requests"]
    if len(heights) != 33 + 48 * full:
        raise ValueError(f"Expected {33 + 48 * full} recorded rows; found {len(heights)}.")
    earliest = next((n for n in range(1, full + 1) if held_lift(heights, n) >= 0.08), None)
    return {"prefix_held_lift_m": held_lift(heights, prefix),
            "full_held_lift_m": held_lift(heights, full),
            "prefix_success": held_lift(heights, prefix) >= 0.08,
            "earliest_success_request": earliest}


def run(root: Path) -> None:
    plan = load_plan(root)
    recorder = HERE / "record_dream_model_rollout.py"
    for seed in plan["seeds"]:
        folder = root / f"seed-{seed}"
        trial_file = folder / "trial.json"
        if trial_file.exists():
            print(f"Already recorded: seed {seed}", flush=True)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        if list(folder.glob("*/rollout.json")):
            raise RuntimeError(f"Unclassified prior attempt in {folder}; inspect before resuming.")
        command = [sys.executable, str(recorder), "--output", str(folder),
                   "--model", plan["model"], "--task", plan["task"],
                   "--start-pose", plan["start_pose"], "--seed", str(seed),
                   "--max-requests", str(plan["full_max_requests"]),
                   "--seconds", str(plan["trial_cap_wall_seconds"]), "--score-only"]
        started_at = now()
        print(f"Running confirmation seed {seed}", flush=True)
        start = time.monotonic()
        with (folder / "recorder.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        result = {"study_id": plan["study_id"], "plan_sha256": plan["plan_sha256"],
                  "seed": seed, "model": plan["model"], "started_at": started_at,
                  "ended_at": now(), "wall_seconds": round(time.monotonic() - start, 3),
                  "process_exit_code": completed.returncode,
                  **classify(folder, seed, plan["model"])}
        if completed.returncode != 0:
            result.update(valid=False, success=None, reason="Recorder process failed; inspect recorder.log.")
        if result["valid"]:
            try:
                result.update(prefix_evidence(folder, plan))
                if result["success"] != (result["full_held_lift_m"] >= 0.08):
                    raise ValueError("Prefix and full rollout scores disagree.")
            except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
                result.update(valid=False, success=None, reason=f"Prefix scoring failed: {error}")
        write_json(trial_file, result)
        print(f"  valid={result['valid']} prefix={result.get('prefix_success')} full={result['success']}",
              flush=True)
    print(json.dumps(analyze(root), indent=2), flush=True)


def analyze(root: Path) -> dict:
    plan = load_plan(root)
    trials = []
    for seed in plan["seeds"]:
        path = root / f"seed-{seed}" / "trial.json"
        if not path.exists():
            trials.append({"seed": seed, "valid": False, "success": None,
                           "reason": "Trial not run."})
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if (row["seed"] != seed or row["model"] != plan["model"]
                or row["plan_sha256"] != plan["plan_sha256"]):
            raise ValueError(f"Trial record conflicts with frozen plan: {path}")
        trials.append(row)
    valid = [row for row in trials if row["valid"]]
    return {"study_id": plan["study_id"], "kind": plan["kind"],
            "plan_sha256": plan["plan_sha256"], "model": plan["model"],
            "planned_trials": len(trials), "valid_trials": len(valid),
            "prefix_9_successes": sum(row["prefix_success"] for row in valid),
            "full_12_successes": sum(row["success"] for row in valid),
            "extra_requests_needed": sum(row["success"] and not row["prefix_success"] for row in valid),
            "wall_seconds_total": round(sum(row.get("wall_seconds", 0) for row in trials), 3),
            "trials": [{key: row.get(key) for key in (
                "seed", "valid", "success", "prefix_success", "earliest_success_request",
                "prefix_held_lift_m", "full_held_lift_m", "run_id", "reason")}
                for row in trials],
            "interpretation": plan["interpretation"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "analyze"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "run":
        run(args.output)
    else:
        print(json.dumps(analyze(args.output), indent=2))


if __name__ == "__main__":
    main()
