"""Build the second account's frozen paired snapshot from every local 909-912 rollout."""

import argparse
import json
from pathlib import Path

from score_rollouts import score

from teach_task_coach.paired_audit import PairedRequest, evaluate_paired

BASE = "dreamlabs/dream-1-beta"
CANDIDATE = "dream-1-ft:f2cc8d90-apple-independent24-500"
SEEDS = (909, 910, 911, 912)


def _attempt(folder: Path, info: dict) -> dict:
    name = folder.name
    fields = {
        "trial_id": name, "episode_id": name, "checkpoint_id": info["checkpoint"],
        "source_uri": f"local-rollout://{name}", "session_id": name,
        "recorded_at": info.get("started_at_utc"),
        "training_exposure": "held_out", "human_verified": False,
        "safety_stops": int(info.get("stop_reason") == "SafetyStop"),
        "duration_s": info.get("duration_s"),
    }
    try:
        result = score(folder)
    except (OSError, ValueError, KeyError):
        fields["outcome"] = "invalid"
        fields["model_action_rows"] = info.get("simulation", {}).get("model_action_rows")
    else:
        fields.update(
            outcome="success" if result["success"] else "failure",
            model_action_rows=result["model_action_rows"],
            held_lift_m=result["held_lift_m"], peak_lift_m=result["peak_lift_m"],
            first_close_after_warmup_s=result["first_close_after_warmup_s"],
            replay_max_state_error_m=result["replay_max_state_error"],
            height_source=result["height_source"],
        )
    return fields


def build(root: Path) -> PairedRequest:
    found: dict[tuple[int, str], tuple[Path, dict]] = {}
    for folder in sorted(root.glob("yam-*")):
        source = folder / "rollout.json"
        if not source.is_file():
            continue
        info = json.loads(source.read_text(encoding="utf-8"))
        scene = info.get("simulation") or {}
        key = scene.get("seed"), info.get("checkpoint")
        if key[0] not in SEEDS:
            continue
        if key[1] not in {BASE, CANDIDATE}:
            raise ValueError(f"Unexpected checkpoint on reserved scene {key[0]}: {key[1]}")
        if key in found:
            raise ValueError(f"Multiple attempts for seed {key[0]} and checkpoint {key[1]}; review manually")
        found[key] = (folder, info)
    pairs = []
    for seed in SEEDS:
        arms = {}
        for role, checkpoint in (("baseline", BASE), ("candidate", CANDIDATE)):
            if (seed, checkpoint) in found:
                folder, info = found[seed, checkpoint]
                arms[role] = _attempt(folder, info)
        if arms:
            pairs.append({
                "pair_id": f"scene-{seed}", "scenario_id": f"apple-seed-{seed}",
                "baseline": arms.get("baseline"), "candidate": arms.get("candidate"),
            })
    return PairedRequest.model_validate({
        "plan": {
            "evaluation_id": "apple-independent24-500-confirmation-909-912",
            "task": "pick up the apple",
            "success_rule": "Apple rises at least 8 cm and stays there for two continuous seconds",
            "reset_protocol": "Reset YAM and the apple to the same seeded scene before each checkpoint",
            "assignment_protocol": "Candidate first on 909/911; base first on 910/912",
            "protocol_ref": "git:fb78357/coach/experiments/yam_sim_faas/grasp_training/SECOND_ACCOUNT_CONFIRMATION_PROTOCOL.md",
            "baseline_checkpoint": BASE, "candidate_checkpoint": CANDIDATE,
            "collection_mode": "simulation", "planned_pairs": 4,
            "minimum_improvement": 0.0, "created_at": "2026-11-22T11:34:14+01:00",
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
    result = evaluate_paired(request)
    print(f"{result.decision}: {result.baseline_successes}/{result.baseline_attempted} base, "
          f"{result.candidate_successes}/{result.candidate_attempted} candidate; "
          f"{len(result.problems)} evidence problems; SHA-256 {result.input_sha256}")


if __name__ == "__main__":
    main()
