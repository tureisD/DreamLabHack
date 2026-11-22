"""Exercise the robot-free collector with a synthetic failed control trace."""

import json
import sys
from pathlib import Path

from teach_task_coach.demos import read_demo

SIM = Path(__file__).parents[1] / "experiments/yam_sim_faas"
sys.path.insert(0, str(SIM))
from collect_failure_demos import collect, eligible_failures, select_diverse
from record_yam_demos import TASK, recording


def test_failure_conditioned_collection_exports_reviewable_dream_dataset(tmp_path):
    model_root = tmp_path / "model"
    with recording(model_root, TASK, "dreamlabs/dream-1-beta", 1201, "model",
                   start_pose="wrist-visible", videos=False) as (env, details):
        left = env.state()["left"]
        right = env.state()["right"]
        for _ in range(100):
            env.step(left, right)
        details["model_action_rows"] = 67
    failures = eligible_failures(model_root)
    assert len(failures) == 1
    assert failures[0]["failure_kind"] == "never_closed"
    assert select_diverse(failures, 1)[0]["seed"] == 1201

    output = tmp_path / "demos"
    result = collect(model_root, output, max_demos=1)
    assert result["selected_demos"] == 1
    assert result["sessions"][0]["export_replay_held_lift_m"] >= 0.08
    demo = read_demo(output / "yam-failure-seed-1201", "test-task")
    assert demo.valid
    assert demo.task_text == TASK
    assert demo.frames > 100
    assert json.loads(Path(result["manifest"]).read_text())["sessions"][0]["failure_kind"] == "never_closed"


def test_selection_covers_distinct_failure_modes_first():
    rows = [
        {"seed": 1, "failure_kind": "early_close", "held_lift_m": 0.0, "apple_xy_m": [0, 0]},
        {"seed": 2, "failure_kind": "early_close", "held_lift_m": 0.0, "apple_xy_m": [1, 1]},
        {"seed": 3, "failure_kind": "never_closed", "held_lift_m": 0.0, "apple_xy_m": [0, 0]},
    ]
    assert {row["failure_kind"] for row in select_diverse(rows, 2)} == {"early_close", "never_closed"}
