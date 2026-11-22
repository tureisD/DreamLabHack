import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from teach_task_coach.hosted import create_gateway, workspace_environment


def test_workspace_workers_use_distinct_simulator_and_api_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAM_API_KEY", "host-only-placeholder")
    monkeypatch.setenv("OPENAI_API_KEY", "host-only-placeholder")
    verified = []
    origin = "http://127.0.0.1:8765"
    app = create_gateway(tmp_path, origin, workspace_limit=2, validator=verified.append)

    async def exercise_two_browsers():
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url=origin) as alice,
            httpx.AsyncClient(transport=transport, base_url=origin) as bob,
        ):
            invalid = await alice.post("/hosted/workspace", json={"api_key": "fixture-dream-key-one"})
            assert invalid.status_code == 403
            assert (await alice.get("/api/tasks")).status_code == 401
            for client, key in ((alice, "fixture-dream-key-one"), (bob, "fixture-dream-key-two")):
                connected = await client.post("/hosted/workspace", headers={"Origin": origin}, json={"api_key": key})
                assert connected.status_code == 201
                assert "HttpOnly" in connected.headers["set-cookie"]
                assert (await client.get("/api/account/status")).json()["configured"]
                assert not (await client.get("/api/assistant/status")).json()["configured"]
            assert verified == ["fixture-dream-key-one", "fixture-dream-key-two"]
            result = await alice.post("/api/tasks", headers={"Origin": origin}, json={
                "name": "Apple", "prompt": "pick up the apple", "baseline_checkpoint": "dreamlabs/dream-1-beta",
                "success_rule": "Hold the apple above the table.",
            })
            assert result.status_code == 201
            assert len((await alice.get("/api/tasks")).json()) == 1
            assert (await bob.get("/api/tasks")).json() == []
            assert (await bob.get(f"/api/tasks/{result.json()['id']}")).status_code == 404
            assert (await alice.get("/api/simulator/status")).json()["state"] == "ready"
            assert (await alice.get("/api/docs/apple-training")).status_code == 404
            assert (await alice.post("/api/trials/fake/start", headers={"Origin": origin})).status_code == 403
            assert (await alice.post("/api/tasks", headers={"Origin": "https://example.com"}, json={})).status_code == 403

    asyncio.run(exercise_two_browsers())


def test_workspace_env_and_https_cookie_are_private(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAM_API_KEY", "host-only-placeholder")
    monkeypatch.setenv("OPENAI_API_KEY", "host-only-placeholder")
    monkeypatch.setenv("COACH_STATION_URL", "http://host-machine:8091")
    env = workspace_environment(Path(tmp_path))
    assert "DREAM_API_KEY" not in env and "OPENAI_API_KEY" not in env
    assert env["COACH_STATION_URL"] == "http://127.0.0.1:1"
    assert Path(env["DREAM_YAM_CONFIG_DIR"]).parent == tmp_path
    origin = "https://dreamcoach.example"
    app = create_gateway(tmp_path, origin, validator=lambda _: None)
    with TestClient(app, base_url=origin) as client:
        response = client.post("/hosted/workspace", headers={"Origin": origin},
                               json={"api_key": "fixture-dream-key-only"})
        assert "__Host-dreamcoach=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        assert "fixture-dream-key-only" not in response.text
        assert client.get("/api/tasks", headers={"Host": "untrusted.example"}).status_code == 421
