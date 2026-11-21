from unittest.mock import Mock

import pytest

from teach_task_coach.demos import DemoScanner
from teach_task_coach.station import StationUnavailable
from teach_task_coach.teleop import SO101Recorder, TeleopRequest


def test_so101_recorder_requires_station_down_and_uses_local_single_episode(monkeypatch, tmp_path):
    station = Mock()
    recorder = SO101Recorder(DemoScanner(tmp_path / "demos"), station)
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
    recorder.log_file.close()
