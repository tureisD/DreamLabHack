import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from teach_task_coach.simulator_process import SimulatorProcessCancelled, run_simulator_process


def test_reset_cancels_a_running_simulator_process(tmp_path):
    ready = tmp_path / "started"
    cancel = Event()
    script = "import pathlib, sys, time; pathlib.Path(sys.argv[1]).touch(); time.sleep(60)"

    def cancel_after_start():
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        cancel.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        reset = executor.submit(cancel_after_start)
        with pytest.raises(SimulatorProcessCancelled):
            run_simulator_process([sys.executable, "-c", script, str(ready)], timeout=8, cancel=cancel)
        reset.result()


def test_reset_cancels_simulator_descendants(tmp_path):
    ready = tmp_path / "started"
    release = tmp_path / "release"
    leaked = tmp_path / "leaked"
    descendant = (
        "import pathlib, sys, time\n"
        "ready, release, leaked = map(pathlib.Path, sys.argv[1:])\n"
        "ready.touch()\n"
        "for _ in range(300):\n"
        "    if release.exists():\n"
        "        leaked.touch()\n"
        "        break\n"
        "    time.sleep(0.05)\n"
    )
    launcher = "import subprocess, sys; subprocess.Popen([sys.executable, *sys.argv[1:]]).wait()"
    args = [sys.executable, "-c", launcher, "-c", descendant, str(ready), str(release), str(leaked)]
    cancel = Event()

    def cancel_after_launch():
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        cancel.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            reset = executor.submit(cancel_after_launch)
            with pytest.raises(SimulatorProcessCancelled):
                run_simulator_process(args, timeout=8, cancel=cancel)
            reset.result()
    finally:
        release.touch()
    time.sleep(0.3)
    assert not leaked.exists()
