"""Build and serve the Coach's isolated, network-free offline walkthrough."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from teach_task_coach.api import create_app
from teach_task_coach.demos import DemoScanner, DemoStore
from teach_task_coach.episodes import RolloutScanner
from teach_task_coach.faas import FaaSStore
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore

TASK = "pick up the apple"
SUCCESS_RULE = "Both fingers of one hand contact the apple, raise it more than 8 cm, and hold for 2 seconds."
PROTOCOL = "coach-offline-walkthrough-v1"


class NoExternalCalls:
    def __getattr__(self, name):
        raise AssertionError(f"Offline-only app attempted external call: {name}")


def _run(root: Path, *, task_id: str, scene_id: str, seed: int, role: str, pickup: bool) -> Path:
    """Write an explicitly synthetic controller trace using the bundled YAM simulator."""
    from frozen_scene import digest, state
    from record_yam_demos import mock_pickups, recording

    with recording(root, TASK, f"offline-fixture/{role}", seed, "scripted", start_pose="wrist-visible") as (env, sim):
        sim.update(
            policy_origin="offline_fixture",
            offline_task_id=task_id,
            offline_scene_id=scene_id,
            comparison_role=role,
            warmup_rows=30,
            requests_attempted=0,
            rule_version="yam-apple-v1",
            protocol=PROTOCOL,
        )
        start = env.state()
        for _ in range(30):
            env.step(start["left"], start["right"])
        sim["pre_action_state_hash"] = digest(state(env).tolist())
        if pickup:
            # This deterministic scripted controller is an interaction fixture, never policy inference.
            # It advances exactly one physics tick per recorded action so video, trace,
            # and action timestamps remain aligned in the review surface.
            with open(os.devnull, "w") as sink, redirect_stdout(sink):
                result = mock_pickups.run_trial("apple", env=env, snapshot_dir=env.folder, settle_steps=0)
            sim["script_result"] = result
        else:
            for _ in range(295):
                env.step(start["left"], start["right"])
        sim["model_action_rows"] = len(env.states) - sim["warmup_rows"]
        sim["action_budget"] = 295
        captured_folder = env.folder
    return captured_folder


def create_workspace(root: Path) -> tuple[Path, str]:
    """Create one complete explanatory pair and one visibly incomplete pair."""
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    sim_dir = Path(__file__).resolve().parents[3] / "dream_library/examples/yam_mujoco"
    sys.path.insert(0, str(sim_dir))
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root / "coach/experiments/yam_sim_faas"))

    data = root / "data"
    rolls = root / "rollouts"
    demo_root = root / "demos"
    demo_root.mkdir()
    task = TaskStore(data).create_task(
        TaskInput(name="Apple pickup · offline walkthrough", prompt=TASK,
                  baseline_checkpoint="offline-fixture/baseline", success_rule=SUCCESS_RULE),
        offline_mode=True,
    )

    scenes = [
        {"id": "scene-3101", "seed": 3101, "sides": ["baseline", "candidate"], "candidate_pickup": True},
        {"id": "scene-3102", "seed": 3102, "sides": ["baseline"], "candidate_pickup": False},
    ]
    protocol_value = {
        "schema": PROTOCOL,
        "task_id": task.id,
        "task": TASK,
        "success_rule": SUCCESS_RULE,
        "rule_version": "yam-apple-v1",
        "disclaimer": "All controllers are offline scripted fixtures; none is Dream-1 evidence.",
        "scenes": scenes,
    }
    protocol = data / "offline-protocol.json"
    protocol.write_text(json.dumps(protocol_value, indent=2, sort_keys=True), encoding="utf-8")
    protocol_hash = hashlib.sha256(protocol.read_bytes()).hexdigest()

    for scene in scenes:
        for role in scene["sides"]:
            pickup = role == "candidate" and scene["id"] == "scene-3101"
            episode_root = _run(rolls, task_id=task.id, scene_id=scene["id"], seed=scene["seed"], role=role, pickup=pickup)
            sidecar = episode_root / "rollout.json"
            # `recording()` wrote a closed sidecar; bind it to the immutable local protocol.
            value = json.loads(sidecar.read_text(encoding="utf-8"))
            value["simulation"]["protocol_sha256"] = protocol_hash
            sidecar.write_text(json.dumps(value, indent=2), encoding="utf-8")

    store = EpisodeStore(data)
    found, skipped = RolloutScanner(rolls).scan()
    if skipped:
        raise RuntimeError(f"Unexpected offline fixture scan issues: {skipped}")
    for episode in found:
        store.upsert(episode)
    if len(found) != 3:
        raise RuntimeError(f"Expected 3 fixture episodes; imported {len(found)}")

    # Keep a separate, explicitly scripted reference demo. It is deliberately not auto-kept.
    from record_yam_demos import mock_pickups, recording
    source_episode_id = next(
        episode.id for episode in found
        if episode.simulation and episode.simulation.get("offline_scene_id") == "scene-3101"
        and episode.simulation.get("comparison_role") == "candidate"
    )
    with recording(demo_root, TASK, "scripted-reference/yam", 3201, "scripted", start_pose="wrist-visible") as (env, sim):
        sim.update(policy_origin="scripted_reference", offline_task_id=task.id, source_episode_id=source_episode_id, rule_version="yam-apple-v1")
        with open(os.devnull, "w") as sink, redirect_stdout(sink):
            sim["script_result"] = mock_pickups.run_trial("apple", env=env, snapshot_dir=env.folder)
    demos, skipped = DemoScanner(demo_root).scan(task.id, TASK)
    if skipped or len(demos) != 1:
        raise RuntimeError(f"Unexpected scripted demo scan: {skipped}")
    DemoStore(data).upsert(demos[0])
    return root, task.id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="Create fixtures in this new directory")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = args.directory.expanduser().resolve() if args.directory else Path(tempfile.mkdtemp(prefix="teach-task-coach-offline-")) / "workspace"
    root, task_id = create_workspace(root)
    os.environ["COACH_DATA_DIR"] = str(root / "data")
    os.environ["COACH_ROLLOUTS_DIR"] = str(root / "rollouts")
    os.environ["COACH_DEMOS_DIR"] = str(root / "demos")
    app = create_app(
        service=PreflightService(NoExternalCalls(), NoExternalCalls()),
        store=EpisodeStore(root / "data"),
        scanner=RolloutScanner(root / "rollouts"),
        task_store=TaskStore(root / "data"),
        demo_store=DemoStore(root / "data"),
        demo_scanner=DemoScanner(root / "demos"),
        faas_store=FaaSStore(root / "data"),
        dream_gateway=NoExternalCalls(),
        offline_only=True,
    )
    import uvicorn

    print("Offline walkthrough only: no Dream API, station, robot, upload, or training access.")
    print(f"Workspace: {root}")
    print(f"Open http://127.0.0.1:{args.port}/#/offline?task={task_id}")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
