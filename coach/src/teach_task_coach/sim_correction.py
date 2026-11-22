"""Local, robot-free click-to-correct simulator service.

The MuJoCo dependency is imported only when a simulator endpoint is used. One
recording runs at a time because MuJoCo rendering and video export are costly.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from typing import Any

from teach_task_coach.demos import DemoStore, read_demo
from teach_task_coach.simulator_process import SimulatorProcessCancelled, run_simulator_process

_IDLE = {"state": "idle", "result": None, "error": None}
_RESET_TIMEOUT_S = 10


def simulator_module() -> Any:
    directory = Path(__file__).resolve().parents[2] / "experiments/yam_sim_faas"
    if not directory.is_dir():
        raise RuntimeError("The YAM simulator scripts are unavailable in this installation.")
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    try:
        import click_to_correct
    except ImportError as exc:
        raise RuntimeError("Install the coach simulator dependencies with uv sync --extra sim.") from exc
    return click_to_correct


def _script() -> Path:
    path = Path(__file__).resolve().parents[2] / "experiments/yam_sim_faas/click_to_correct.py"
    if not path.is_file():
        raise RuntimeError("The YAM simulator scripts are unavailable in this installation.")
    return path


def _scene_script() -> Path:
    path = Path(__file__).resolve().parents[2] / "experiments/yam_sim_faas/scene_task.py"
    if not path.is_file():
        raise RuntimeError("The configurable YAM scene task is unavailable in this installation.")
    return path


def _run_process(script: Path, arguments: list[str], *, timeout: int, cancel: Event | None = None) -> str:
    completed = run_simulator_process([sys.executable, str(script), *arguments], timeout=timeout, cancel=cancel)
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip()[-1200:]
                           or "The YAM simulator process failed.")
    return completed.stdout


class SimCorrectionService:
    def __init__(self, demos_root: Path, demos: DemoStore) -> None:
        self.demos_root = demos_root
        self.demos = demos
        self._lock = Lock()
        self._reset_lock = Lock()
        self._resetting = False
        self._generation = 0
        self._recording: tuple[Thread, Event] | None = None
        self._state: dict[str, Any] = _IDLE.copy()

    def preview(self, fruit: str, seed: int) -> dict[str, Any]:
        if fruit not in ("apple", "banana") or seed < 0 or seed > 2**32 - 1:
            raise ValueError("Choose a supported fruit and a 32-bit nonnegative scene seed.")
        with self._lock:
            if self._state["state"] == "recording":
                raise ValueError("A simulator recording is running; preview after it finishes.")
        return json.loads(_run_process(_script(), ["--preview", "--fruit", fruit, "--seed", str(seed)],
                                       timeout=60))

    def start(self, task_id: str, task_prompt: str, kind: str, fruit: str, seed: int,
              object_pixel: tuple[float, float],
              target_pixel: tuple[float, float] | None) -> dict[str, Any]:
        generation = self._recording_generation()
        sim = simulator_module()
        env = sim.seeded_env(fruit, seed)
        try:
            goal = sim.goal_from_clicks(env, kind, fruit, object_pixel, target_pixel)
            if goal.task_text != task_prompt:
                raise ValueError(f"Local task instruction must be exactly: {goal.task_text}")
        finally:
            env.close()
        arguments = ["--kind", kind, "--fruit", fruit, "--seed", str(seed),
                     "--object-pixel", *(str(value) for value in object_pixel),
                     "--output", str(self.demos_root)]
        if target_pixel is not None:
            arguments += ["--target-pixel", *(str(value) for value in target_pixel)]
        return self._start_recording(task_id, generation, partial(self._render_click, arguments))

    def _recording_generation(self) -> int:
        with self._lock:
            if self._resetting:
                raise ValueError("Wait for the simulator session to finish resetting.")
            if self._recording:
                raise ValueError("Another simulator recording is already running.")
            return self._generation

    def _start_recording(self, task_id: str, generation: int,
                         render: Callable[[Event], dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            if self._resetting or generation != self._generation:
                raise ValueError("The simulator session changed. Start the recording again.")
            if self._recording:
                raise ValueError("Another simulator recording is already running.")
            self._state = {"state": "recording", "task_id": task_id,
                           "result": None, "error": None}
            cancel = Event()
            worker = Thread(target=self._run, args=(task_id, render, cancel), daemon=True)
            self._recording = (worker, cancel)
            try:
                worker.start()
            except RuntimeError:
                self._recording = None
                self._state = _IDLE.copy()
                raise
            return dict(self._state)

    def _run(self, task_id: str, render: Callable[[Event], dict[str, Any]], cancel: Event) -> None:
        state: dict[str, Any] = _IDLE.copy()
        try:
            result = render(cancel)
            demo = read_demo(Path(result["session_path"]), task_id)
            with self._lock:
                if not cancel.is_set():
                    self.demos.upsert(demo)
                    state = {"state": "complete", "task_id": task_id,
                             "result": {**result, "demo_id": demo.id}, "error": None}
        except SimulatorProcessCancelled:
            pass
        except Exception as exc:  # noqa: BLE001 - background failures must reach status polling
            state = {"state": "failed", "task_id": task_id, "result": None, "error": str(exc)}
        finally:
            with self._lock:
                self._state = _IDLE.copy() if cancel.is_set() else state
                self._recording = None

    def _render_click(self, arguments: list[str], cancel: Event) -> dict[str, Any]:
        output = _run_process(_script(), arguments, timeout=600, cancel=cancel)
        return self._render_result(output, "CLICK_RESULT=", "The simulator finished without a verified demo result.")

    @staticmethod
    def _render_result(output: str, prefix: str, error: str) -> dict[str, Any]:
        for line in output.splitlines():
            if line.startswith(prefix):
                return json.loads(line.removeprefix(prefix))
        raise RuntimeError(error)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def reset_session(self) -> None:
        """Cancel the active recording and forget its summary, preserving saved demonstrations."""
        with self._reset_lock:
            with self._lock:
                self._generation += 1
                if not self._recording:
                    self._state = _IDLE.copy()
                    return
                self._resetting = True
                worker, cancel = self._recording
                cancel.set()
            try:
                worker.join(timeout=_RESET_TIMEOUT_S)
                if worker.is_alive():
                    raise TimeoutError("The previous simulator recording is still stopping. Try Begin again.")
            finally:
                with self._lock:
                    self._resetting = False

    def preview_scene_task(self, specification: dict, seed: int) -> dict[str, Any]:
        scene = self._scene_module()
        spec = scene.TaskSpec.from_dict(specification)
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError("Scene seed must be a nonnegative 32-bit integer.")
        with self._lock:
            if self._state["state"] == "recording":
                raise ValueError("A simulator recording is running; preview after it finishes.")
        with TemporaryDirectory() as temporary:
            spec_path = Path(temporary) / "scene.json"
            image_path = Path(temporary) / "preview.png"
            spec_path.write_text(json.dumps(spec.as_dict()), encoding="utf-8")
            output = subprocess.run([sys.executable, str(_scene_script()), "--spec", str(spec_path),
                                     "--seed", str(seed), "--preview", str(image_path)],
                                    capture_output=True, text=True, timeout=60, check=False)
            if output.returncode:
                raise RuntimeError((output.stderr or output.stdout).strip()[-1200:])
            result = json.loads(output.stdout)
            result["image"] = "data:image/png;base64," + base64.b64encode(
                image_path.read_bytes()).decode("ascii")
            result["width"], result["height"] = 640, 360
            return result

    @staticmethod
    def _scene_module() -> Any:
        directory = _scene_script().parent
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        try:
            import scene_task
        except ImportError as exc:
            raise RuntimeError("Install simulator dependencies with uv sync --extra sim.") from exc
        return scene_task

    def start_scene_task(self, task_id: str, task_prompt: str,
                         specification: dict, seed: int) -> dict[str, Any]:
        generation = self._recording_generation()
        scene = self._scene_module()
        spec = scene.TaskSpec.from_dict(specification)
        if spec.prompt != task_prompt:
            raise ValueError(f"Local task instruction must be exactly: {spec.prompt}")
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError("Scene seed must be a nonnegative 32-bit integer.")
        return self._start_recording(task_id, generation, partial(self._render_scene, spec.as_dict(), seed))

    def _render_scene(self, specification: dict, seed: int, cancel: Event) -> dict[str, Any]:
        with TemporaryDirectory() as temporary:
            spec_path = Path(temporary) / "scene.json"
            spec_path.write_text(json.dumps(specification), encoding="utf-8")
            output = _run_process(
                _scene_script(),
                ["--spec", str(spec_path), "--seed", str(seed), "--collect", "--output", str(self.demos_root)],
                timeout=600, cancel=cancel,
            )
        return self._render_result(
            output, "SCENE_RESULT=", "The scene task finished without a verified demo result."
        )
