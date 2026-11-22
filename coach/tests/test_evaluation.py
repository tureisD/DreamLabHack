import datetime as dt
import json
from pathlib import Path

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


def test_partial_rollout_can_be_abandoned_and_comparison_restarted(tmp_path):
    client, tasks, _episodes, _evaluations, task, job, station = setup_comparison(tmp_path)
    first = client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}
    ).json()
    trial = tasks.list_evaluation_trials(first["id"])[0]
    assert client.post(f"/api/trials/{trial.id}/start").status_code == 200
    assert client.post(f"/api/trials/{trial.id}/stop").status_code == 200
    folder = tmp_path / "rollouts" / "partial_run1"
    folder.mkdir()
    (folder / "rollout.json").write_text(json.dumps({
        "status": "partial", "task": task.prompt, "checkpoint": trial.checkpoint,
        "run": station.run_number, "started_at_utc": "2026-11-21T10:00:05+00:00",
        "frames": 10, "fps": 20, "stop_reason": "stopped",
    }))
    synced = client.post(f"/api/trials/{trial.id}/sync")
    assert synced.status_code == 200
    assert synced.json()["status"] == "awaiting_rollout"
    assert "incomplete" in synced.json()["last_error"]
    assert client.post(f"/api/trials/{trial.id}/label", json={"success": False}).status_code == 409
    assert client.post(
        f"/api/trials/{trial.id}/abandon", json={"reason": "partial recording"}
    ).status_code == 200
    replacement = client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}
    )
    assert replacement.status_code == 201


def populate_report(tasks, episodes, evaluation, base_results, candidate_results, reviewed=False):
    started = (dt.datetime.fromisoformat(evaluation.created_at) + dt.timedelta(seconds=1)).isoformat()
    for trial in tasks.list_evaluation_trials(evaluation.id):
        success = (candidate_results if trial.checkpoint == "candidate" else base_results)[trial.scene_index]
        if success is None:
            continue
        folder = tasks.db.data_dir / "rollouts" / trial.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "rollout.json").write_text(json.dumps({
            "task": "put block in bin", "checkpoint": trial.checkpoint,
            "started_at_utc": started, "status": "complete",
        }), encoding="utf-8")
        episode = EpisodeSummary(
            id=trial.id, source_path=str(folder), status="complete",
            task="put block in bin", checkpoint=trial.checkpoint,
            body=None, robot_name=None, started_at_utc=started, frames=100, fps=20,
            duration_s=5, stop_reason="stopped", error=None, stalls=None, clamps=None,
            videos={}, findings=[], events=[], success=success,
        )
        episodes.upsert(episode)
        episodes.label(episode.id, success, None, None, "operator-1" if reviewed else None)
        tasks.transition(trial.id, "planned", "completed", episode_id=episode.id)


def test_paired_snapshot_preserves_incomplete_and_requires_review_provenance(tmp_path):
    client, tasks, episodes, evaluations, task, job, _station = setup_comparison(tmp_path)
    evaluation_id = client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}
    ).json()["id"]
    url = f"/api/evaluations/{evaluation_id}/paired-snapshot"
    assert client.post(url, json={"heldout_attested": False, "resets_attested": True}).status_code == 409
    attestation = {"heldout_attested": True, "resets_attested": True}
    empty = client.post(url, json=attestation)
    assert empty.status_code == 200
    assert client.post("/api/paired-evaluations/analyze", json=empty.json()).json()["decision"] == "not_evaluable"

    evaluation = evaluations.get(evaluation_id)
    assert evaluation is not None
    populate_report(tasks, episodes, evaluation, [False] * 30, [True] * 30)
    old = client.post(url, json=attestation)
    assert old.status_code == 200
    old_report = client.post("/api/paired-evaluations/analyze", json=old.json()).json()
    assert old_report["decision"] == "not_evaluable"
    assert any("reviewer" in problem for problem in old_report["problems"])

    started = (dt.datetime.fromisoformat(evaluation.created_at) + dt.timedelta(seconds=1)).isoformat()
    for trial in tasks.list_evaluation_trials(evaluation_id):
        episode = episodes.get(trial.episode_id)
        assert episode is not None
        episode.started_at_utc = started
        episodes.upsert(episode)
        episodes.label(episode.id, episode.success, None, None, "operator-1")
    ready = client.post(url, json=attestation)
    assert ready.status_code == 200
    report = client.post("/api/paired-evaluations/analyze", json=ready.json()).json()
    assert report["decision"] == "improved"
    assert report["usable_pairs"] == 30
    assert report["difference_interval"][0] > 0.15


def test_latest_evaluation_reflects_new_reviewed_trials_across_tasks(tmp_path):
    client, tasks, episodes, evaluations, task, job, _station = setup_comparison(tmp_path)
    url = "/api/evaluations/latest"
    assert client.get(url).json() is None

    evaluations.create(task.id, job.id, "candidate", 0.15, tasks, planned_pairs=1)
    other = tasks.create_task(TaskInput(
        name="Other block task", prompt=task.prompt, baseline_checkpoint="base", success_rule="in bin"
    ))
    latest = evaluations.create(other.id, "other-job", "candidate", 0.15, tasks, planned_pairs=1)
    pending = client.get(url).json()
    assert pending["task_name"] == other.name
    assert pending["evaluation"]["id"] == latest.id
    assert pending["report"]["baseline_reviewed"] == pending["report"]["candidate_reviewed"] == 0

    populate_report(tasks, episodes, latest, [None], [True], reviewed=True)
    partial = client.get(url).json()["report"]
    assert partial["baseline_reviewed"] == 0
    assert partial["candidate_reviewed"] == partial["candidate_successes"] == 1
    assert partial["usable_pairs"] == 0

    populate_report(tasks, episodes, latest, [False], [None], reviewed=True)
    updated = client.get(url).json()["report"]
    assert updated["baseline_reviewed"] == updated["candidate_reviewed"] == 1
    assert updated["usable_pairs"] == 1
    assert updated["baseline_successes"] == 0
    assert updated["candidate_successes"] == 1
    assert updated["decision"] == "not_evaluable"


def test_variable_scene_budget_and_paired_planner(tmp_path):
    client, tasks, _episodes, _evaluations, task, job, _station = setup_comparison(tmp_path)
    estimate = client.post("/api/paired-evaluations/plan", json={
        "expected_gain": 0.8, "minimum_improvement": 0.15,
        "max_pairs": 64, "minutes_per_pair": 12,
    })
    assert estimate.status_code == 200
    assert estimate.json()["feasible"]
    assert estimate.json()["recommended_pairs"] == 18
    created = client.post(f"/api/tasks/{task.id}/evaluations", json={
        "fine_tune_job_id": job.id, "planned_pairs": 40,
    })
    assert created.status_code == 201
    assert created.json()["planned_pairs"] == 40
    assert len(tasks.heldout_scenes(task.id)) == 40
    trials = client.get(f"/api/evaluations/{created.json()['id']}/trials").json()
    assert len(trials) == 80
    assert sum(trial["checkpoint"] == "candidate" for trial in trials[::2]) == 20
    assert client.post("/api/paired-evaluations/plan", json={
        "expected_gain": 0.4, "minimum_improvement": 0.15, "max_pairs": 40,
    }).json()["feasible"] is False


def test_saved_audit_invalidates_when_recorded_metadata_changes(tmp_path):
    client, tasks, episodes, evaluations, task, job, _station = setup_comparison(tmp_path)
    evaluation_id = client.post(f"/api/tasks/{task.id}/evaluations", json={
        "fine_tune_job_id": job.id,
    }).json()["id"]
    evaluation = evaluations.get(evaluation_id)
    assert evaluation is not None
    populate_report(tasks, episodes, evaluation, [False] * 30, [True] * 30, reviewed=True)
    assert client.post(f"/api/evaluations/{evaluation_id}/paired-snapshot", json={
        "heldout_attested": True, "resets_attested": True,
    }).status_code == 200
    assert client.get(f"/api/evaluations/{evaluation_id}/report").json()["decision"] == "improved"
    trial = tasks.list_evaluation_trials(evaluation_id)[0]
    episode = episodes.get(trial.episode_id)
    assert episode is not None
    (Path(episode.source_path) / "rollout.json").write_text("{\"changed\":true}", encoding="utf-8")
    report = client.get(f"/api/evaluations/{evaluation_id}/report").json()
    assert report["decision"] == "not_evaluable"
    assert client.post(f"/api/evaluations/{evaluation_id}/promote").status_code == 409
    assert client.post(f"/api/evaluations/{evaluation_id}/paired-snapshot", json={
        "heldout_attested": True, "resets_attested": True,
    }).status_code == 200
    rerun = client.get(f"/api/evaluations/{evaluation_id}/audit").json()
    assert rerun["decision"] == "not_evaluable"
    assert any("digest" in problem for problem in rerun["problems"])


def test_paired_report_distinguishes_improvement_and_inconclusive_result(tmp_path):
    client, tasks, episodes, evaluations, task, job, _station = setup_comparison(tmp_path)
    created = client.post(
        f"/api/tasks/{task.id}/evaluations", json={"fine_tune_job_id": job.id}
    ).json()
    evaluation = evaluations.get(created["id"])
    assert evaluation is not None
    assert client.get(f"/api/evaluations/{evaluation.id}/report").json()["decision"] == "not_evaluable"
    populate_report(tasks, episodes, evaluation, [False] * 30, [True] * 24 + [False] * 6,
                    reviewed=True)
    assert client.get(f"/api/evaluations/{evaluation.id}/report").json()["decision"] == "not_evaluable"
    assert client.post(f"/api/evaluations/{evaluation.id}/paired-snapshot", json={
        "heldout_attested": True, "resets_attested": True,
    }).status_code == 200
    report = client.get(f"/api/evaluations/{evaluation.id}/report").json()
    assert report["usable_pairs"] == 30
    assert report["baseline_successes"] == 0
    assert report["candidate_successes"] == 24
    assert report["decision"] == "improved"
    assert report["ci_low"] > 0
    assert report["exact_p_value"] is None

    for trial in tasks.list_evaluation_trials(evaluation.id):
        success = trial.scene_index < (15 if trial.checkpoint == "candidate" else 12)
        episodes.label(trial.episode_id, success, None, None, "operator-1")
    report = client.get(f"/api/evaluations/{evaluation.id}/report").json()
    assert report["decision"] == "not_evaluable"
    assert report["candidate_successes"] == 15
    assert report["baseline_successes"] == 12
    assert client.post(f"/api/evaluations/{evaluation.id}/paired-snapshot", json={
        "heldout_attested": True, "resets_attested": True,
    }).status_code == 200
    assert client.get(f"/api/evaluations/{evaluation.id}/report").json()["decision"] == "inconclusive"

    for trial in tasks.list_evaluation_trials(evaluation.id):
        success = trial.checkpoint == "base" and trial.scene_index < 20
        episodes.label(trial.episode_id, success, None, None, "operator-1")
    assert client.post(f"/api/evaluations/{evaluation.id}/paired-snapshot", json={
        "heldout_attested": True, "resets_attested": True,
    }).status_code == 200
    report = client.get(f"/api/evaluations/{evaluation.id}/report").json()
    assert report["decision"] == "worse"


def test_verified_candidate_promotes_future_runs_and_can_roll_back(tmp_path):
    client, tasks, episodes, evaluations, task, job, _station = setup_comparison(tmp_path)
    created = client.post(
        f"/api/tasks/{task.id}/evaluations",
        json={"fine_tune_job_id": job.id},
    ).json()
    evaluation = evaluations.get(created["id"])
    assert evaluation is not None
    assert client.post(f"/api/evaluations/{evaluation.id}/promote").status_code == 409
    populate_report(tasks, episodes, evaluation, [False] * 30, [True] * 24 + [False] * 6,
                    reviewed=True)
    assert client.post(f"/api/evaluations/{evaluation.id}/promote").status_code == 409
    assert client.post(f"/api/evaluations/{evaluation.id}/paired-snapshot", json={
        "heldout_attested": True, "resets_attested": True,
    }).status_code == 200
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
