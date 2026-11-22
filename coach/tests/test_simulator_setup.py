"""The bundled simulator has a real, checkable setup action."""

from fastapi.testclient import TestClient

from teach_task_coach.api import create_app
from teach_task_coach.simulator_setup import SimulatorSetup


def test_simulator_status_checks_dependencies_and_bundled_scripts(tmp_path, monkeypatch):
    setup = SimulatorSetup(tmp_path)
    assert setup.status().state == "missing"
    scripts = tmp_path / "experiments/yam_sim_faas"
    scripts.mkdir(parents=True)
    (scripts / "record_yam_demos.py").write_text("")
    (scripts / "collect_failure_demos.py").write_text("")
    monkeypatch.setattr("teach_task_coach.simulator_setup.importlib.util.find_spec", lambda name: object())
    client = TestClient(create_app(simulator_setup=setup))
    assert client.get("/api/simulator/status").json()["state"] == "ready"
    assert client.post("/api/simulator/prepare").json()["state"] == "ready"
