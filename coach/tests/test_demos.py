import json

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient
from test_trials import FakeStation

from teach_task_coach.api import create_app
from teach_task_coach.coverage import plan
from teach_task_coach.demos import DemoScanner, DemoStore, read_demo
from teach_task_coach.episodes import EpisodeSummary, RolloutScanner
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskInput, TaskStore, TrialInput


def make_demo(root, *, with_video=True):
    folder = root / "recorded-demo-001"
    (folder / "meta").mkdir(parents=True)
    (folder / "meta/info.json").write_text(
        json.dumps(
            {
                "codebase_version": "v2.1",
                "total_episodes": 1,
                "total_frames": 100,
                "fps": 20,
                "features": {
                    "observation.state": {"shape": [2]},
                    "action": {"shape": [2]},
                    "observation.images.overhead": {"shape": [3, 48, 64]},
                },
            }
        )
    )
    (folder / "meta/tasks.jsonl").write_text('{"task_index":0,"task":"put block in bin"}\n')
    data = folder / "data/chunk-000/episode_000000.parquet"
    data.parent.mkdir(parents=True)
    actions = [[0.0, 0.0]] * 60 + [[float(index) / 100, 0.0] for index in range(40)]
    pq.write_table(pa.table({"action": pa.array(actions)}), data)
    if with_video:
        video = folder / "videos/chunk-000/observation.images.overhead/episode_000000.mp4"
        video.parent.mkdir(parents=True)
        with av.open(str(video), 'w') as container:
            stream = container.add_stream('mpeg4', rate=20)
            stream.width, stream.height, stream.pix_fmt = 64, 48, 'yuv420p'
            pattern = np.arange(48*64, dtype=np.uint16).reshape(48,64)
            for i in range(100):
                frame = av.VideoFrame.from_ndarray(((pattern + 3*i) % 256).astype('uint8'), format='gray')
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
    return folder


def test_conversion_marker_preserves_offline_origin_without_rollout_sidecar(tmp_path):
    folder = make_demo(tmp_path)
    (folder / "meta/conversion.json").write_text(json.dumps({"origin": "offline_fixture"}))
    demo = read_demo(folder, "task-id")
    assert demo.origin == "offline_fixture"
    assert demo not in DemoStore(tmp_path / "data").training_eligible("task-id")


def test_demo_qc_flags_idle_start_and_missing_video(tmp_path):
    folder = make_demo(tmp_path)
    demo = read_demo(folder, "task-id")
    assert demo.valid
    assert {finding.code for finding in demo.findings} == {"idle_start"}

    (folder / "videos/chunk-000/observation.images.overhead/episode_000000.mp4").unlink()
    demo = read_demo(folder, "task-id")
    assert not demo.valid
    assert "missing_video" in {finding.code for finding in demo.findings}


def test_demo_qc_flags_dark_camera_and_abrupt_action(tmp_path):
    folder = make_demo(tmp_path)
    video = folder / "videos/chunk-000/observation.images.overhead/episode_000000.mp4"
    with av.open(str(video), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=20)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        for _ in range(80):
            frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), dtype=np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    actions = [[index * 0.01, 0.0] for index in range(100)]
    actions[50] = [10.0, 0.0]
    pq.write_table(pa.table({"action": pa.array(actions)}), folder / "data/chunk-000/episode_000000.parquet")
    demo = read_demo(folder, "task-id")
    assert {finding.code for finding in demo.findings} == {"possible_occlusion", "frozen_camera", "abrupt_action", "video_frames"}
    assert not demo.valid


def test_demo_import_review_and_coverage_plan(tmp_path):
    source = tmp_path / "demos"
    source.mkdir()
    make_demo(source)
    task_store = TaskStore(tmp_path / "data")
    task = task_store.create_task(
        TaskInput(
            name="Block to bin",
            prompt="put block in bin",
            baseline_checkpoint="dreamlabs/dream-1-beta",
            success_rule="in bin",
        )
    )
    episode_store = EpisodeStore(tmp_path / "data")
    demo_store = DemoStore(tmp_path / "data")
    client = TestClient(
        create_app(
            PreflightService(FakeStation(), list),
            episode_store,
            RolloutScanner(tmp_path),
            task_store,
            demo_store=demo_store,
            demo_scanner=DemoScanner(source),
        )
    )

    assert client.post(f"/api/tasks/{task.id}/demos/import").json()["imported"] == 1
    demo_id = client.get(f"/api/tasks/{task.id}/demos").json()[0]["id"]
    assert client.get(f"/api/demos/{demo_id}/video/overhead").content[4:8] == b'ftyp'
    assert client.post(f"/api/demos/{demo_id}/decision", json={"decision": "keep"}).status_code == 422

    trial = task_store.create_trial(task.id, TrialInput(start_cell=4))
    episode = EpisodeSummary(
        id="baseline-episode",
        source_path=str(tmp_path / "baseline"),
        status="complete",
        task=task.prompt,
        checkpoint=task.baseline_checkpoint,
        body="yam",
        robot_name="pilot",
        started_at_utc=None,
        frames=100,
        fps=20,
        duration_s=5,
        stop_reason="stopped",
        error=None,
        stalls=0,
        clamps=0,
        videos={},
        findings=[],
        events=[],
    )
    episode_store.upsert(episode)
    episode_store.label(episode.id, False, "grasp", "missed")
    task_store.transition(trial.id, "planned", "starting")
    task_store.transition(trial.id, "starting", "running")
    task_store.transition(trial.id, "running", "awaiting_rollout")
    task_store.transition(trial.id, "awaiting_rollout", "awaiting_label", episode_id=episode.id)
    task_store.transition(trial.id, "awaiting_label", "completed")

    plan_before = plan(task.id, task_store, episode_store, demo_store)
    assert plan_before.next_cell == 4
    assert plan_before.cells[4].baseline_failures == 1

    kept = client.post(
        f"/api/demos/{demo_id}/decision",
        json={"decision": "keep", "start_cell": 4, "note": "clean grasp"},
    )
    assert kept.status_code == 200
    assert kept.json()["decision"] == "keep"
    assert client.get(f"/api/tasks/{task.id}/demo-plan").json()["observed_failure_cells_covered"]
    assert DemoStore(tmp_path / "data").get(demo_id).note == "clean grasp"
    client.post(f"/api/tasks/{task.id}/demos/import")
    assert demo_store.get(demo_id).decision == "keep"
