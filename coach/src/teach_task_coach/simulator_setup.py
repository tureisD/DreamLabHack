"""Prepare the bundled YAM simulator without running a robot or Dream inference."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import threading
from pathlib import Path

from pydantic import BaseModel, Field


class SimulatorStatus(BaseModel):
    state: str
    message: str
    log: list[str] = Field(default_factory=list)


class SimulatorSetup:
    def __init__(self, coach_dir: Path | None = None) -> None:
        self.coach_dir = coach_dir or Path(__file__).resolve().parents[2]
        self._lock = threading.Lock()
        self._state = "idle"
        self._log: list[str] = []

    def _installed(self) -> bool:
        scripts = self.coach_dir / "experiments/yam_sim_faas"
        return (importlib.util.find_spec("mujoco") is not None
                and (scripts / "record_yam_demos.py").is_file()
                and (scripts / "collect_failure_demos.py").is_file())

    def status(self) -> SimulatorStatus:
        with self._lock:
            state = self._state
            log = list(self._log[-12:])
        if state == "preparing":
            return SimulatorStatus(state=state, message="Installing the bundled simulator dependencies.", log=log)
        if self._installed():
            return SimulatorStatus(state="ready", message="YAM simulator dependencies and collection scripts are available locally.", log=log)
        if state == "failed":
            return SimulatorStatus(state=state, message="Simulator preparation failed. Check that uv is installed and try again.", log=log)
        return SimulatorStatus(state="missing", message="YAM simulator dependencies are not installed yet.", log=log)

    def prepare(self) -> SimulatorStatus:
        current = self.status()
        if current.state in ("ready", "preparing"):
            return current
        with self._lock:
            if self._state != "preparing":
                self._state = "preparing"
                self._log = ["Starting local YAM simulator dependency setup."]
                threading.Thread(target=self._run, daemon=True, name="coach-simulator-setup").start()
        return self.status()

    def _run(self) -> None:
        uv = shutil.which("uv")
        if not uv:
            with self._lock:
                self._state = "failed"
                self._log.append("uv is not installed. Install uv, then try again.")
            return
        try:
            result = subprocess.run(
                [uv, "sync", "--locked", "--extra", "sim"], cwd=self.coach_dir,
                capture_output=True, text=True, timeout=600, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            lines = (result.stdout + "\n" + result.stderr).splitlines()[-10:]
            ready = result.returncode == 0 and self._installed()
            with self._lock:
                self._log.extend(lines)
                self._log.append("Simulator ready." if ready else f"Setup exited with code {result.returncode}.")
                self._state = "ready" if ready else "failed"
        except (OSError, subprocess.TimeoutExpired) as exc:
            with self._lock:
                self._state = "failed"
                self._log.append(f"Setup could not finish: {type(exc).__name__}.")
