import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from dream import DreamClient
from dream.datasets import Report
from fastapi.testclient import TestClient
from test_demos import make_demo
from test_trials import FakeStation

from teach_task_coach.api import create_app
from teach_task_coach.demos import DemoStore, read_demo
from teach_task_coach.episodes import RolloutScanner
from teach_task_coach.faas import FaaSStore, FaaSWorker, FineTuneRequest, exclusive_worker_lock
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore


class FakeDream:
    def __init__(self):
        self.body = SimpleNamespace(
            name="pilot/robot", id="emb_1", embodiment_config={"state": {}, "action": {}, "video": {"overhead": "observation.images.overhead"}}
        )
        self.remote_dataset = None
        self.remote_job = None
        self.upload_calls = 0
        self.submit_calls = 0

    def embodiments(self):
        return [self.body]

    def validate(self, _path, _config):
        return Report(ok=True, sessions=1, episodes=1, frames=100)

    def datasets(self):
        return [] if self.remote_dataset is None else [self.remote_dataset]

    def upload(self, _path, name, embodiment):
        self.upload_calls += 1
        self.remote_dataset = SimpleNamespace(
            id="ds_1", name=f"pilot/{name}", embodiment=embodiment, status="ready_to_process", error=None
        )
        return self.remote_dataset

    def dataset_status(self, _id):
        return SimpleNamespace(status="processed", error=None)

    def finetunes(self):
        return [] if self.remote_job is None else [self.remote_job]

    def submit(self, _dataset, suffix, _settings):
        self.submit_calls += 1
        self.remote_job = {"id": "ftj_1", "suffix": suffix, "status": "queued"}
        return self.remote_job

    def finetune_status(self, _id):
        return {"status": "succeeded", "fine_tuned_model": "dream-1-ft:pilot-test"}


def setup_dataset(tmp_path):
    task_store = TaskStore(tmp_path / "data")
    task = task_store.create_task(
        TaskInput(name="Block", prompt="put block in bin", baseline_checkpoint="base", success_rule="in bin")
    )
    source = tmp_path / "source"
    source.mkdir()
    demo = read_demo(make_demo(source), task.id)
    demo_store = DemoStore(tmp_path / "data")
    demo_store.upsert(demo)
    demo_store.decide(demo.id, "keep", 4, None)
    faas_store = FaaSStore(tmp_path / "data")
    return task_store, task, demo_store, faas_store


def test_worker_validates_uploads_and_publishes_checkpoint(tmp_path):
    tasks, task, demos, store = setup_dataset(tmp_path)
    dream = FakeDream()
    client = TestClient(
        create_app(
            PreflightService(FakeStation(), list), EpisodeStore(tmp_path / "data"),
            RolloutScanner(tmp_path), tasks, demo_store=demos, faas_store=store, dream_gateway=dream,
        )
    )
    version_response = client.post(
        f"/api/tasks/{task.id}/datasets", json={"embodiment_name": "pilot/robot"}
    )
    assert version_response.status_code == 201
    version_id = version_response.json()["id"]
    worker = FaaSWorker(store, tasks, demos, dream)
    worker.tick()
    assert store.get_dataset(version_id).status == "validated"
    assert store.get_dataset(version_id).validation_report["episodes"] == 1

    job_response = client.post(
        f"/api/datasets/{version_id}/finetunes", json=FineTuneRequest().model_dump()
    )
    assert job_response.status_code == 201
    assert client.post(f"/api/datasets/{version_id}/finetunes", json={}).status_code == 409
    job_id = job_response.json()["id"]

    worker.tick()
    assert store.get_finetune(job_id).status == "processing"
    worker.tick()
    assert store.get_finetune(job_id).status == "pending_training"
    worker.tick()
    assert store.get_finetune(job_id).status == "training"
    worker.tick()
    assert store.get_finetune(job_id).checkpoint == "dream-1-ft:pilot-test"
    assert store.get_finetune(job_id).status == "succeeded"
    assert dream.upload_calls == 1
    assert dream.submit_calls == 1


def test_worker_reconciles_existing_remote_dataset_and_job(tmp_path):
    tasks, task, demos, store = setup_dataset(tmp_path)
    dream = FakeDream()
    version = store.create_dataset(task.id, "pilot/robot", [demo.id for demo in demos.list(task.id)])
    worker = FaaSWorker(store, tasks, demos, dream)
    worker.tick()
    job = store.create_finetune(version.id, FineTuneRequest())
    dream.remote_dataset = SimpleNamespace(
        id="ds_existing", name=f"pilot/{version.remote_slug}", embodiment="pilot/robot", status="processed", error=None
    )
    worker.tick()
    assert dream.upload_calls == 0
    worker.tick()
    dream.remote_job = {"id": "ftj_existing", "suffix": job.suffix, "status": "queued"}
    worker.tick()
    assert dream.submit_calls == 0
    assert store.get_finetune(job.id).remote_job_id == "ftj_existing"


def test_copied_dataset_passes_real_dream_client_validation(tmp_path):
    """The worker's directory layout is accepted by the SDK used for the real upload."""
    config = {
        "state": {"right_arm": [0, 6], "right_gripper": [6, 7], "left_arm": [7, 13], "left_gripper": [13, 14]},
        "action": {"right_arm": [0, 6], "right_gripper": [6, 7], "left_arm": [7, 13], "left_gripper": [13, 14]},
        "video": {role: f"observation.images.{role}" for role in ("overhead", "wrist_l", "wrist_r")},
    }
    task_store = TaskStore(tmp_path / "data")
    task = task_store.create_task(
        TaskInput(name="Fold", prompt="fold", baseline_checkpoint="base", success_rule="folded")
    )
    folder = tmp_path / "source" / "session"
    (folder / "meta").mkdir(parents=True)
    frames, dim = 49, 14
    vector = np.arange(frames * dim, dtype=np.float32).reshape(frames, dim)
    offsets = pa.array(np.arange(0, vector.size + 1, dim, dtype=np.int32))
    column = pa.ListArray.from_arrays(offsets, pa.array(vector.reshape(-1)))
    table = pa.table(
        {
            "action": column,
            "observation.state": column,
            "timestamp": np.arange(frames) / 30,
            "episode_index": np.zeros(frames, dtype=np.int64),
        }
    )
    data_file = folder / "data/chunk-000/episode_000000.parquet"
    data_file.parent.mkdir(parents=True)
    pq.write_table(table, data_file)
    feature = {"dtype": "float32", "shape": [dim], "names": [f"joint_{index}" for index in range(dim - 1)] + ["gripper"]}
    video_feature = {"dtype": "video", "shape": [48, 64, 3], "names": ["height", "width", "channels"]}
    info = {
        "codebase_version": "v2.1", "total_episodes": 1, "total_frames": frames, "fps": 30,
        "chunks_size": 1000,
        "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
        "features": {"action": feature, "observation.state": feature}
        | {f"observation.images.{role}": video_feature for role in ("overhead", "wrist_l", "wrist_r")},
    }
    (folder / "meta/info.json").write_text(json.dumps(info))
    (folder / "meta/tasks.jsonl").write_text('{"task_index":0,"task":"fold"}\n')
    (folder / "meta/episodes.jsonl").write_text('{"episode_index":0,"tasks":["fold"],"length":49}\n')
    sample_video = (Path(__file__).resolve().parents[2] / "dream_library/dream_client/tests/fixtures/avc1.mp4").read_bytes()
    for role in ("overhead", "wrist_l", "wrist_r"):
        path = folder / f"videos/chunk-000/observation.images.{role}/episode_000000.mp4"
        path.parent.mkdir(parents=True)
        path.write_bytes(sample_video)

    demo_store = DemoStore(tmp_path / "data")
    demo = read_demo(folder, task.id)
    assert demo.valid
    demo_store.upsert(demo)
    demo_store.decide(demo.id, "keep", 0, None)
    store = FaaSStore(tmp_path / "data")
    version = store.create_dataset(task.id, "pilot/robot", [demo.id])
    dream = FakeDream()
    dream.body.embodiment_config = config
    dream.validate = lambda path, body_config: DreamClient().validate_dataset(path, body_config)

    FaaSWorker(store, task_store, demo_store, dream).tick()

    assert store.get_dataset(version.id).status == "validated"


def test_second_worker_cannot_claim_same_data_directory(tmp_path):
    lock = tmp_path / "worker.lock"
    with (
        exclusive_worker_lock(lock),
        pytest.raises(RuntimeError, match="already running"),
        exclusive_worker_lock(lock),
    ):
        pass


def test_resume_settings_persist_and_api_rejects_unevaluated_parent(tmp_path):
    tasks, task, demos, store = setup_dataset(tmp_path)
    version = store.create_dataset(task.id, "pilot/robot", [demo.id for demo in demos.list(task.id)])
    store.update_dataset(version.id, status="validated")
    parent = store.create_finetune(version.id, FineTuneRequest(steps=500, lr_schedule="constant"))
    store.update_finetune(parent.id, status="succeeded", checkpoint="dream-1-ft:pilot-parent")
    client = TestClient(create_app(
        PreflightService(FakeStation(), list), EpisodeStore(tmp_path / "data"),
        RolloutScanner(tmp_path), tasks, demo_store=demos, faas_store=store,
    ))
    request = FineTuneRequest(
        steps=500, lr_schedule="constant", resume_from="dream-1-ft:pilot-parent"
    )
    response = client.post(f"/api/datasets/{version.id}/finetunes", json=request.model_dump())
    assert response.status_code == 409
    assert "evaluation" in response.json()["detail"]
    saved = store.create_finetune(version.id, request)
    assert store.get_finetune(saved.id).resume_from == "dream-1-ft:pilot-parent"
