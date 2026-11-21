"""Record Dream-1 controlling the repo's YAM simulator; requires DREAM_API_KEY."""

import argparse
import os
import secrets
import sys
from pathlib import Path

import record_yam_demos as recorder

SIM = Path(__file__).resolve().parents[3] / "dream_library/examples/yam_mujoco"
sys.path.insert(0, str(SIM))
import dream_control


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path.cwd() / "yam_dream1_rollout")
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--task", default="pick up the apple")
    parser.add_argument("--model", type=dream_control.resolve_model, default=dream_control.BETA_MODEL)
    parser.add_argument("--seed", type=recorder.scene_seed, help="Repeat a recorded apple placement")
    parser.add_argument("--max-requests", type=int, default=1, help="Limit get_action calls per run")
    parser.add_argument("--dry-run", action="store_true", help="Record the observation warm-up offline")
    args = parser.parse_args()
    if not args.dry_run and not os.getenv("DREAM_API_KEY"):
        parser.error("Set DREAM_API_KEY in the process environment")
    if args.max_requests < 1:
        parser.error("--max-requests must be positive")
    seed = args.seed if args.seed is not None else secrets.randbits(32)
    source = "observation dry run" if args.dry_run else "model"
    with recorder.recording(args.output, args.task, args.model, seed, source) as (env, details):
        options = ["--headless", "--quiet", "--seconds", str(args.seconds), "--task", args.task,
                   "--model", args.model, "--max-requests", str(args.max_requests)]
        if args.dry_run:
            options.append("--dry-run")
        rows = dream_control.main(options, shared_env=env) or 0
        details["model_action_rows"] = rows
        if not args.dry_run and not rows:
            raise RuntimeError("Pilot ended with zero executed model actions. Review the partial recording.")


if __name__ == "__main__":
    main()
