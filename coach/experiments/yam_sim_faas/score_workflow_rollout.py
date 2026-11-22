"""Machine-readable scoring for the chat's staged YAM recording."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "grasp_training"))
from score_rollouts import score


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rollout", type=Path)
    parser.add_argument("--held-out-seed", type=int)
    parser.add_argument("--diagnose", action="store_true", help="Explain the recorded task outcome.")
    parser.add_argument("--collect-into", type=Path)
    parser.add_argument("--max-demos", type=int, default=4)
    args = parser.parse_args()
    if args.collect_into:
        from collect_failure_demos import collect

        result = collect(args.rollout, args.collect_into, max_demos=args.max_demos)
        print("WORKFLOW_RESULT=" + json.dumps(result))
        return
    folders = list(args.rollout.glob("*/rollout.json"))
    if len(folders) != 1:
        parser.error("Expected one rollout in this trial directory.")
    sidecar = folders[0]
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    held_out = args.held_out_seed
    result = score(
        sidecar.parent,
        training_candidate=held_out is None,
        evaluation_seeds=None if held_out is None else {held_out},
        diagnostics=args.diagnose,
    )
    print("WORKFLOW_RESULT=" + json.dumps({**result, "started_at": metadata["started_at_utc"]}))


if __name__ == "__main__":
    main()
