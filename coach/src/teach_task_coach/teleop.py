"""Launch one local SO-101 leader/follower LeRobot demonstration session."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from teach_task_coach.demos import DemoScanner
from teach_task_coach.station import StationClient, StationUnavailable


class TeleopRequest(BaseModel):
    follower_port: str = Field(min_length=1)
    leader_port: str = Field(min_length=1)
    follower_id: str = Field(min_length=1)
    leader_id: str = Field(min_length=1)
    camera_index: int = Field(ge=0)
    seconds: int = Field(default=30, ge=5, le=120)


class TeleopStatus(BaseModel):
    state: str
    session_path: str | None
    exit_code: int | None


class SO101Recorder:
    def __init__(self, scanner: DemoScanner, station: StationClient) -> None:
        self.scanner = scanner
        self.station = station
        self.process: subprocess.Popen | None = None
        self.session_path: Path | None = None
        self.log_file = None

    def status(self) -> TeleopStatus:
        if self.process is None:
            return TeleopStatus(state="idle", session_path=None, exit_code=None)
        code = self.process.poll()
        return TeleopStatus(
            state="recording" if code is None else ("complete" if code == 0 else "failed"),
            session_path=str(self.session_path), exit_code=code,
        )

    def start(self, prompt: str, request: TeleopRequest) -> TeleopStatus:
        if self.status().state == "recording":
            raise ValueError("A teleoperation recording is already running.")
        try:
            self.station.status()
        except StationUnavailable:
            pass
        else:
            raise ValueError("Stop the Dream station process before teleoperation; it owns the arms.")
        binary = shutil.which(os.getenv("COACH_LEROBOT_RECORD", "lerobot-record"))
        if binary is None:
            raise ValueError("Install LeRobot's lerobot-record command on the robot computer first.")
        self.scanner.root.mkdir(parents=True, exist_ok=True)
        self.session_path = self.scanner.root / f"so101-{uuid.uuid4().hex[:12]}"
        repo_id = f"local/coach-{uuid.uuid4().hex[:12]}"
        camera = (
            "{overhead: {type: opencv, index_or_path: "
            f"{request.camera_index}, width: 640, height: 480, fps: 30}}}}"
        )
        args = [
            binary,
            "--robot.type=so101_follower", f"--robot.port={request.follower_port}",
            f"--robot.id={request.follower_id}", "--teleop.type=so101_leader",
            f"--teleop.port={request.leader_port}", f"--teleop.id={request.leader_id}",
            f"--robot.cameras={camera}", f"--dataset.repo_id={repo_id}",
            f"--dataset.root={self.session_path}", f"--dataset.single_task={prompt}",
            "--dataset.num_episodes=1", f"--dataset.episode_time_s={request.seconds}",
            "--dataset.reset_time_s=0", "--dataset.push_to_hub=false",
        ]
        self.log_file = (self.scanner.root / "so101-recorder.log").open("ab")
        try:
            self.process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=self.log_file,
                stderr=subprocess.STDOUT, shell=False,
            )
        except OSError:
            self.log_file.close()
            self.log_file = None
            raise
        return self.status()
