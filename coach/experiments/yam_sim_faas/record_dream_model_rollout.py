"""Record Dream-1 controlling the repo's YAM simulator; requires DREAM_API_KEY."""

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

import record_yam_demos as recorder

SIM = Path(__file__).resolve().parents[3] / "dream_library/examples/yam_mujoco"
sys.path.insert(0, str(SIM))
import dream_control
import frozen_scene


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path.cwd() / "yam_dream1_rollout")
    parser.add_argument("--seconds", type=float, default=600, help="Wall-clock ceiling; action requests limit simulated motion")
    parser.add_argument("--task", default="pick up the apple")
    parser.add_argument("--model", type=dream_control.resolve_model, default=dream_control.BETA_MODEL)
    parser.add_argument("--seed", type=recorder.scene_seed, help="Repeat a recorded apple placement")
    parser.add_argument("--start-pose", choices=("home", "wrist-visible"))
    parser.add_argument("--held-out-scene", type=Path, help="Replay a frozen apple evaluation scene for exactly 20 simulated seconds")
    parser.add_argument("--max-requests", type=int, default=1, help="Limit get_action calls per run")
    parser.add_argument("--dry-run", action="store_true", help="Record the observation warm-up offline")
    parser.add_argument("--score-only", action="store_true", help="Save action/state replay without review videos")
    args = parser.parse_args(argv)
    if not args.dry_run and not os.getenv("DREAM_API_KEY"):
        parser.error("Set DREAM_API_KEY in the process environment")
    if args.max_requests < 1:
        parser.error("--max-requests must be positive")
    pose = args.start_pose or "home"
    seed = args.seed
    control_rows = 20 * recorder.FPS
    if args.held_out_scene is not None:
        spec = json.loads(args.held_out_scene.read_text(encoding="utf-8"))
        warmup = 1 + (dream_control.FRAMES - 1) * dream_control.FRAME_EVERY_STEPS
        if (
            spec.get("seed") not in (901, 902, 903, 904)
            or spec.get("start_pose") != "wrist-visible"
            or spec.get("instruction") != recorder.TASK or args.task != recorder.TASK
            or spec.get("split") != "heldout" or spec.get("action_budget") != control_rows
            or spec.get("fps") != recorder.FPS or spec.get("warmup") != warmup
            or seed not in (None, spec["seed"]) or args.start_pose not in (None, "wrist-visible")
        ):
            parser.error("Frozen scene does not match the held-out apple protocol or CLI options")
        seed, pose = spec["seed"], spec["start_pose"]
    if seed is None:
        seed = secrets.randbits(32)
    source = "observation dry run" if args.dry_run else "model"
    with recorder.recording(args.output, args.task, args.model, seed, source,
                            start_pose=pose, videos=not args.score_only) as (env, details):
        options = ["--headless", "--quiet", "--seconds", str(args.seconds), "--task", args.task,
                   "--model", args.model, "--max-requests", str(args.max_requests)]
        if args.dry_run:
            options.append("--dry-run")
        if args.held_out_scene is not None:
            manifest = frozen_scene.restore(args.held_out_scene, env, seed=seed, pose=pose)
            details.update(scene_id=args.held_out_scene.stem, split="heldout", rule_hash=manifest["rule_hash"],
                           action_budget=control_rows, simulator_hz=recorder.FPS)
            options.extend(["--control-rows", str(control_rows)])
        details.update(requests_attempted=0, model_action_rows=0)
        try:
            rows = dream_control.main(options, shared_env=env, progress=details) or 0
        except Exception as error:
            if args.held_out_scene is not None:
                details["control_stop"] = getattr(error, "reason", None) or type(error).__name__
            raise
        finally:
            details["simulated_control_seconds"] = details["model_action_rows"] / recorder.FPS
        if args.held_out_scene is not None and not args.dry_run and rows != control_rows:
            budgeted_calls = details["requests_attempted"] - details.get("pool_warming_refusals", 0)
            details["control_stop"] = "request_cap" if budgeted_calls >= args.max_requests else "wall_clock_limit"
            raise RuntimeError(f"Incomplete held-out trial: executed {rows} of {control_rows} control rows")
        if not args.dry_run and not rows:
            raise RuntimeError("Pilot ended with zero executed model actions. Review the partial recording.")


if __name__ == "__main__":
    main()
