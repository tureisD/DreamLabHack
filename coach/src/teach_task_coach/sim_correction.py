"""Local, robot-free click-to-correct simulator service.

The MuJoCo dependency is imported only when a simulator endpoint is used. One
recording runs at a time because MuJoCo rendering and video export are costly.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from typing import Any

from teach_task_coach.demos import DemoStore, read_demo


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


def _run_process(arguments: list[str], *, timeout: int) -> str:
    completed = subprocess.run([sys.executable, str(_script()), *arguments],
                               capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip()[-1200:]
                           or "The YAM simulator process failed.")
    return completed.stdout


class SimCorrectionService:
    def __init__(self, demos_root: Path, demos: DemoStore) -> None:
        self.demos_root = demos_root
        self.demos = demos
        self._lock = Lock()
        self._state: dict[str, Any] = {"state": "idle", "result": None, "error": None}

    def preview(self, fruit: str, seed: int) -> dict[str, Any]:
        if fruit not in ("apple", "banana") or seed < 0 or seed > 2**32 - 1:
            raise ValueError("Choose a supported fruit and a 32-bit nonnegative scene seed.")
        with self._lock:
            if self._state["state"] == "recording":
                raise ValueError("A simulator recording is running; preview after it finishes.")
        return json.loads(_run_process(["--preview", "--fruit", fruit, "--seed", str(seed)],
                                       timeout=60))

    def start(self, task_id: str, task_prompt: str, kind: str, fruit: str, seed: int,
              object_pixel: tuple[float, float],
              target_pixel: tuple[float, float] | None) -> dict[str, Any]:
        sim = simulator_module()
        env = sim.seeded_env(fruit, seed)
        try:
            goal = sim.goal_from_clicks(env, kind, fruit, object_pixel, target_pixel)
            if goal.task_text != task_prompt:
                raise ValueError(f"Local task instruction must be exactly: {goal.task_text}")
        finally:
            env.close()
        with self._lock:
            if self._state["state"] == "recording":
                raise ValueError("Another simulator recording is already running.")
            self._state = {"state": "recording", "task_id": task_id,
                           "result": None, "error": None}
        worker = Thread(target=self._run, args=(task_id, kind, fruit, seed,
                                               object_pixel, target_pixel), daemon=True)
        worker.start()
        return self.status()

    def _run(self, task_id: str, kind: str, fruit: str, seed: int,
             object_pixel: tuple[float, float],
             target_pixel: tuple[float, float] | None) -> None:
        try:
            arguments = ["--kind", kind, "--fruit", fruit, "--seed", str(seed),
                         "--object-pixel", *(str(value) for value in object_pixel),
                         "--output", str(self.demos_root)]
            if target_pixel is not None:
                arguments += ["--target-pixel", *(str(value) for value in target_pixel)]
            output = _run_process(arguments, timeout=600)
            marker = next((line.removeprefix("CLICK_RESULT=") for line in output.splitlines()
                           if line.startswith("CLICK_RESULT=")), None)
            if marker is None:
                raise RuntimeError("The simulator finished without a verified demo result.")
            result = json.loads(marker)
            demo = read_demo(Path(result["session_path"]), task_id)
            self.demos.upsert(demo)
            state = {"state": "complete", "task_id": task_id,
                     "result": {**result, "demo_id": demo.id}, "error": None}
        except Exception as exc:  # noqa: BLE001 - background failures must reach status polling
            state = {"state": "failed", "task_id": task_id,
                     "result": None, "error": str(exc)}
        with self._lock:
            self._state = state

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

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
        scene = self._scene_module()
        spec = scene.TaskSpec.from_dict(specification)
        if spec.prompt != task_prompt:
            raise ValueError(f"Local task instruction must be exactly: {spec.prompt}")
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError("Scene seed must be a nonnegative 32-bit integer.")
        with self._lock:
            if self._state["state"] == "recording":
                raise ValueError("Another simulator recording is already running.")
            self._state = {"state": "recording", "task_id": task_id,
                           "result": None, "error": None}
        Thread(target=self._run_scene_task, args=(task_id, spec.as_dict(), seed),
               daemon=True).start()
        return self.status()

    def _run_scene_task(self, task_id: str, specification: dict, seed: int) -> None:
        try:
            with TemporaryDirectory() as temporary:
                spec_path = Path(temporary) / "scene.json"
                spec_path.write_text(json.dumps(specification), encoding="utf-8")
                output = subprocess.run([sys.executable, str(_scene_script()), "--spec", str(spec_path),
                                         "--seed", str(seed), "--collect", "--output",
                                         str(self.demos_root)], capture_output=True, text=True,
                                        timeout=600, check=False)
                if output.returncode:
                    raise RuntimeError((output.stderr or output.stdout).strip()[-1200:])
            marker = next((line.removeprefix("SCENE_RESULT=") for line in output.stdout.splitlines()
                           if line.startswith("SCENE_RESULT=")), None)
            if marker is None:
                raise RuntimeError("The scene task finished without a verified demo result.")
            result = json.loads(marker)
            demo = read_demo(Path(result["session_path"]), task_id)
            self.demos.upsert(demo)
            state = {"state": "complete", "task_id": task_id,
                     "result": {**result, "demo_id": demo.id}, "error": None}
        except Exception as exc:  # noqa: BLE001 - background failures must reach status polling
            state = {"state": "failed", "task_id": task_id,
                     "result": None, "error": str(exc)}
        with self._lock:
            self._state = state
