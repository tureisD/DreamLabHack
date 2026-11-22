"""Run a simulator child process that a fresh session can cancel."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryFile
from threading import Event
from typing import Any


class SimulatorProcessCancelled(RuntimeError):
    """The current session cancelled the simulator command."""


def _stop_process_tree(child: subprocess.Popen) -> None:
    if os.name == "nt":
        # A Windows venv launcher can have a second interpreter running the actual rollout.
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(child.pid), "/T", "/F"], timeout=3, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if child.poll() is None:
        child.kill()


def run_simulator_process(
    args: list[str], *, timeout: float, cancel: Event | None = None, **popen_kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    if cancel is None:
        return subprocess.run(
            args, capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False, **popen_kwargs,
        )
    if cancel.is_set():
        raise SimulatorProcessCancelled()

    # Files avoid blocking on pipe readers when a child is stopped mid-render.
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    with TemporaryFile() as stdout, TemporaryFile() as stderr:
        with subprocess.Popen(args, stdout=stdout, stderr=stderr, **popen_kwargs) as child:
            deadline = time.monotonic() + timeout
            try:
                while child.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(args, timeout)
                    if cancel.wait(min(0.2, remaining)):
                        raise SimulatorProcessCancelled()
                if cancel.is_set():
                    raise SimulatorProcessCancelled()
            finally:
                if child.poll() is None:
                    _stop_process_tree(child)
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(
            args, child.returncode, stdout.read().decode("utf-8", "replace"),
            stderr.read().decode("utf-8", "replace"),
        )
