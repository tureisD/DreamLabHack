import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient
from test_faas import setup_dataset
from test_trials import FakeStation

from teach_task_coach.api import create_app
from teach_task_coach.episodes import EpisodeSummary, Finding, RolloutScanner
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TrialInput


def test_guidance_moves_from_baseline_to_covered_pilot(tmp_path):
    tasks, task, demos, faas = setup_dataset(tmp_path)
    episodes = EpisodeStore(tmp_path / "data")
    trial = tasks.create_trial(task.id, TrialInput(start_cell=4))
    client = TestClient(create_app(
        PreflightService(FakeStation(), list), episodes, RolloutScanner(tmp_path), tasks,
        demo_store=demos, faas_store=faas,
    ))
    route = f"/api/tasks/{task.id}/guidance"
    baseline = client.get(route).json()
    assert baseline["phase"] == "baseline"
    assert baseline["pilot_ready"] is False

    episode = EpisodeSummary(
        id="failure", source_path="/test/failure", status="complete",
        task=task.prompt, checkpoint="base", body=None, robot_name=None,
        started_at_utc=None, frames=100, fps=20, duration_s=5,
        stop_reason="stopped", error=None, stalls=None, clamps=None,
        videos={}, findings=[], events=[], success=False,
    )
    episodes.upsert(episode)
    episodes.label(episode.id, False, "grasp", "missed")
    tasks.transition(trial.id, "planned", "completed", episode_id=episode.id)
    ready = client.get(route).json()
    assert ready["phase"] == "fix"
    assert ready["target_screen"] == "repair"
    assert ready["pilot_ready"] is False
    diagnosis = client.get(f"/api/tasks/{task.id}/diagnosis").json()
    assert diagnosis["data_count"] == 1
    assert diagnosis["failure_stages"] == {"grasp": 1}

    episode.findings = [Finding(
        kind="safety_stop", severity="problem", message="Safety stop at wrist.", evidence="rollout.json"
    )]
    episodes.upsert(episode)
    blocked = client.get(route).json()
    assert blocked["phase"] == "fix"
    assert "Safety stop at wrist." in blocked["evidence"]
    diagnosis = client.get(f"/api/tasks/{task.id}/diagnosis").json()
    assert diagnosis["setup_count"] == 1
    assert diagnosis["data_count"] == 0


def test_guidance_names_uncovered_failure_cell(tmp_path):
    tasks, task, demos, faas = setup_dataset(tmp_path)
    episodes = EpisodeStore(tmp_path / "data")
    trial = tasks.create_trial(task.id, TrialInput(start_cell=2))
    episode = EpisodeSummary(
        id="failure2", source_path="/test/failure2", status="complete",
        task=task.prompt, checkpoint="base", body=None, robot_name=None,
        started_at_utc=None, frames=100, fps=20, duration_s=5,
        stop_reason="stopped", error=None, stalls=None, clamps=None,
        videos={}, findings=[], events=[], success=False,
    )
    episodes.upsert(episode)
    episodes.label(episode.id, False, "grasp", None)
    tasks.transition(trial.id, "planned", "completed", episode_id=episode.id)
    client = TestClient(create_app(
        PreflightService(FakeStation(), list), episodes, RolloutScanner(tmp_path), tasks,
        demo_store=demos, faas_store=faas,
    ))
    result = client.get(f"/api/tasks/{task.id}/guidance").json()
    assert result["phase"] == "fix"
    assert result["target_screen"] == "repair"
    assert result["pilot_ready"] is False


def test_diagnosis_marks_noninitiating_failed_run(tmp_path):
    tasks, task, demos, faas = setup_dataset(tmp_path)
    episodes = EpisodeStore(tmp_path / "data")
    trial = tasks.create_trial(task.id, TrialInput(start_cell=1))
    folder = tmp_path / "stalled_run"
    (folder / "data").mkdir(parents=True)
    pq.write_table(pa.table({"observation.state": pa.array([[0.0, 0.0]] * 10)}), folder / "data/episode.parquet")
    episode = EpisodeSummary(
        id="never_moved", source_path=str(folder), status="complete", task=task.prompt,
        checkpoint="base", body=None, robot_name=None, started_at_utc=None,
        frames=10, fps=20, duration_s=0.5, stop_reason="stopped", error=None,
        stalls=None, clamps=None, videos={}, findings=[], events=[], success=False,
    )
    episodes.upsert(episode)
    episodes.label(episode.id, False, None, None)
    tasks.transition(trial.id, "planned", "completed", episode_id=episode.id)
    client = TestClient(create_app(
        PreflightService(FakeStation(), list), episodes, RolloutScanner(tmp_path), tasks,
        demo_store=demos, faas_store=faas,
    ))
    run = client.get(f"/api/tasks/{task.id}/diagnosis").json()["runs"][0]
    assert run["initiated"] is False
    assert "never left" in run["reason"]
