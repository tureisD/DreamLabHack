import json

from fastapi.testclient import TestClient
from test_preflight import FakeStation, status

from teach_task_coach.api import create_app
from teach_task_coach.episodes import RolloutScanner, read_episode
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore


def make_rollout(root, *, recording=False):
    folder = root / "2026-11-21T10-00-00_run1"
    folder.mkdir(parents=True)
    (folder / "rollout.json").write_text(
        json.dumps(
            {
                "status": "recording" if recording else "complete",
                "task": "put block in bin",
                "checkpoint": "dreamlabs/dream-1-beta",
                "body": "yam",
                "robot_name": "pilot",
                "started_at_utc": "2026-11-21T10:00:00+00:00",
                "frames": 120,
                "fps": 20,
                "duration_s": 6,
                "stop_reason": "stopped",
                "stalls": 2,
                "clamps": 1,
            }
        )
    )
    (folder / "inference.jsonl").write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {"kind": "run_start", "t": "2026-11-21T10:00:00+00:00"},
                {"kind": "error", "t": "2026-11-21T10:00:02+00:00", "detail": "gateway retry", "action": "retry"},
                {"kind": "run_stop", "t": "2026-11-21T10:00:06+00:00"},
            )
        )
        + "\n"
    )
    video = folder / "videos/chunk-000/observation.images.overhead/episode_000000.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"sample video fixture")
    return folder


def test_scanner_reads_station_metadata_and_skips_live_recording(tmp_path):
    folder = make_rollout(tmp_path)
    episode = read_episode(folder)

    assert episode.task == "put block in bin"
    assert episode.videos["overhead"].endswith("episode_000000.mp4")
    assert episode.events[1].elapsed_s == 2
    assert {finding.kind for finding in episode.findings} == {"stalls", "clamps"}

    (folder / "rollout.json").write_text('{"status":"recording","task":"x","checkpoint":"y"}')
    imported, skipped = RolloutScanner(tmp_path).scan()
    assert imported == []
    assert "not finished" in skipped[0]


def test_import_label_and_video_route_persist(tmp_path):
    root = tmp_path / "rollouts"
    root.mkdir()
    make_rollout(root)
    store = EpisodeStore(tmp_path / "data")
    service = PreflightService(FakeStation(status()), list)
    client = TestClient(create_app(service, store, RolloutScanner(root)))

    imported = client.post("/api/rollouts/import")
    assert imported.status_code == 200
    assert imported.json()["imported"] == 1
    episode_id = client.get("/api/episodes").json()[0]["id"]

    label = client.post(
        f"/api/episodes/{episode_id}/label",
        json={"success": False, "failure_stage": "grasp", "note": "missed the block"},
    )
    assert label.status_code == 200
    assert label.json()["failure_stage"] == "grasp"
    assert EpisodeStore(tmp_path / "data").get(episode_id).note == "missed the block"
    assert client.get(f"/api/episodes/{episode_id}/video/overhead").content == b"sample video fixture"
    assert client.get(f"/api/episodes/{episode_id}/video/unknown").status_code == 404

    client.post("/api/rollouts/import")
    assert client.get(f"/api/episodes/{episode_id}").json()["success"] is False
