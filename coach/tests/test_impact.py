from fastapi.testclient import TestClient

from teach_task_coach.api import create_app
from teach_task_coach.demos import DemoStore
from teach_task_coach.evaluation import EvaluationStore
from teach_task_coach.faas import FaaSStore
from teach_task_coach.impact import footprint
from teach_task_coach.repair import RepairRequest, RepairStore
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore


def test_local_footprint_counts_actual_repair_trials_and_not_unsubmitted_faas(tmp_path):
    tasks = TaskStore(tmp_path)
    demos = DemoStore(tmp_path)
    faas = FaaSStore(tmp_path)
    evaluations = EvaluationStore(tmp_path)
    episodes = EpisodeStore(tmp_path)
    repairs = RepairStore(tmp_path)
    task = tasks.create_task(TaskInput(
        name="Apple", prompt="pick up the apple", baseline_checkpoint="base",
        success_rule="Apple held for two seconds",
    ))
    initial = footprint(task.id, tasks, demos, faas, evaluations, episodes, repairs)
    assert initial.baseline_trials == 0
    assert initial.faas_steps_submitted == 0
    repairs.create(task.id, RepairRequest(kind="prompt", candidate_prompt="lift the apple",
                                          planned_pairs=4), tasks)
    after = footprint(task.id, tasks, demos, faas, evaluations, episodes, repairs)
    assert after.repair_trials == 8
    assert after.validated_improvements == 0
    assert any("not establish savings" in note for note in after.notes)
    client = TestClient(create_app(task_store=tasks, demo_store=demos, faas_store=faas,
                                   evaluation_store=evaluations, store=episodes, repair_store=repairs))
    response = client.get(f"/api/tasks/{task.id}/footprint")
    assert response.status_code == 200
    assert response.json()["repair_trials"] == 8
    assert client.get("/api/tasks/missing/footprint").status_code == 404
