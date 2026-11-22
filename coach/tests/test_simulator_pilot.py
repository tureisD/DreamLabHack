"""Exercise the simulator recorder through the same endpoints as Coach's Runs screen."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teach_task_coach.api import create_app
from teach_task_coach.episodes import RolloutScanner
from teach_task_coach.storage import EpisodeStore


def test_training_batches_are_independent(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas/grasp_training"
    monkeypatch.syspath_prepend(str(scripts))
    from batch import HOLDOUT, SEEDS

    assert len(SEEDS["varied"]) == len(SEEDS["independent"]) == 24
    assert SEEDS["varied"].isdisjoint(SEEDS["independent"])
    assert SEEDS["independent"].isdisjoint(HOLDOUT)


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


def test_named_finetune_actions_and_station_chunks_preserve_archived_joint_order(monkeypatch):
    pytest.importorskip("mujoco")
    import io
    import zipfile
    import numpy as np
    import pyarrow.parquet as pq

    scripts = Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"
    monkeypatch.syspath_prepend(str(scripts))
    import record_dream_model_rollout as pilot

    with zipfile.ZipFile(scripts / "grasp_training/varied.zip") as archive:
        name = next(name for name in archive.namelist() if name.endswith(".parquet"))
        rows = np.asarray(pq.read_table(io.BytesIO(archive.read(name)), columns=["action"])["action"].to_pylist())
    close = int(np.argmin(rows[:, 13]))
    sample = rows[max(0, close - 12):close + 12]
    # A real one-handed grasp gives an asymmetric test of side and gripper order.
    assert np.ptp(sample[:, 13]) > 0.5 and np.ptp(sample[:, 6]) < 0.01
    named = {"action." + part: sample[:, lo:hi] for part, (lo, hi) in pilot.recorder.PARTS.items()}
    station = {"q_l_chunk": sample[:, 7:], "q_r_chunk": sample[:, :7]}
    env = pilot.recorder.YamEnv()
    try:
        validate = pilot.dream_control.validate_chunk
        left, right = validate(env, station, verbose=False)
        flat_grips = {key: (value[:, 0] if key.endswith("_gripper") else value) for key, value in named.items()}
        for reply in ({"per_key": named}, {"per_key": flat_grips}, station | {"per_key": {}}):
            actual = validate(env, reply, verbose=False)
            np.testing.assert_array_equal(actual[0], left)
            np.testing.assert_array_equal(actual[1], right)
        for malformed in (named | {"action.left_arm": sample[:, :5]}, named | {"action.right_gripper": sample[:-1, 6:7]}):
            with pytest.raises(ValueError):
                validate(env, {"per_key": malformed})
    finally:
        env.close()


def test_control_budget_stops_mid_chunk_without_an_extra_request(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    from unittest.mock import Mock
    import numpy as np

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"))
    import record_dream_model_rollout as pilot
    control = pilot.dream_control
    policy = Mock()
    policy.get_action.return_value = {"per_key": {
        "action." + part: np.ones((2, hi - lo)) * 0.5 for part, (lo, hi) in pilot.recorder.PARTS.items()
    }}
    monkeypatch.setattr(control, "open_policy", lambda *_: policy)
    monkeypatch.setattr(control, "settings", lambda: {"DREAM_API_KEY": "offline-fixture"})
    monkeypatch.setattr(control, "FRAMES", 1)
    with pilot.recorder.recording(tmp_path, pilot.recorder.TASK, "fixture/parts", 41, "model") as (env, details):
        rows = control.main(["--headless", "--model", "fixture/parts", "--control-rows", "3", "--max-requests", "5"],
                            shared_env=env, progress=details)
        assert rows == details["model_action_rows"] == 3
        assert policy.get_action.call_count == details["requests_attempted"] == 2
        assert details["warmup_rows"] == 1 and len(env.states) == 4


def test_heldout_request_cap_preserves_short_attempt_for_review(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    from unittest.mock import Mock
    from teach_task_coach.episodes import read_episode

    scripts = Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"
    monkeypatch.syspath_prepend(str(scripts))
    import record_dream_model_rollout as pilot

    manifest = next((scripts / "grasp_training/held_out").glob("fdcaa847*.json"))
    policy = Mock()
    policy.get_action.return_value = {"q_l_chunk": [[0, 0, 0, 0, 0, 0, 1]], "q_r_chunk": [[0, 0, 0, 0, 0, 0, 1]]}
    monkeypatch.setenv("DREAM_API_KEY", "offline-fixture")
    monkeypatch.setattr(pilot.dream_control, "open_policy", lambda *_: policy)
    with pytest.raises(RuntimeError, match="executed 1 of 400"):
        pilot.main(["--output", str(tmp_path), "--held-out-scene", str(manifest), "--max-requests", "1"])
    run = read_episode(next(tmp_path.glob("yam-*")))
    assert run.status == "partial" and run.success is None and run.frames == 34
    assert run.simulation["control_stop"] == "request_cap"
    assert run.simulation["simulated_control_seconds"] == 0.05 and run.simulation["requests_attempted"] == 1
    assert run.pickup_evidence.analyzed_frames == 1


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
    import json

    import av
    import numpy as np
    import pyarrow.parquet as pq

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"))
    from record_yam_demos import RecordingYamEnv
    from resample_yam_demos import export_camera, export_session

    source, target = tmp_path / "raw", tmp_path / "export"
    env = RecordingYamEnv(source, "pick up the apple", 44, start_pose="wrist-visible")
    try:
        arms = env.state()
        for grip in (1.0, 0.75, 0.5, 0.25, 0.0):
            env.step(np.r_[arms["left"][:6], grip], arms["right"])
    finally:
        env.close()
    assert export_session(source, target) == 3
    raw_names = json.loads((source / "meta/info.json").read_text())["features"]["action"]["names"]
    assert [raw_names[6], raw_names[13]] == ["right_gripper", "left_gripper"]
    # Both five and six 20 Hz rows would yield three exported frames.
    with pytest.raises(ValueError, match="decoded 5 source frames, expected 6"):
        export_camera(next(source.rglob("*.mp4")), tmp_path / "mismatch.mp4", 6)
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
