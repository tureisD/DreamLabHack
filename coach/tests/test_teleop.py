from unittest.mock import Mock

import pytest

from teach_task_coach.demos import DemoScanner
from teach_task_coach.station import StationUnavailable
from teach_task_coach.teleop import ArmLease, SO101Recorder, TeleopRequest


def test_so101_recorder_requires_station_down_and_uses_local_single_episode(monkeypatch, tmp_path):
    station = Mock()
    recorder = SO101Recorder(DemoScanner(tmp_path / "demos"), station, tmp_path / "arms.lock")
    request = TeleopRequest(
        follower_port="/dev/follower", leader_port="/dev/leader",
        follower_id="follower", leader_id="leader", camera_index=1,
    )
    with pytest.raises(ValueError, match="Stop the Dream station"):
        recorder.start("put block in bin", request)
    station.status.side_effect = StationUnavailable("down")
    monkeypatch.setattr("teach_task_coach.teleop.shutil.which", lambda _: "/bin/lerobot-record")
    process = Mock()
    process.poll.return_value = None
    launched = Mock(return_value=process)
    monkeypatch.setattr("teach_task_coach.teleop.subprocess.Popen", launched)
    status = recorder.start("put block in bin", request)
    assert status.state == "recording"
    args = launched.call_args.args[0]
    assert "--dataset.num_episodes=1" in args
    assert "--dataset.push_to_hub=false" in args
    assert "--dataset.single_task=put block in bin" in args
    assert any(arg.startswith("--dataset.root=") for arg in args)
    assert launched.call_args.kwargs["shell"] is False
    with pytest.raises(ValueError, match="already running"):
        recorder.start("put block in bin", request)
    process.poll.return_value = 0
    assert recorder.status().state == "complete"


def test_so101_recorder_refuses_timeout_when_station_still_holds_arms(monkeypatch, tmp_path):
    station = Mock()
    station.status.side_effect = StationUnavailable("timed out")
    recorder = SO101Recorder(DemoScanner(tmp_path / "demos"), station, tmp_path / "arms.lock")
    monkeypatch.setattr("teach_task_coach.teleop.shutil.which", lambda _: "/bin/lerobot-record")
    launched = Mock()
    monkeypatch.setattr("teach_task_coach.teleop.subprocess.Popen", launched)
    request = TeleopRequest(
        follower_port="/dev/follower", leader_port="/dev/leader",
        follower_id="follower", leader_id="leader", camera_index=0,
    )
    holder = ArmLease(tmp_path / "arms.lock")
    holder.acquire()
    try:
        with pytest.raises(ValueError, match="arms are still owned"):
            recorder.start("put block in bin", request)
    finally:
        holder.close()
    launched.assert_not_called()


def test_teleop_stop_retains_lock_until_recorder_exits(monkeypatch, tmp_path):
    station = Mock()
    station.status.side_effect = StationUnavailable("down")
    recorder = SO101Recorder(DemoScanner(tmp_path / "demos"), station, tmp_path / "arms.lock")
    monkeypatch.setattr("teach_task_coach.teleop.shutil.which", lambda _: "/bin/lerobot-record")
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr("teach_task_coach.teleop.subprocess.Popen", Mock(return_value=process))
    request = TeleopRequest(
        follower_port="/dev/follower", leader_port="/dev/leader",
        follower_id="follower", leader_id="leader", camera_index=0,
    )
    with pytest.raises(ValueError, match="different serial ports"):
        recorder.start("move block", request.model_copy(update={"leader_port": "/dev/follower"}))
    recorder.start("move block", request)
    assert recorder.stop().state == "stopping"
    process.terminate.assert_called_once()
    with pytest.raises(ValueError, match="already running"):
        recorder.start("move block", request)
    holder = ArmLease(tmp_path / "arms.lock")
    with pytest.raises(ValueError, match="arms are still owned"):
        holder.acquire()
    process.poll.return_value = -15
    assert recorder.status().state == "stopped"
    holder.acquire()
    holder.close()


def test_teleop_failure_returns_only_current_session_log(monkeypatch, tmp_path):
    station = Mock()
    station.status.side_effect = StationUnavailable("down")
    recorder = SO101Recorder(DemoScanner(tmp_path / "demos"), station, tmp_path / "arms.lock")
    monkeypatch.setattr("teach_task_coach.teleop.shutil.which", lambda _: "/bin/lerobot-record")
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr("teach_task_coach.teleop.subprocess.Popen", Mock(return_value=process))
    recorder.start("move block", TeleopRequest(
        follower_port="/dev/follower", leader_port="/dev/leader",
        follower_id="follower", leader_id="leader", camera_index=0,
    ))
    assert recorder.log_path is not None
    recorder.log_file.write(b"camera unavailable\n")
    recorder.log_file.flush()
    process.poll.return_value = 1
    status = recorder.status()
    assert status.state == "failed"
    assert "camera unavailable" in status.log_tail
