"""Run and audit the frozen same-checkpoint simulator repair comparison.

Use the current Dream credentials file. No dataset upload or FaaS submission occurs.
Every started trial is retained, including partial and failed runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = HERE / "closed_loop_repair_plan.json"
sys.path.insert(0, str(HERE / "grasp_training"))
from score_rollouts import score  # noqa: E402


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_plan(root: Path) -> dict:
    source = PLAN.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    frozen = root / "frozen_plan.json"
    if frozen.exists() and frozen.read_bytes() != source:
        raise ValueError("The committed plan changed after this study began.")
    if not frozen.exists():
        frozen.write_bytes(source)
    plan = json.loads(source)
    if (len(plan["seeds"]) != len(set(plan["seeds"]))
            or set(plan["conditions"]) != {"original_short", "coach_extended"}):
        raise ValueError("Invalid study design.")
    for seed in plan["seeds"]:
        if set(plan["order"][str(seed)]) != set(plan["conditions"]):
            raise ValueError(f"Invalid condition order for seed {seed}.")
    return {**plan, "plan_sha256": digest}


def trial_path(root: Path, seed: int, condition: str) -> Path:
    return root / f"seed-{seed}" / condition


def classify(folder: Path, seed: int, model: str) -> dict:
    sidecars = list(folder.glob("*/rollout.json"))
    if len(sidecars) != 1:
        return {"valid": False, "success": None,
                "reason": f"Expected one rollout sidecar; found {len(sidecars)}."}
    rollout = sidecars[0].parent
    info = json.loads(sidecars[0].read_text(encoding="utf-8"))
    scene = info.get("simulation", {})
    if (scene.get("seed") != seed or info.get("checkpoint") != model
            or scene.get("source") != "model"):
        return {"valid": False, "success": None, "reason": "Run metadata differs from frozen plan.",
                "run_id": rollout.name}
    common = {"run_id": rollout.name, "status": info.get("status"),
              "model_action_rows": scene.get("model_action_rows", 0),
              "requests_attempted": scene.get("requests_attempted"),
              "duration_s": info.get("duration_s")}
    if info.get("status") == "partial":
        if scene.get("model_action_rows", 0) > 0:
            return {**common, "valid": True, "success": False,
                    "reason": "Partial task run with executed model actions."}
        return {**common, "valid": False, "success": None,
                "reason": "No model actions were executed."}
    if info.get("status") != "complete":
        return {**common, "valid": False, "success": None,
                "reason": "Run did not complete."}
    try:
        scored = score(rollout, evaluation_seeds={seed})
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        return {**common, "valid": False, "success": None,
                "reason": f"Replay or scoring failed: {error}"}
    return {**common, "valid": True, "success": scored["success"],
            "reason": "Complete run and replay verified.",
            "peak_lift_m": scored["peak_lift_m"], "held_lift_m": scored["held_lift_m"],
            "first_close_after_warmup_s": scored["first_close_after_warmup_s"],
            "replay_max_state_error": scored["replay_max_state_error"]}


def run(root: Path) -> None:
    plan = load_plan(root)
    recorder = HERE / "record_dream_model_rollout.py"
    for seed in plan["seeds"]:
        for condition in plan["order"][str(seed)]:
            folder = trial_path(root, seed, condition)
            result_file = folder / "trial.json"
            if result_file.exists():
                print(f"Already recorded: seed {seed}, {condition}", flush=True)
                continue
            folder.mkdir(parents=True, exist_ok=True)
            existing = list(folder.glob("*/rollout.json"))
            if existing:
                raise RuntimeError(f"Unclassified prior attempt in {folder}; inspect it before resuming.")
            command = [sys.executable, str(recorder), "--output", str(folder),
                       "--model", plan["model"], "--task", plan["task"],
                       "--start-pose", plan["start_pose"], "--seed", str(seed),
                       "--max-requests", str(plan["conditions"][condition]["max_requests"]),
                       "--seconds", str(plan["trial_cap_wall_seconds"]), "--score-only"]
            started_at = now()
            print(f"Running seed {seed}, {condition}", flush=True)
            start = time.monotonic()
            with (folder / "recorder.log").open("w", encoding="utf-8") as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                           check=False)
            result = {"study_id": plan["study_id"], "plan_sha256": plan["plan_sha256"],
                      "seed": seed, "condition": condition, "model": plan["model"],
                      "max_requests": plan["conditions"][condition]["max_requests"],
                      "started_at": started_at, "ended_at": now(),
                      "wall_seconds": round(time.monotonic() - start, 3),
                      "process_exit_code": completed.returncode,
                      **classify(folder, seed, plan["model"])}
            if (completed.returncode != 0
                    and not (result.get("status") == "partial"
                             and result.get("model_action_rows", 0) > 0)):
                result.update(valid=False, success=None,
                              reason="Recorder process failed; inspect recorder.log.")
            write_json(result_file, result)
            print(f"  {result['reason']} success={result['success']}", flush=True)
    print(json.dumps(analyze(root), indent=2), flush=True)


def analyze(root: Path) -> dict:
    plan = load_plan(root)
    trials = []
    for seed in plan["seeds"]:
        for condition in plan["order"][str(seed)]:
            path = trial_path(root, seed, condition) / "trial.json"
            if not path.exists():
                trials.append({"seed": seed, "condition": condition, "valid": False,
                               "success": None, "reason": "Trial not run."})
                continue
            row = json.loads(path.read_text(encoding="utf-8"))
            if (row["seed"] != seed or row["condition"] != condition
                    or row["model"] != plan["model"]
                    or row["plan_sha256"] != plan["plan_sha256"]):
                raise ValueError(f"Trial record conflicts with frozen plan: {path}")
            trials.append(row)
    groups = {name: [row for row in trials if row["condition"] == name]
              for name in plan["conditions"]}
    summaries = {}
    for name, group in groups.items():
        valid = [row for row in group if row["valid"]]
        summaries[name] = {"planned": len(group), "valid": len(valid),
                           "successes": sum(row["success"] is True for row in valid),
                           "failures": sum(row["success"] is False for row in valid),
                           "wall_seconds_total": round(sum(row.get("wall_seconds", 0) for row in group), 3),
                           "model_action_rows_total": sum(row.get("model_action_rows", 0) for row in group)}
    pairs = []
    for seed in plan["seeds"]:
        short = next(row for row in groups["original_short"] if row["seed"] == seed)
        coach = next(row for row in groups["coach_extended"] if row["seed"] == seed)
        pairs.append({"seed": seed, "usable": short["valid"] and coach["valid"],
                      "original_short_success": short["success"],
                      "coach_extended_success": coach["success"],
                      "original_short_run_id": short.get("run_id"),
                      "coach_extended_run_id": coach.get("run_id")})
    usable = [pair for pair in pairs if pair["usable"]]
    return {"study_id": plan["study_id"], "kind": plan["kind"],
            "plan_sha256": plan["plan_sha256"], "model": plan["model"],
            "planned_pairs": len(pairs), "usable_pairs": len(usable),
            "conditions": summaries, "pairs": pairs,
            "coach_only_successes": sum(p["coach_extended_success"] and not p["original_short_success"] for p in usable),
            "original_only_successes": sum(p["original_short_success"] and not p["coach_extended_success"] for p in usable),
            "interpretation": plan["interpretation"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "analyze"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output) if args.action == "run" else analyze(args.output)
    if args.action == "analyze":
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
