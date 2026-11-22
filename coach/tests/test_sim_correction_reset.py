import json
from concurrent.futures import ThreadPoolExecutor
from subprocess import CompletedProcess
from threading import Event
from types import SimpleNamespace

import pytest

from teach_task_coach import sim_correction
from teach_task_coach.demos import Demo, DemoStore
from teach_task_coach.sim_correction import SimCorrectionService
from teach_task_coach.simulator_process import SimulatorProcessCancelled
from teach_task_coach.tasks import TaskInput, TaskStore

_PROMPT = "pick up the apple"


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sim_correction,
        "simulator_module",
        lambda: SimpleNamespace(
            seeded_env=lambda *_: SimpleNamespace(close=lambda: None),
            goal_from_clicks=lambda *_: SimpleNamespace(task_text=_PROMPT),
        ),
    )
    monkeypatch.setattr(
        SimCorrectionService,
        "_scene_module",
        staticmethod(lambda: SimpleNamespace(TaskSpec=SimpleNamespace(
            from_dict=lambda spec: SimpleNamespace(prompt=spec["prompt"], as_dict=lambda: spec),
        ))),
    )
    return SimCorrectionService(tmp_path / "demos", DemoStore(tmp_path))


@pytest.mark.parametrize("mode", ["fruit", "scene"])
def test_reset_cancels_active_recording_and_preserves_existing_demo(
    tmp_path, monkeypatch, recorder, mode,
):
    task = TaskStore(tmp_path).create_task(TaskInput(
        name="Apple pickup", prompt=_PROMPT, baseline_checkpoint="dreamlabs/dream-1-beta",
        success_rule="Lift the apple.",
    ))
    folder = tmp_path / "demos" / "saved"
    folder.mkdir(parents=True)
    demo = Demo(
        id="saved", task_id=task.id, task_text=task.prompt, source_path=str(folder),
        codebase_version="v2.1", frames=1, fps=10, camera_keys=[], state_dim=None,
        action_dim=None, findings=[],
    )
    recorder.demos.upsert(demo)
    started = Event()
    stopped = Event()

    def render(args, *, timeout, cancel):
        assert "--preview" not in args
        started.set()
        assert cancel.wait(3)
        stopped.set()
        if mode == "scene":
            return CompletedProcess(args, 0, "SCENE_RESULT=" + json.dumps({
                "session_path": str(tmp_path / "late-demo"),
            }), "")
        raise SimulatorProcessCancelled()

    monkeypatch.setattr(sim_correction, "run_simulator_process", render)
    monkeypatch.setattr(
        sim_correction, "read_demo",
        lambda path, task_id: demo.model_copy(update={"id": "late", "source_path": str(path)}),
    )
    if mode == "fruit":
        status = recorder.start(task.id, task.prompt, "lift", "apple", 1, (0, 0), None)
    else:
        status = recorder.start_scene_task(task.id, task.prompt, {"prompt": task.prompt}, 1)
    assert status["state"] == "recording"
    assert started.wait(3)

    recorder.reset_session()

    assert stopped.is_set()
    assert recorder.status() == {"state": "idle", "result": None, "error": None}
    assert recorder.demos.list(task.id) == [demo]
    assert folder.is_dir()


def test_reset_rejects_a_recording_validated_under_previous_session(monkeypatch, recorder):
    validating = Event()
    release = Event()

    def goal_from_clicks(*_):
        validating.set()
        assert release.wait(3)
        return SimpleNamespace(task_text=_PROMPT)

    monkeypatch.setattr(
        sim_correction,
        "simulator_module",
        lambda: SimpleNamespace(
            seeded_env=lambda *_: SimpleNamespace(close=lambda: None),
            goal_from_clicks=goal_from_clicks,
        ),
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(recorder.start, "task", _PROMPT, "lift", "apple", 1, (0, 0), None)
        try:
            assert validating.wait(3)
            recorder.reset_session()
        finally:
            release.set()
        with pytest.raises(ValueError, match="simulator session changed"):
            response.result(timeout=3)

    assert recorder.status()["state"] == "idle"


def test_reset_times_out_without_allowing_overlapping_recording(monkeypatch, recorder):
    started = Event()
    release = Event()

    def render(args, *, timeout, cancel):
        started.set()
        assert release.wait(3)
        assert cancel.is_set()
        raise SimulatorProcessCancelled()

    monkeypatch.setattr(sim_correction, "run_simulator_process", render)
    monkeypatch.setattr(sim_correction, "_RESET_TIMEOUT_S", 0.01)
    recorder.start("task", _PROMPT, "lift", "apple", 1, (0, 0), None)
    assert started.wait(3)
    try:
        with pytest.raises(TimeoutError, match="still stopping"):
            recorder.reset_session()
        with pytest.raises(ValueError, match="already running"):
            recorder.start("task", _PROMPT, "lift", "apple", 2, (0, 0), None)
    finally:
        release.set()
    monkeypatch.setattr(sim_correction, "_RESET_TIMEOUT_S", 3)
    recorder.reset_session()
    assert recorder.status()["state"] == "idle"
