from types import SimpleNamespace

from fastapi.testclient import TestClient

from teach_task_coach.api import create_app
from teach_task_coach.preflight import PreflightService
from teach_task_coach.station import StationUnavailable


class FakeStation:
    def __init__(self, status=None, fails=False):
        self.value = status
        self.fails = fails

    def status(self):
        if self.fails:
            raise StationUnavailable("offline")
        return self.value


def status(**changes):
    value = {
        "state": "idle",
        "checkpoint": "dreamlabs/dream-1-beta",
        "prompt": "put block in bin",
        "arms": {"left": True, "right": True},
        "cameras": {"overhead": 0.1, "wrist_l": 0.2},
        "last_error": None,
    }
    value.update(changes)
    return value


def test_healthy_preflight_lists_accessible_models():
    model = SimpleNamespace(
        id="dreamlabs/dream-1-beta",
        owner="public",
        embodiment="yam",
        servable=True,
        cameras=["overhead", "wrist_l"],
    )
    client = TestClient(create_app(PreflightService(FakeStation(status()), lambda: [model])))

    response = client.get("/api/preflight")

    assert response.status_code == 200
    assert response.json()["station"]["state"] == "ready"
    assert response.json()["dream"]["state"] == "ready"
    assert response.json()["models"][0]["id"] == model.id
    assert response.json()["station_status"]["checkpoint"] == model.id


def test_busy_station_does_not_hide_model_access():
    result = PreflightService(FakeStation(status(state="running")), list).run()

    assert result.station.state == "blocked"
    assert result.dream.state == "ready"


def test_stale_camera_blocks_robot_readiness():
    result = PreflightService(FakeStation(status(cameras={"overhead": 3.1})), list).run()

    assert result.station.state == "blocked"
    assert "camera" in result.station.message.lower()


def test_station_and_dream_fail_independently():
    from dream.errors import DreamConfigError

    def no_credentials():
        raise DreamConfigError("secret must not be returned")

    result = PreflightService(FakeStation(fails=True), no_credentials).run()

    assert result.station.state == "unavailable"
    assert result.dream.state == "unavailable"
    assert "secret" not in result.model_dump_json()
