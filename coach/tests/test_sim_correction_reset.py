import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
            stage = Path(args[args.index("--output") + 1])
            demo_folder = stage / "late-demo"
            demo_folder.mkdir()
            return CompletedProcess(args, 0, "SCENE_RESULT=" + json.dumps({
                "session_path": str(demo_folder),
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
    assert [path.name for path in folder.parent.iterdir()] == ["saved"]
    assert not list(tmp_path.glob("yam-recording-*"))


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


def test_recording_is_published_to_the_demo_directory_after_validation(tmp_path, monkeypatch, recorder):
    task = TaskStore(tmp_path).create_task(TaskInput(
        name="Apple pickup", prompt=_PROMPT, baseline_checkpoint="dreamlabs/dream-1-beta",
        success_rule="Lift the apple.",
    ))

    def render(args, *, timeout, cancel):
        output = Path(args[args.index("--output") + 1])
        assert output.parent == tmp_path.resolve()
        assert output != recorder.demos_root
        folder = output / "new-demo"
        folder.mkdir()
        return CompletedProcess(args, 0, "CLICK_RESULT=" + json.dumps({"session_path": str(folder)}), "")

    def read_demo(path, task_id):
        assert not (recorder.demos_root / path.name).exists()
        return Demo(
            id="demo", task_id=task_id, source_path=str(path), task_text=_PROMPT,
            codebase_version="v2.1", frames=1, fps=10, camera_keys=[], state_dim=None,
            action_dim=None, findings=[],
        )

    monkeypatch.setattr(sim_correction, "run_simulator_process", render)
    monkeypatch.setattr(sim_correction, "read_demo", read_demo)
    recorder.start(task.id, _PROMPT, "lift", "apple", 1, (0, 0), None)
    with recorder._lock:
        recording = recorder._recording
    if recording:
        recording[0].join(timeout=3)

    final = recorder.demos_root / "new-demo"
    state = recorder.status()
    assert state["state"] == "complete", state
    assert state["result"] == {"session_path": str(final), "demo_id": "demo"}
    assert final.is_dir()
    assert recorder.demos.list(task.id)[0].source_path == str(final)
    assert not list(tmp_path.glob("yam-recording-*"))


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
