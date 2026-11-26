"""Machine-readable scoring for the chat's staged YAM recording."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "grasp_training"))
from score_rollouts import score


def score_trial(rollout: Path, held_out: int | None, *, diagnose: bool) -> dict:
    [sidecar] = rollout.glob("*/rollout.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    result = score(
        sidecar.parent,
        training_candidate=held_out is None,
        evaluation_seeds=None if held_out is None else {held_out},
        diagnostics=diagnose,
    )
    return {**result, "started_at": metadata["started_at_utc"], "task": metadata["task"]}


def diagnose_batch(raw: str) -> dict:
    trials = json.loads(raw)
    if not isinstance(trials, list) or not 1 <= len(trials) <= 16:
        raise ValueError("The diagnostic batch must contain between 1 and 16 paired trials.")
    scores = {}
    for trial in trials:
        if (
            not isinstance(trial, dict) or not isinstance(trial.get("folder"), str)
            or type(trial.get("seed")) is not int or not 0 <= trial["seed"] < 2**32
        ):
            raise ValueError("Every diagnostic request needs a trial folder and valid scene seed.")
        try:
            scores[trial["folder"]] = score_trial(Path(trial["folder"]), trial["seed"], diagnose=True)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, IndexError):
            # The caller falls back to saved metrics for this trial alone.
            continue
    return {"scores": scores}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rollout", type=Path, nargs="?")
    parser.add_argument("--held-out-seed", type=int)
    parser.add_argument("--diagnose", action="store_true", help="Explain the recorded task outcome.")
    parser.add_argument("--diagnose-batch", help="Score a JSON list of saved held-out trial folders and scene seeds.")
    parser.add_argument("--collect-into", type=Path)
    parser.add_argument("--max-demos", type=int, default=4)
    args = parser.parse_args()
    if args.diagnose_batch is not None:
        print("WORKFLOW_RESULT=" + json.dumps(diagnose_batch(args.diagnose_batch)))
        return
    if args.rollout is None:
        parser.error("A rollout folder is required.")
    if args.collect_into:
        from collect_failure_demos import collect

        result = collect(args.rollout, args.collect_into, max_demos=args.max_demos)
        print("WORKFLOW_RESULT=" + json.dumps(result))
        return
    result = score_trial(args.rollout, args.held_out_seed, diagnose=args.diagnose)
    print("WORKFLOW_RESULT=" + json.dumps(result))


if __name__ == "__main__":
    main()
