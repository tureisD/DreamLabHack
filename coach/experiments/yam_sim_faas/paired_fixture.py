"""Run a descriptive held-out two-scene comparison with stand-ins, never Dream or hardware."""

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
from frozen_scene import digest, freeze, restore, state
from record_yam_demos import FPS, TASK, RecordingYamEnv, mock_pickups, recording

from teach_task_coach.episodes import read_episode

RULE = "Both fingertips of one hand, more than 0.08 m elevation for at least 2 s without other support."
BUDGET = 325
WARMUP = 4


def create_fixture(root, task_id):
    root.mkdir(parents=True, exist_ok=False)
    plans = []
    for seed in (111, 222):
        setup = root / "preparation" / str(seed)
        setup.mkdir(parents=True)
        env = RecordingYamEnv(setup, TASK, seed, defer_video=True)
        try:
            manifest = freeze(
                root / "scenes",
                env,
                task_id=task_id,
                instruction=TASK,
                rule=RULE,
                seed=seed,
                pose="home",
                split="heldout",
                budget=BUDGET,
                warmup=WARMUP,
            )
        finally:
            env.close()
        plans.append(
            {"scene": manifest.stem, "seed": seed, "pair": digest([task_id, manifest.stem])}
        )
    protocol = {
        "schema": "yam-fixture-protocol-v1",
        "task_id": task_id,
        "rule": RULE,
        "task": TASK,
        "fps": FPS,
        "action_budget": BUDGET,
        "warmup_rows": WARMUP,
        "scenes": plans,
        "checkpoints": {"baseline": "fixture/hold", "candidate": "fixture/scripted-pickup"},
        "repeat_policy": "first recorded attempt only; no substitution",
        "split": "heldout",
    }
    with (root / "protocol.json").open("x") as f:
        json.dump(protocol, f, indent=2)
    for n, scene in enumerate(plans):
        for side, checkpoint in protocol["checkpoints"].items():
            if n == 1 and side == "candidate":
                continue  # Deliberate missing-side acceptance case.
            with recording(root / "attempts", TASK, checkpoint, scene["seed"], "model") as (
                env,
                sidecar,
            ):
                manifest = restore(
                    root / "scenes" / (scene["scene"] + ".json"),
                    env,
                    seed=scene["seed"],
                    pose="home",
                )
                sidecar.update(
                    policy_origin="offline_fixture",
                    comparison_role=side,
                    task_id=task_id,
                    pair_id=scene["pair"],
                    scene_id=scene["scene"],
                    rule_hash=manifest["rule_hash"],
                    protocol_hash=digest(protocol),
                    action_budget=BUDGET,
                    warmup_rows=WARMUP,
                    requests_attempted=0,
                    split="heldout",
                )
                for _ in range(WARMUP):
                    pose = env.state()
                    env.step(pose["left"], pose["right"])
                sidecar["pre_action_state_hash"] = digest(state(env).tolist())
                if side == "candidate":
                    mock_pickups.run_trial("apple", env=env, snapshot_dir=env.folder)
                else:
                    pose = env.state()
                    for _ in range(BUDGET):
                        env.step(pose["left"], pose["right"])
                sidecar["model_action_rows"] = len(env.states) - WARMUP
                sidecar["end_state_hash"] = digest(state(env).tolist())
    return protocol


def summarize(root):
    p = json.loads((root / "protocol.json").read_text())
    records = []
    for folder in sorted((root / "attempts").glob("*/rollout.json")):
        e = read_episode(folder.parent)
        sim = e.simulation or {}
        evidence = e.pickup_evidence
        records.append(
            {
                "id": e.id,
                "task": e.task,
                "checkpoint": e.checkpoint,
                "sim": sim,
                "status": e.status,
                "stop": e.stop_reason,
                "frames": e.frames,
                "fps": e.fps,
                "label": e.success,
                "operator_note": e.note,
                "started": e.started_at_utc,
                "evidence": evidence.model_dump() if evidence else None,
                "videos": {k: str(Path(v).relative_to(root)) for k, v in e.videos.items()},
            }
        )
    pairs = []
    for spec in p["scenes"]:
        manifest = json.loads((root / "scenes" / (spec["scene"] + ".json")).read_text())
        errors = []
        chosen = {}
        if digest(manifest) != spec["scene"]:
            errors.append("manifest hash mismatch")
        for side, checkpoint in p["checkpoints"].items():
            attempts = sorted(
                (
                    e
                    for e in records
                    if e["sim"].get("pair_id") == spec["pair"]
                    and e["sim"].get("comparison_role") == side
                ),
                key=lambda e: (e["started"] or "", e["id"]),
            )
            if not attempts:
                errors.append("missing " + side)
                continue
            e = chosen[side] = attempts[0]
            s = e["sim"]
            expected = (
                spec["scene"],
                p["task_id"],
                manifest["rule_hash"],
                digest(p),
                checkpoint,
                p["task"],
                p["fps"],
                p["action_budget"],
                p["warmup_rows"],
                "heldout",
                "offline_fixture",
            )
            actual = (
                s.get("scene_id"),
                s.get("task_id"),
                s.get("rule_hash"),
                s.get("protocol_hash"),
                e["checkpoint"],
                e["task"],
                e["fps"],
                s.get("action_budget"),
                s.get("warmup_rows"),
                s.get("split"),
                s.get("policy_origin"),
            )
            if actual != expected:
                errors.append(side + " protocol mismatch")
            if (
                e["status"] != "complete"
                or s.get("model_action_rows") != p["action_budget"]
                or e["frames"] != p["warmup_rows"] + p["action_budget"]
            ):
                errors.append(side + " incomplete action window")
            if not e["evidence"] or e["evidence"]["observation"] in ("unavailable", "no_actions"):
                errors.append(side + " unavailable evidence")
        if len(chosen) == 2 and (
            not chosen["baseline"]["sim"].get("pre_action_state_hash")
            or chosen["baseline"]["sim"].get("pre_action_state_hash")
            != chosen["candidate"]["sim"].get("pre_action_state_hash")
        ):
            errors.append("actual action-start state differs")
        diff = None
        if not errors:
            peaks = [chosen[k]["evidence"]["peak_lift_m"] for k in ("baseline", "candidate")]
            if all(isinstance(v, (float, int)) and np.isfinite(v) for v in peaks):
                diff = peaks[1] - peaks[0]
        pairs.append(
            {
                "scene_id": spec["scene"],
                "pair_id": spec["pair"],
                "sides": chosen,
                "reasons": errors,
                "candidate_minus_baseline_lift_m": diff,
            }
        )
    return {
        "schema": "yam-descriptive-report-v1",
        "source": "offline simulation fixtures, not Dream-1",
        "task_id": p["task_id"],
        "rule": p["rule"],
        "protocol_hash": digest(p),
        "data_hash": digest(records),
        "started_attempts": len(records),
        "partial_attempts": sum(e["status"] != "complete" for e in records),
        "planned_pairs": len(pairs),
        "comparable_pairs": sum(not x["reasons"] for x in pairs),
        "human_labelled_pairs": sum(
            not x["reasons"] and all(e["label"] is not None for e in x["sides"].values())
            for x in pairs
        ),
        "attempts": records,
        "pairs": pairs,
        "promotion": False,
    }


def save_report(root, history):
    report = summarize(root)
    history.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).isoformat(timespec="microseconds")
    version = digest([stamp, report])
    report["recorded_at"] = stamp
    with (history / (version + ".json")).open("x") as f:
        json.dump(report, f, indent=2, allow_nan=False)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    create_fixture(args.directory, args.task_id)
    report = save_report(args.directory, args.history)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "source",
                    "started_attempts",
                    "planned_pairs",
                    "comparable_pairs",
                    "human_labelled_pairs",
                    "protocol_hash",
                    "data_hash",
                )
            }
        )
    )
