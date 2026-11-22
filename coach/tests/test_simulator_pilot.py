"""Exercise the simulator recorder through the same endpoints as Coach's Runs screen."""

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

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

    client = TestClient(
        create_app(store=EpisodeStore(tmp_path / "coach"), scanner=RolloutScanner(root))
    )
    assert client.post("/api/rollouts/import").json() == {"imported": 2, "skipped": []}
    runs = [
        client.get("/api/episodes/" + item["id"]).json()
        for item in client.get("/api/episodes").json()
    ]
    first, failed = sorted(runs, key=lambda r: r["simulation"]["seed"])
    assert first["status"] == "complete" and first["simulation"]["model_action_rows"] == 1
    assert failed["simulation"]["requests_attempted"] == 1
    assert failed["simulation"]["model_action_rows"] == 0
    assert failed["status"] == "partial" and failed["success"] is None
    assert failed["pickup_evidence"]["observation"] == "no_actions"
    assert first["pickup_evidence"]["observation"] == "no_contact"
    assert first["pickup_evidence"]["analyzed_frames"] == 1 and first["success"] is None
    assert first["simulation"]["apple_xy_m"] != failed["simulation"]["apple_xy_m"]
    path = "/api/episodes/" + first["id"]
    for role in ("overhead", "wrist_l", "wrist_r"):
        assert client.get(path + "/video/" + role).content[4:8] == b"ftyp"
    assert client.post(
        path + "/label", json={"success": False, "note": "Only one action"}
    ).is_success
    client.post("/api/rollouts/import")
    assert client.get(path).json()["success"] is False


def test_reference_hold_links_to_a_real_frame_without_labelling_it(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    pytest.importorskip("PIL")
    import av

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas")
    )
    import record_yam_demos as recorder

    root = tmp_path / "rollouts"
    with recorder.recording(root, recorder.TASK, "scripted-yam", 101, "scripted") as (env, details):
        details["script_result"] = recorder.mock_pickups.run_trial(
            "apple", env=env, snapshot_dir=env.folder
        )
    episodes, skipped = RolloutScanner(root).scan()
    assert not skipped and len(episodes) == 1
    run = episodes[0]
    evidence = run.pickup_evidence
    assert evidence.source == "scripted" and evidence.observation == "held"
    assert run.success is None and 0 < evidence.first_contact_s < evidence.evidence_s
    assert evidence.longest_hold_s >= 2 and evidence.peak_lift_m > 0.08
    for path in run.videos.values():
        with av.open(path) as clip:
            assert round(evidence.evidence_s * run.fps) < clip.streams.video[0].frames == run.frames


def test_scripted_settle_preserves_wrist_visible_pose(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    pytest.importorskip("PIL")
    import numpy as np

    scripts = Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"
    monkeypatch.syspath_prepend(str(scripts))
    import record_yam_demos as recorder

    env = recorder.RecordingYamEnv(tmp_path, "pick up the apple", 41, start_pose="wrist-visible")
    initial = env.state()
    commands = []
    step = env.step

    class StopAfterSettle(Exception):
        pass

    def observed_step(left, right):
        commands.append((np.asarray(left).copy(), np.asarray(right).copy()))
        result = step(left, right)
        if len(commands) == 30:
            raise StopAfterSettle
        return result

    env.step = observed_step
    try:
        with pytest.raises(StopAfterSettle):
            recorder.mock_pickups.run_trial("apple", env=env, snapshot_dir=tmp_path)
        assert len(commands) == 30
        for left, right in commands:
            np.testing.assert_allclose(left, initial["left"])
            np.testing.assert_allclose(right, initial["right"])
        np.testing.assert_allclose(env.state()["left"], initial["left"], atol=1e-6)
        np.testing.assert_allclose(env.state()["right"], initial["right"], atol=1e-6)
    finally:
        env.close()


def test_scripted_recorder_cli_accepts_wrist_visible(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    pytest.importorskip("PIL")
    scripts = Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"
    monkeypatch.syspath_prepend(str(scripts))
    import record_yam_demos as recorder

    observed = []
    folder = tmp_path / "episode"
    folder.mkdir()

    @contextmanager
    def fake_recording(_root, _task, _checkpoint, seed, _source, *, start_pose):
        observed.append((seed, start_pose))
        yield SimpleNamespace(folder=folder), {}

    monkeypatch.setattr(recorder, "recording", fake_recording)
    monkeypatch.setattr(recorder.mock_pickups, "run_trial", lambda *a, **kw: {"passed": True})
    recorder.main(
        [
            "--output",
            str(tmp_path),
            "--episodes",
            "1",
            "--seed",
            "41",
            "--start-pose",
            "wrist-visible",
        ]
    )
    assert observed == [(41, "wrist-visible")]


def test_seed41_wrist_visible_pose_keeps_apple_separate_and_in_view(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    pytest.importorskip("PIL")
    import numpy as np

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas")
    )
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
