"""Exercise request accounting with a simulated Dream policy and no network calls."""

from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from dream.errors import DreamSessionExpired


@pytest.fixture
def controller(monkeypatch):
    pytest.importorskip("mujoco")
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "dream_library/examples/yam_mujoco")
    )
    import dream_control

    def capture(env, windows, keep=True):
        if keep:
            for window in windows.values():
                window.append("frame")

    monkeypatch.setattr(dream_control, "settings", lambda: {"DREAM_API_KEY": "fixture"})
    monkeypatch.setattr(dream_control, "capture", capture)
    monkeypatch.setattr(dream_control, "observation", lambda *args: {})
    monkeypatch.setattr(dream_control, "feed", Mock())
    monkeypatch.setattr(dream_control, "RunViewerSync", Mock())
    monkeypatch.setattr(
        dream_control, "time",
        SimpleNamespace(monotonic=monotonic, sleep=lambda seconds: sleep(min(0.001, seconds))),
    )
    action_rows = [(0,) * 7] * 48
    monkeypatch.setattr(dream_control, "validate_chunk", lambda *args, **kwargs: (action_rows, action_rows))
    policy = Mock()
    monkeypatch.setattr(dream_control, "open_policy", lambda *args: policy)
    env = SimpleNamespace(state=lambda: {"left": (), "right": ()}, step=Mock())

    def run(progress):
        return dream_control.main(
            ["--headless", "--max-requests", "12"],
            shared_env=env, collision_view=object(), progress=progress,
        )

    return run, policy


def test_session_replacements_leave_all_twelve_action_requests_available(controller):
    run, policy = controller
    replacement = DreamSessionExpired("fixture session replaced", reason="expired")
    policy.get_action.side_effect = [None, replacement] * 6 + [None] * 6
    progress = {}

    assert run(progress) == 12 * 48
    assert progress == {
        "warmup_rows": 33,
        "requests_attempted": 18,
        "model_action_rows": 576,
        "session_replacements": 6,
        "last_session_replacement_reason": "expired",
    }
    policy.close.assert_called_once()


@pytest.mark.parametrize(
    ("responses", "expected_attempts", "expected_replacements"),
    [(["replacement"] * 4, 4, 4), (["replacement", "replacement", None] * 6 + ["replacement"], 19, 13)],
)
def test_replacement_retries_stop_at_their_own_limits(
    controller, responses, expected_attempts, expected_replacements
):
    run, policy = controller
    replacement = DreamSessionExpired("fixture session replaced", reason="serve_died")
    policy.get_action.side_effect = [replacement if response else None for response in responses]
    progress = {}

    with pytest.raises(DreamSessionExpired):
        run(progress)

    assert progress["requests_attempted"] == expected_attempts
    assert progress["session_replacements"] == expected_replacements
    assert progress["last_session_replacement_reason"] == "serve_died"
    policy.close.assert_called_once()
