"""Exercise the robot-free collector with a synthetic failed control trace."""

import json
import sys
from pathlib import Path

import pytest
from dream import DreamClient
from fastapi.testclient import TestClient
from test_faas import FakeDream

from teach_task_coach.api import create_app
from teach_task_coach.demos import DemoStore, read_demo
from teach_task_coach.evaluation import EvaluationStore
from teach_task_coach.faas import FaaSStore, FaaSWorker, FineTuneRequest
from teach_task_coach.impact import footprint
from teach_task_coach.repair import RepairStore
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore

SIM = Path(__file__).parents[1] / "experiments/yam_sim_faas"
sys.path.insert(0, str(SIM))
from collect_failure_demos import collect, eligible_failures, select_diverse
from record_yam_demos import CONFIG, TASK, recording
from score_rollouts import score


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
    assert len(result["sessions"][0]["demo_sha256"]) == 64
    demo = read_demo(output / "yam-failure-seed-1201", "test-task")
    assert demo.valid
    assert demo.task_text == TASK
    assert demo.frames > 100
    assert json.loads(Path(result["manifest"]).read_text())["sessions"][0]["failure_kind"] == "never_closed"

    # Exercise the same coach stores, real Dream dataset validator, and worker
    # transitions used by the UI. Dream upload/training is deliberately faked.
    data_dir = tmp_path / "coach"
    tasks = TaskStore(data_dir)
    task = tasks.create_task(TaskInput(name="Apple", prompt=TASK,
                                       baseline_checkpoint="dreamlabs/dream-1-beta",
                                       success_rule="Hold apple 8 cm above rest for 2 seconds"))
    demos = DemoStore(data_dir)
    imported = read_demo(output / "yam-failure-seed-1201", task.id)
    demos.upsert(imported)
    demos.decide(imported.id, "keep", 0, "Reviewed synthetic failure correction")
    faas = FaaSStore(data_dir)
    gateway = FakeDream()
    gateway.body.embodiment_config = CONFIG
    gateway.validate = lambda path, config: DreamClient().validate_dataset(path, config)
    version = faas.create_dataset(task.id, gateway.body.name, [imported.id])
    worker = FaaSWorker(faas, tasks, demos, gateway)
    worker.tick()
    assert faas.get_dataset(version.id).status == "validated"
    job = faas.create_finetune(version.id, FineTuneRequest(steps=500, lr_schedule="constant"))
    for _ in range(4):
        worker.tick()
    assert faas.get_finetune(job.id).status == "succeeded"
    assert gateway.upload_calls == gateway.submit_calls == 1
    usage = footprint(task.id, tasks, demos, faas, EvaluationStore(data_dir),
                      EpisodeStore(data_dir), RepairStore(data_dir))
    assert usage.demos_kept == usage.faas_jobs_submitted == 1
    assert usage.faas_steps_submitted == 500

    # The saved second-account simulator comparison was produced by a real
    # completed FaaS job; analyze it separately from the fake worker job above.
    api = TestClient(create_app())
    snapshot = api.get("/api/paired-evaluations/demo/second-account")
    assert snapshot.status_code == 200
    paired = api.post("/api/paired-evaluations/analyze", json=snapshot.json())
    assert paired.status_code == 200
    assert paired.json()["decision"] == "descriptive"
    assert (paired.json()["baseline_successes"], paired.json()["candidate_successes"]) == (0, 4)


def test_selection_covers_distinct_failure_modes_first():
    rows = [
        {"seed": 1, "failure_kind": "early_close", "held_lift_m": 0.0, "apple_xy_m": [0, 0]},
        {"seed": 2, "failure_kind": "early_close", "held_lift_m": 0.0, "apple_xy_m": [1, 1]},
        {"seed": 3, "failure_kind": "never_closed", "held_lift_m": 0.0, "apple_xy_m": [0, 0]},
    ]
    assert {row["failure_kind"] for row in select_diverse(rows, 2)} == {"early_close", "never_closed"}


@pytest.mark.parametrize(
    ("seed", "split"), [(913, None), (940, None), (2**31 + 9, "heldout")],
)
def test_collector_rejects_published_and_tagged_evaluation_rollouts(tmp_path, seed, split):
    (tmp_path / "rollout.json").write_text(json.dumps({
        "status": "complete", "task": TASK, "simulation": {
            "source": "model", "seed": seed, "start_pose": "wrist-visible", "split": split,
        },
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="not an eligible complete model rollout"):
        score(tmp_path, training_candidate=True)
