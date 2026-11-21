import json
from io import BytesIO

import pytest

from teach_task_coach.scene import SceneAdapter
from teach_task_coach.tasks import HeldoutScene


def test_scene_adapter_only_calls_local_fixture_with_manifest(monkeypatch):
    with pytest.raises(ValueError, match="local HTTP"):
        SceneAdapter("https://remote.example")
    adapter = SceneAdapter("http://127.0.0.1:9999")
    calls = []

    class Response:
        def __enter__(self):
            return BytesIO(b'{"placed": true, "detail": "Object placed"}')

        def __exit__(self, *_args):
            return None

    def fake_urlopen(call, timeout):
        calls.append((call, timeout))
        return Response()

    monkeypatch.setattr("teach_task_coach.scene.request.urlopen", fake_urlopen)
    scene = HeldoutScene(
        task_id="task", scene_index=3, start_cell=3,
        x_fraction=0.4, y_fraction=0.7, angle_deg=90,
    )
    assert adapter.place(scene).placed is True
    call, timeout = calls[0]
    assert call.full_url == "http://127.0.0.1:9999/place"
    assert json.loads(call.data)["x_fraction"] == 0.4
    assert timeout == 45
