"""Launch one local SO-101 leader/follower LeRobot demonstration session."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from teach_task_coach.demos import DemoScanner
from teach_task_coach.station import StationClient, StationUnavailable


class ArmLease:
    """Hold the station's arm lock while a local teleop process owns the motors."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if stream.seek(0, os.SEEK_END) == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise ValueError("Robot arms are still owned by the station or another recorder.") from exc
        self.stream = stream

    def child_options(self) -> dict:
        # On POSIX the child retains the same flock if the coach server exits.
        return {"pass_fds": (self.stream.fileno(),)} if os.name != "nt" else {}

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None


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
    log_tail: str | None = None


class SO101Recorder:
    def __init__(
        self, scanner: DemoScanner, station: StationClient, arm_lock_path: Path | None = None
    ) -> None:
        self.scanner = scanner
        self.station = station
        home = Path(os.getenv("DREAMCLI_HOME", "~/.dreamlabs")).expanduser()
        configured_lock = os.getenv("COACH_ARMS_LOCK") or str(home / "arms.lock")
        self.arm_lock_path = arm_lock_path or Path(configured_lock).expanduser()
        self.lease: ArmLease | None = None
        self.process: subprocess.Popen | None = None
        self.session_path: Path | None = None
        self.log_path: Path | None = None
        self.log_file = None
        self.stop_requested = False

    def status(self) -> TeleopStatus:
        if self.process is None:
            return TeleopStatus(state="idle", session_path=None, exit_code=None)
        code = self.process.poll()
        if code is not None:
            if self.log_file is not None:
                self.log_file.close()
                self.log_file = None
            if self.lease is not None:
                self.lease.close()
                self.lease = None
        if code is None:
            state = "stopping" if self.stop_requested else "recording"
        else:
            state = "stopped" if self.stop_requested else ("complete" if code == 0 else "failed")
        log_tail = None
        if code is not None and state == "failed" and self.log_path and self.log_path.exists():
            with self.log_path.open("rb") as stream:
                stream.seek(max(0, self.log_path.stat().st_size - 4096))
                log_tail = stream.read().decode("utf-8", errors="replace")
        return TeleopStatus(
            state=state, session_path=str(self.session_path), exit_code=code,
            log_tail=log_tail,
        )

    def stop(self) -> TeleopStatus:
        if self.process is None or self.process.poll() is not None:
            raise ValueError("No teleoperation recording is running.")
        if not self.stop_requested:
            self.process.terminate()
            self.stop_requested = True
        return self.status()

    def start(self, prompt: str, request: TeleopRequest) -> TeleopStatus:
        if self.status().state in ("recording", "stopping"):
            raise ValueError("A teleoperation recording is already running.")
        if request.follower_port.strip() == request.leader_port.strip():
            raise ValueError("Leader and follower must use different serial ports.")
        station_url = getattr(self.station, "base_url", None)
        if isinstance(station_url, str) and urlsplit(station_url).hostname not in (
            "127.0.0.1", "localhost", "::1"
        ):
            raise ValueError("Run the teleoperation recorder on the robot computer with a local station URL.")
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
        self.log_path = self.scanner.root / f"{self.session_path.name}.log"
        self.stop_requested = False
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
        lease = ArmLease(self.arm_lock_path)
        try:
            lease.acquire()
            self.log_file = self.log_path.open("wb")
            self.process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=self.log_file,
                stderr=subprocess.STDOUT, shell=False,
                **lease.child_options(),
            )
        except BaseException:
            if self.log_file is not None:
                self.log_file.close()
            self.log_file = None
            lease.close()
            raise
        self.lease = lease
        return self.status()
