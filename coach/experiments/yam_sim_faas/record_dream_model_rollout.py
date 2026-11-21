"""Record Dream-1 controlling the repo's YAM simulator; requires DREAM_API_KEY."""

import argparse
import os
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
    args = parser.parse_args()
    if not os.getenv("DREAM_API_KEY"):
        parser.error("Set DREAM_API_KEY in the process environment")
    recorder.ROOT = args.output.resolve()
    recorder.ROOT.mkdir(exist_ok=True)
    recorder.TASK = args.task
    env = recorder.RecordingYamEnv()
    try:
        dream_control.main(
            ["--headless", "--quiet", "--seconds", str(args.seconds), "--task", args.task],
            shared_env=env,
        )
    finally:
        env.close()


if __name__ == "__main__":
    main()
