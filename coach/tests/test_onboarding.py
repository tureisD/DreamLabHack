"""Account connection and beginner guidance stay local unless AI is explicitly enabled."""

from fastapi.testclient import TestClient
from pydantic import SecretStr

from teach_task_coach.account import AccountService, AccountStatus
from teach_task_coach.api import create_app
from teach_task_coach.assistant import (
    AiConnect,
    AssistantQuestion,
    ChatMessage,
    ChatRequest,
    answer,
    chat,
    connect_ai,
)


def test_connect_validates_before_saving_and_never_returns_key(tmp_path, monkeypatch):
    path = tmp_path / "credentials"
    path.write_text("DREAM_API_URL=https://platform.dreamlabs.ai\nDREAM_API_KEY=old_key\n")
    monkeypatch.setenv("DREAM_CREDENTIALS", str(path))
    monkeypatch.delenv("DREAM_API_KEY", raising=False)
    seen = []
    service = AccountService(lambda key: seen.append(key), path)
    client = TestClient(create_app(account_service=service))
    status = client.post("/api/account/connect", json={"api_key": "dl_live_test_value_123"})
    assert status.status_code == 200
    assert status.json()["configured"] is True
    assert "dl_live_test_value_123" not in status.text
    assert seen == ["dl_live_test_value_123"]
    assert path.read_text().count("DREAM_API_KEY=") == 1
    assert "DREAM_API_URL=https://platform.dreamlabs.ai" in path.read_text()
    assert client.get("/api/account/status").json()["source"] == "credentials_file"


def test_invalid_key_and_environment_override_do_not_write(tmp_path, monkeypatch):
    path = tmp_path / "credentials"
    monkeypatch.delenv("DREAM_API_KEY", raising=False)
    service = AccountService(lambda _key: None, path)
    try:
        service.connect(SecretStr("bad key with spaces"))
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid key accepted")
    assert not path.exists()
    monkeypatch.setenv("DREAM_API_KEY", "environment_key")
    try:
        service.connect(SecretStr("dl_live_test_value_123"))
    except ValueError as exc:
        assert "overrides" in str(exc)
    else:
        raise AssertionError("Environment override accepted")
    assert not path.exists()


def test_guided_assistant_does_not_need_or_use_external_api(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = answer(AssistantQuestion(
        question="How do I record my first demo?", phase="collect",
        next_action="Record a failure-position demo.", allow_external_ai=True,
    ))
    assert response.mode == "guided"
    assert response.external_ai_available is False
    assert "Demonstrations" in response.answer


def test_external_ai_requires_opt_in_and_parses_text(monkeypatch):
    import io
    import json

    from teach_task_coach import assistant

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_open(request, timeout):
        calls.append((request, timeout))
        return Response(json.dumps({"output": [{"content": [
            {"type": "output_text", "text": "Record one failure example, then review it."}
        ]}]}).encode())

    monkeypatch.setattr(assistant.urllib.request, "urlopen", fake_open)
    question = AssistantQuestion(question="What do I record?", phase="collect", next_action="Record a demo")
    assert answer(question).mode == "guided"
    assert not calls
    answer_ai = answer(question.model_copy(update={"allow_external_ai": True}))
    assert answer_ai.mode == "ai"
    assert "failure example" in answer_ai.answer
    assert len(calls) == 1
    assert b"test-only-key" not in calls[0][0].data


def test_chat_asks_model_for_next_turn_and_never_sends_credentials(monkeypatch):
    import io
    import json

    from teach_task_coach import assistant

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-only-key")
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_open(request, timeout):
        calls.append((request, timeout))
        result = {"message": "What task should the robot learn?", "input_kind": "text",
                  "suggested_screen": None, "task_draft": None}
        return Response(json.dumps({"output": [{"content": [
            {"type": "output_text", "text": json.dumps(result)}
        ]}]}).encode())

    monkeypatch.setattr(assistant.urllib.request, "urlopen", fake_open)
    result = chat(ChatRequest(messages=[ChatMessage(role="user", content="I have a SO-101 robot")],
                              state={"dream_connected": False}))
    assert result.message == "What task should the robot learn?"
    payload = json.loads(calls[0][0].data)
    assert payload["store"] is False
    assert "sk-test-only-key" not in json.dumps(payload)
    assert payload["input"][-1]["content"] == "I have a SO-101 robot"


def test_introduction_has_no_action_before_begin(monkeypatch):
    from teach_task_coach import assistant

    def unexpected_remote_call(*_args, **_kwargs):
        raise AssertionError("The welcome should be available without an AI provider request.")

    monkeypatch.setattr(assistant, "_active_ai_key", unexpected_remote_call)
    monkeypatch.setattr(assistant.urllib.request, "urlopen", unexpected_remote_call)
    result = chat(ChatRequest(stage="introduction", messages=[], state={"dream_connected": False}))
    assert "Press Begin" in result.message
    assert "without a physical robot" in result.message
    assert "held-out scenes" in result.message
    assert "misses to choose your next demos" in result.message
    assert result.input_kind == "text"
    assert result.suggested_screen is None
    assert result.setup_help is None


def test_connected_workspace_reads_only_account_inventory():
    from types import SimpleNamespace

    class Account:
        def status(self):
            return AccountStatus(configured=True, source="credentials_file", message="Connected")

    class Gateway:
        def datasets(self):
            return [SimpleNamespace(id="ds_1", name="alice/apple", status="processed")]

        def finetunes(self):
            return [{"id": "ftj_1", "dataset": "alice/apple", "status": "running", "api_key": "secret"}]

        @property
        def client(self):
            return SimpleNamespace(get_models=lambda: [SimpleNamespace(id="dream-1-ft:apple", servable=False)])

    response = TestClient(create_app(account_service=Account(), dream_gateway=Gateway())).get("/api/account/workspace")
    assert response.status_code == 200
    assert response.json()["fine_tuning_jobs"][0]["status"] == "running"
    assert response.json()["datasets"][0]["name"] == "alice/apple"
    assert "secret" not in response.text


def test_chat_rejects_keys_in_transcript_and_ai_key_stays_local(monkeypatch, tmp_path):
    from teach_task_coach import assistant

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("COACH_AI_CREDENTIALS", str(tmp_path / "coach-ai-key.dpapi"))
    monkeypatch.setattr(assistant, "_session_ai_key", None)
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(assistant.urllib.request, "urlopen", lambda request, timeout: seen.append(request) or Response())
    status = connect_ai(AiConnect(api_key="sk-test-key_1234567890123456"))
    assert status.configured and status.source == "session"
    if assistant.os.name == "nt":
        encrypted = (tmp_path / "coach-ai-key.dpapi").read_bytes()
        assert b"sk-test-key" not in encrypted
        monkeypatch.setattr(assistant, "_session_ai_key", None)
        assert assistant.ai_status().source == "local_credential"
    assert len(seen) == 1
    try:
        chat(ChatRequest(messages=[ChatMessage(role="user", content="dl_live_abc1234567890123456")]))
    except ValueError as exc:
        assert "masked" in str(exc)
    else:
        raise AssertionError("Dream key was accepted into chat")
    assert len(seen) == 1


def test_chat_offers_simulator_card_and_task_draft(monkeypatch):
    import io
    import json

    from teach_task_coach import assistant

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-only-key")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    result = {"message": "Use the bundled YAM setup card.", "input_kind": "text",
              "suggested_screen": "tasks", "setup_help": "simulator",
              "suggestions": ["Use the existing dataset"],
              "task_draft": {"name": "Apple in basket", "prompt": "Put the apple in the basket.",
                             "success_rule": "Apple remains in the basket after release for two seconds."}}
    monkeypatch.setattr(assistant.urllib.request, "urlopen", lambda request, timeout: Response(
        json.dumps({"output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}]}).encode()))
    reply = chat(ChatRequest(messages=[ChatMessage(role="user", content="Where is the simulator?")]))
    assert reply.setup_help == "simulator"
    assert reply.suggested_screen is None
    assert reply.suggestions == ["Use the existing dataset"]
    assert reply.task_draft and "two seconds" in reply.task_draft.success_rule
