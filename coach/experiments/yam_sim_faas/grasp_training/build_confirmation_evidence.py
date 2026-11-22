"""Rebuild the committed paired demo from eight local held-out simulator rollouts."""

import argparse
import json
from pathlib import Path

from score_rollouts import score

from teach_task_coach.paired_audit import PairedRequest

RUNS = {
    905: ("yam-44fe8c6519ce462db554368b8c2a2cfb", "yam-14a305b9f558424d8fe01e32358d89c2"),
    906: ("yam-8e1657a3fa494cba999600ee8ce3b80c", "yam-ebf154883ef546ca9e26dfb530c56c65"),
    907: ("yam-3f669cf8fec8436b8c7e248cab7f9c48", "yam-ef09816c6ff04516aac271be192cdf38"),
    908: ("yam-230a77db8f254f2cbe4abf5a001f1713", "yam-c556ca8cfcb2466ea3612f74219090d7"),
}


def attempt(root: Path, name: str) -> dict:
    folder = root / name
    info = json.loads((folder / "rollout.json").read_text(encoding="utf-8"))
    result = score(folder)
    if info["status"] != "complete" or result["height_source"] != "recorded":
        raise ValueError(f"{name}: a complete recorded-height rollout is required")
    return {
        "trial_id": name, "episode_id": name, "checkpoint_id": result["checkpoint"],
        "source_uri": f"local-rollout://{name}", "session_id": name,
        "recorded_at": info["started_at_utc"],
        "outcome": "success" if result["success"] else "failure",
        "training_exposure": "held_out", "human_verified": False,
        "safety_stops": 0, "model_action_rows": result["model_action_rows"],
        "held_lift_m": result["held_lift_m"], "peak_lift_m": result["peak_lift_m"],
        "first_close_after_warmup_s": result["first_close_after_warmup_s"],
        "replay_max_state_error_m": result["replay_max_state_error"],
        "height_source": result["height_source"],
    }


def build(root: Path) -> PairedRequest:
    pairs = []
    for seed, (base, candidate) in RUNS.items():
        pairs.append({
            "pair_id": f"scene-{seed}", "scenario_id": f"apple-seed-{seed}",
            "baseline": attempt(root, base), "candidate": attempt(root, candidate),
        })
    return PairedRequest.model_validate({
        "plan": {
            "evaluation_id": "apple-500step-confirmation-905-908",
            "task": "pick up the apple",
            "success_rule": "Apple rises at least 8 cm and stays there for two continuous seconds",
            "reset_protocol": "Reset YAM and the apple to the same seeded scene before each checkpoint",
            "assignment_protocol": "Candidate first on 905/907; base first on 906/908",
            "protocol_ref": "git:e80edcc/coach/experiments/yam_sim_faas/grasp_training/CONFIRMATION_PROTOCOL.md",
            "baseline_checkpoint": "dreamlabs/dream-1-beta",
            "candidate_checkpoint": "dream-1-ft:7820aef9-apple-varied24-500",
            "collection_mode": "simulation", "planned_pairs": 4,
            "minimum_improvement": 0.0, "created_at": "2026-11-22T10:16:59+01:00",
            "required_model_rows": 576, "simulator_hold_threshold_m": 0.08,
        },
        "pairs": pairs,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollouts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = build(args.rollouts)
    args.output.write_text(json.dumps(request.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(request.pairs)} paired simulator scenes to {args.output}")


if __name__ == "__main__":
    main()
