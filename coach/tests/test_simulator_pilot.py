"""Exercise the simulator recorder through the same endpoints as Coach's Runs screen."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teach_task_coach.api import create_app
from teach_task_coach.episodes import RolloutScanner
from teach_task_coach.storage import EpisodeStore


def test_simulator_pilot_budget_and_review(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    pytest.importorskip("PIL")
    scripts = Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"
    monkeypatch.syspath_prepend(str(scripts))
    import record_dream_model_rollout as pilot

    root = tmp_path / "rollouts"
    monkeypatch.setenv("DREAM_API_KEY", "test-only")
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path / "coach"))
    monkeypatch.setattr(pilot.dream_control, "FRAMES", 1)
    monkeypatch.setattr(pilot.dream_control, "settings", lambda: {"DREAM_API_KEY": "test-only"})

    class FakePolicy:
        calls = 0

        def set_observation(self, *args, **kwargs):
            pass

        def get_action(self):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("simulated inference failure")
            rows = [[0, 0, 0, 0, 0, 0, 1]]
            return {"q_l_chunk": rows, "q_r_chunk": rows}

        def close(self):
            pass

    policy = FakePolicy()
    monkeypatch.setattr(pilot.dream_control, "open_policy", lambda config, key: policy)
    argv = ["pilot", "--output", str(root), "--seconds", "60", "--seed"]
    monkeypatch.setattr(sys, "argv", [*argv, "41"])
    pilot.main()
    assert policy.calls == 1
    monkeypatch.setattr(sys, "argv", [*argv, "42"])
    with pytest.raises(RuntimeError, match="simulated inference failure"):
        pilot.main()

    client = TestClient(create_app(store=EpisodeStore(tmp_path / "coach"), scanner=RolloutScanner(root)))
    assert client.post("/api/rollouts/import").json() == {"imported": 2, "skipped": []}
    runs = [client.get("/api/episodes/" + item["id"]).json() for item in client.get("/api/episodes").json()]
    first, failed = sorted(runs, key=lambda r: r["simulation"]["seed"])
    assert first["status"] == "complete" and first["simulation"]["model_action_rows"] == 1
    assert failed["simulation"]["requests_attempted"] == 1
    assert failed["simulation"]["model_action_rows"] == 0
    assert failed["status"] == "partial" and failed["success"] is None
    assert first["simulation"]["apple_xy_m"] != failed["simulation"]["apple_xy_m"]
    path = "/api/episodes/" + first["id"]
    for role in ("overhead", "wrist_l", "wrist_r"):
        assert client.get(path + "/video/" + role).content[4:8] == b"ftyp"
    assert client.post(path + "/label", json={"success": False, "note": "Only one action"}).is_success
    client.post("/api/rollouts/import")
    assert client.get(path).json()["success"] is False


def test_seed41_wrist_visible_pose_keeps_apple_separate_and_in_view(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    pytest.importorskip("PIL")
    import numpy as np

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"))
    from record_yam_demos import RecordingYamEnv

    env = RecordingYamEnv(tmp_path, "pick up the apple", 41, start_pose="wrist-visible")
    try:
        q = env.state()
        assert q["left"][-1] > 0.99
        apple = env.data.body("apple")
        assert np.linalg.norm(apple.xpos - env.data.site("left_tcp").xpos) > 0.18
        env.images()
        env.renderer.enable_segmentation_rendering()
        env.renderer.update_scene(env.data, camera="left")
        geom_ids = env.renderer.render()[60:420, :, 0]
        apple_geoms = np.flatnonzero(env.model.geom_bodyid == env.model.body("apple").id)
        assert np.isin(geom_ids, apple_geoms).sum() > 500
    finally:
        env.close()


def test_training_export_preserves_gripper_slots_and_frame_times(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    pytest.importorskip("PIL")
    import av
    import json
    import numpy as np
    import pyarrow.parquet as pq

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"))
    from record_yam_demos import RecordingYamEnv
    from resample_yam_demos import export_session

    source, target = tmp_path / "raw", tmp_path / "export"
    env = RecordingYamEnv(source, "pick up the apple", 44, start_pose="wrist-visible")
    try:
        arms = env.state()
        for grip in (1.0, 0.75, 0.5, 0.25, 0.0):
            env.step(np.r_[arms["left"][:6], grip], arms["right"])
    finally:
        env.close()
    assert export_session(source, target) == 3
    table = pq.read_table(next(target.rglob("*.parquet")))
    assert table["frame_index"].to_pylist() == [0, 1, 2]
    assert np.array(table["action"].to_pylist())[:, 13].tolist() == [1.0, 0.5, 0.0]
    info = json.loads((target / "meta/info.json").read_text())
    names = info["features"]["action"]["names"]
    assert [names[6], names[13]] == ["right_gripper", "left_gripper"]
    stats = json.loads((target / "meta/episodes_stats.jsonl").read_text())
    assert stats["stats"]["action"]["count"] == [3]
    for video in target.rglob("*.mp4"):
        with av.open(str(video)) as container:
            times = [float(frame.time) for frame in container.decode(video=0)]
        np.testing.assert_allclose(times, table["timestamp"].to_pylist(), atol=1e-6)
