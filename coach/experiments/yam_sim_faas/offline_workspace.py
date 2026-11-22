"""Create a new, isolated Coach acceptance workspace. No station or Dream client calls."""

import argparse
import json
from pathlib import Path

from record_yam_demos import TASK, mock_pickups, recording

from teach_task_coach.episodes import RolloutScanner
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore

FIXTURE = "offline-fixture/hold-position"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "directory", type=Path, help="New directory; existing data is never overwritten"
    )
    root = cli.parse_args().directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    runs, demos, data = (root / p for p in ("rollouts", "demos", "data"))
    # Deterministic stand-in policy for the recording pipeline. Never claim Dream inference.
    with recording(runs, TASK, FIXTURE, 41, "scripted", start_pose="wrist-visible") as (env, sim):
        sim.update(policy_origin="offline_fixture", offline_task_id="pending", warmup_rows=0, model_action_rows=80)
        pose = env.state()
        for _ in range(80):
            env.step(pose["left"], pose["right"])
    with recording(demos, TASK, "scripted-yam", 101, "scripted") as (env, sim):
        sim.update(policy_origin="scripted_reference", offline_task_id="pending")
        sim["script_result"] = mock_pickups.run_trial("apple", env=env, snapshot_dir=env.folder)
    tasks = TaskStore(data)
    for name in ("Apple pickup / control", "Apple pickup / offline review"):
        task = tasks.create_task(
            TaskInput(
                name=name,
                prompt=TASK,
                baseline_checkpoint=FIXTURE,
                success_rule="Within the 4-second test window, lift the apple over 8 cm and hold for at least 2 seconds.",
            ),
            offline_mode=True,
        )
    for folder in (runs, demos):
        for sidecar in folder.glob("*/rollout.json"):
            info = json.loads(sidecar.read_text(encoding="utf-8"))
            info["simulation"]["offline_task_id"] = task.id
            sidecar.write_text(json.dumps(info, indent=2), encoding="utf-8")
    store = EpisodeStore(data)
    found, skipped = RolloutScanner(runs).scan()
    if skipped or len(found) != 1:
        raise RuntimeError(f"Unexpected fixture scan: {skipped}")
    store.upsert(found[0])
    print(f"Offline fixture only, no Dream-1 request. Workspace: {root}")
    print(f"Review route: /#/runs?task={task.id}&run={found[0].id}")


if __name__ == "__main__":
    main()
