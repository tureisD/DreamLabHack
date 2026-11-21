from fastapi.testclient import TestClient
from test_trials import FakeStation

from teach_task_coach.api import create_app
from teach_task_coach.episodes import EpisodeSummary, RolloutScanner
from teach_task_coach.evaluation import EvaluationStore
from teach_task_coach.faas import FaaSStore, FineTuneRequest
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore


def setup_comparison(tmp_path):
    data_dir = tmp_path / "data"
    tasks = TaskStore(data_dir)
    task = tasks.create_task(TaskInput(
        name="Block", prompt="put block in bin", baseline_checkpoint="base", success_rule="in bin"
    ))
    faas = FaaSStore(data_dir)
    dataset = faas.create_dataset(task.id, "pilot/robot", [])
    job = faas.create_finetune(dataset.id, FineTuneRequest())
    faas.update_finetune(job.id, status="succeeded", checkpoint="candidate")
    station = FakeStation()
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    episodes = EpisodeStore(data_dir)
    evaluations = EvaluationStore(data_dir)
    client = TestClient(create_app(
        PreflightService(station, list), episodes, RolloutScanner(rollouts), tasks,
        faas_store=faas, evaluation_store=evaluations,
    ))
    return client, tasks, episodes, evaluations, task, job, station


def test_predeclared_scenes_are_paired_and_trial_order_is_enforced(tmp_path):
    client, tasks, _episodes, _evaluations, task, job, station = setup_comparison(tmp_path)
    scenes = tasks.heldout_scenes(task.id)
    assert len(scenes) == 30
    assert [scene.start_cell for scene in scenes] == [index % 9 for index in range(30)]

    response = client.post(
        f"/api/tasks/{task.id}/evaluations",
        json={"fine_tune_job_id": job.id, "minimum_effect": 0.15},
    )
    assert response.status_code == 201
    evaluation = response.json()
    trials = client.get(f"/api/evaluations/{evaluation['id']}/trials").json()
    assert len(trials) == 60
    assert len({trial["scene_index"] for trial in trials}) == 30
    assert sum(trials[index]["checkpoint"] == "candidate" for index in range(0, 60, 2)) == 15
    for index in range(0, 60, 2):
        assert trials[index]["scene_index"] == trials[index + 1]["scene_index"]
        assert {trials[index]["checkpoint"], trials[index + 1]["checkpoint"]} == {"base", "candidate"}
        assert trials[index]["start_cell"] == scenes[trials[index]["scene_index"]].start_cell
    assert client.post(f"/api/trials/{trials[1]['id']}/start").status_code == 409
    assert client.post(f"/api/trials/{trials[0]['id']}/start").status_code == 200
    assert station.checkpoint == trials[0]["checkpoint"]
    assert client.post(f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}).status_code == 409


def test_evaluation_refuses_unfinished_or_other_tasks_jobs(tmp_path):
    client, tasks, _episodes, _evaluations, task, job, _station = setup_comparison(tmp_path)
    other = tasks.create_task(TaskInput(
        name="Other", prompt="pick cup", baseline_checkpoint="base", success_rule="cup held"
    ))
    assert client.post(
        f"/api/tasks/{other.id}/evaluations", json={"fine_tune_job_id": job.id}
    ).status_code == 409
    assert client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": "missing"}
    ).status_code == 404


def test_unusable_trial_allows_new_comparison_but_blocks_old_sequence(tmp_path):
    client, tasks, _episodes, _evaluations, task, job, _station = setup_comparison(tmp_path)
    first = client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}
    ).json()
    trials = tasks.list_evaluation_trials(first["id"])
    assert client.post(f"/api/trials/{trials[0].id}/start").status_code == 200
    assert client.post(f"/api/trials/{trials[0].id}/stop").status_code == 200
    assert client.post(
        f"/api/trials/{trials[0].id}/abandon", json={"reason": "camera recording lost"}
    ).status_code == 200
    assert client.post(f"/api/trials/{trials[1].id}/start").status_code == 409
    second = client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}
    )
    assert second.status_code == 201
    assert second.json()["id"] != first["id"]
    assert client.post(f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}).status_code == 409


def populate_report(tasks, episodes, evaluation, base_results, candidate_results):
    for trial in tasks.list_evaluation_trials(evaluation.id):
        success = (candidate_results if trial.checkpoint == "candidate" else base_results)[trial.scene_index]
        episode = EpisodeSummary(
            id=trial.id, source_path=f"/test/{trial.id}", status="complete",
            task="put block in bin", checkpoint=trial.checkpoint,
            body=None, robot_name=None, started_at_utc=None, frames=100, fps=20,
            duration_s=5, stop_reason="stopped", error=None, stalls=None, clamps=None,
            videos={}, findings=[], events=[], success=success,
        )
        episodes.upsert(episode)
        episodes.label(episode.id, success, None, None)
        tasks.transition(trial.id, "planned", "completed", episode_id=episode.id)


def test_paired_report_distinguishes_improvement_and_inconclusive_result(tmp_path):
    client, tasks, episodes, evaluations, task, job, _station = setup_comparison(tmp_path)
    created = client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}
    ).json()
    evaluation = evaluations.get(created["id"])
    assert evaluation is not None
    assert client.get(f"/api/evaluations/{evaluation.id}/report").json()["decision"] == "inconclusive"
    populate_report(tasks, episodes, evaluation, [False] * 30, [True] * 24 + [False] * 6)
    report = client.get(f"/api/evaluations/{evaluation.id}/report").json()
    assert report["usable_pairs"] == 30
    assert report["baseline_successes"] == 0
    assert report["candidate_successes"] == 24
    assert report["decision"] == "improved"
    assert report["ci_low"] > 0
    assert report["exact_p_value"] < 0.05

    for trial in tasks.list_evaluation_trials(evaluation.id):
        success = trial.scene_index < (15 if trial.checkpoint == "candidate" else 12)
        episodes.label(trial.episode_id, success, None, None)
    report = client.get(f"/api/evaluations/{evaluation.id}/report").json()
    assert report["decision"] == "inconclusive"
    assert report["candidate_successes"] == 15
    assert report["baseline_successes"] == 12

    for trial in tasks.list_evaluation_trials(evaluation.id):
        success = trial.checkpoint == "base" and trial.scene_index < 20
        episodes.label(trial.episode_id, success, None, None)
    report = client.get(f"/api/evaluations/{evaluation.id}/report").json()
    assert report["decision"] == "worse"


def test_verified_candidate_promotes_future_runs_and_can_roll_back(tmp_path):
    client, tasks, episodes, evaluations, task, job, _station = setup_comparison(tmp_path)
    created = client.post(
        f"/api/tasks/{task.id}/evaluations",
        json={"fine_tune_job_id": job.id, "auto_promote": True},
    ).json()
    evaluation = evaluations.get(created["id"])
    assert evaluation is not None
    assert client.post(f"/api/evaluations/{evaluation.id}/promote").status_code == 409
    populate_report(tasks, episodes, evaluation, [False] * 30, [True] * 24 + [False] * 6)
    assert client.post(f"/api/evaluations/{evaluation.id}/promote").json()["checkpoint"] == "candidate"
    deployed = client.post(
        f"/api/tasks/{task.id}/deployed-trials", json={"start_cell": 2}
    ).json()
    assert deployed["checkpoint"] == "candidate"
    assert deployed["purpose"] == "deployed"
    assert client.get(f"/api/tasks/{task.id}/baseline-trials").json() == []
    assert len(client.get(f"/api/tasks/{task.id}/deployed-trials").json()) == 1
    assert client.post(f"/api/tasks/{task.id}/deployment/rollback").json()["checkpoint"] == "base"


def test_configured_fixture_places_scene_before_evaluation_start(tmp_path):
    client, tasks, episodes, evaluations, task, job, station = setup_comparison(tmp_path)
    evaluation = client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}
    ).json()
    trial = tasks.list_evaluation_trials(evaluation["id"])[0]

    class Fixture:
        configured = True

        def __init__(self):
            self.scenes = []

        def place(self, scene):
            self.scenes.append(scene)
            return {"placed": True, "detail": "placed"}

    fixture = Fixture()
    local = TestClient(create_app(
        PreflightService(station, list), episodes, RolloutScanner(tmp_path / "rollouts"),
        tasks, evaluation_store=evaluations, scene_adapter=fixture,
    ))
    assert local.post(f"/api/trials/{trial.id}/start").status_code == 200
    assert fixture.scenes[0].scene_index == trial.scene_index
    assert local.post(f"/api/trials/{trial.id}/start").status_code == 409
    assert len(fixture.scenes) == 1
