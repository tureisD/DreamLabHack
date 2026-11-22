"""Read-only workflow assistant with an optional opt-in language-model answer."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Literal

from pydantic import BaseModel, Field

_session_ai_key: str | None = None


class AiStatus(BaseModel):
    configured: bool
    source: str


class AiConnect(BaseModel):
    api_key: str = Field(min_length=20, max_length=300)


def ai_status() -> AiStatus:
    return AiStatus(configured=bool(os.getenv("OPENAI_API_KEY") or _session_ai_key),
                    source="environment" if os.getenv("OPENAI_API_KEY") else
                    "session" if _session_ai_key else "missing")


def connect_ai(value: AiConnect) -> AiStatus:
    global _session_ai_key
    key = value.api_key.strip()
    if not re.fullmatch(r"sk-[A-Za-z0-9_-]{17,297}", key):
        raise ValueError("Enter a valid OpenAI API key in the masked field.")
    request = urllib.request.Request("https://api.openai.com/v1/models",
                                     headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except (OSError, ValueError) as exc:
        raise ValueError("OpenAI could not validate this key. Check it and try again.") from exc
    _session_ai_key = key
    return ai_status()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(max_length=24)
    state: dict = Field(default_factory=dict)


class TaskDraft(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=500)
    success_rule: str = Field(min_length=1, max_length=1000)


class ChatReply(BaseModel):
    message: str
    input_kind: Literal["text", "dream_key"] = "text"
    suggested_screen: Literal["preflight", "tasks", "demos", "training", "evaluation", "statistical"] | None = None
    task_draft: TaskDraft | None = None


def chat(value: ChatRequest) -> ChatReply:
    key = os.getenv("OPENAI_API_KEY", "").strip() or _session_ai_key
    if not key:
        raise ValueError("Connect an AI provider before starting the chat.")
    for message in value.messages:
        if re.search(r"\b(?:dl_live_|sk-)[A-Za-z0-9_-]{12,}", message.content):
            raise ValueError("API keys must be entered in the masked key field, not the chat.")
    state = json.dumps(value.state, ensure_ascii=False)[:5000]
    transcript = [{"role": item.role, "content": item.content} for item in value.messages[-20:]]
    payload = {
        "model": os.getenv("COACH_ASSISTANT_MODEL", "gpt-4.1-mini"),
        "instructions": (
            "You are the interactive Dream-1 fine-tuning coach. Conduct a conversation with a complete beginner. "
            "Ask ONE concrete question at a time, tailored to the supplied live app state and the user's answers. "
            "Never request a list of details in one turn. For a new task, ask for the task name first; "
            "after the user answers, ask for the exact robot instruction; then ask for one observable success rule. "
            "Start by learning what task and hardware/simulator they have. If Dream is disconnected, explain how to "
            "make a key on platform.dreamlabs.ai and set input_kind=dream_key. Never ask for a key in ordinary chat. "
            "For a task, gather a short name, an exact robot instruction, and an observable success rule; then "
            "return task_draft so the UI can offer a Save task confirmation. Guide the user through setup/preflight, "
            "baseline trials, collecting and reviewing demos, dataset creation, explicit paid FaaS submission, "
            "and paired held-out evaluation, in that order when feasible. If no physical robot, ask about a simulator "
            "and explain that new training data needs a recorder or simulator. Ground claims in state; do not claim "
            "you moved hardware, created data, submitted training, or proved improvement. Suggest a screen when "
            "the user needs to act there. Never take a paid or robot action yourself. Keep responses under 100 words. "
            "Return only JSON with message, input_kind, suggested_screen, task_draft."
        ),
        "input": [{"role": "user", "content": f"Current app state: {state}"}, *transcript],
        "text": {"format": {"type": "json_schema", "name": "coach_turn", "strict": True,
                 "schema": {"type": "object", "additionalProperties": False, "properties": {
                     "message": {"type": "string"},
                     "input_kind": {"type": "string", "enum": ["text", "dream_key"]},
                     "suggested_screen": {"type": ["string", "null"], "enum": ["preflight", "tasks", "demos", "training", "evaluation", "statistical", None]},
                     "task_draft": {"type": ["object", "null"], "additionalProperties": False,
                                    "properties": {"name": {"type": "string"}, "prompt": {"type": "string"},
                                                   "success_rule": {"type": "string"}},
                                    "required": ["name", "prompt", "success_rule"]}},
                     "required": ["message", "input_kind", "suggested_screen", "task_draft"]}}},
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        result = "".join(part.get("text", "") for item in data.get("output", [])
                         for part in item.get("content", []) if part.get("type") == "output_text")
        return ChatReply.model_validate_json(result)
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError("The AI coach could not respond. Check the AI key and try again.") from exc


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    phase: str = Field(max_length=60)
    next_action: str = Field(max_length=1000)
    allow_external_ai: bool = False


class AssistantAnswer(BaseModel):
    answer: str
    mode: str
    external_ai_available: bool


def local_answer(value: AssistantQuestion) -> str:
    question = value.question.lower()
    if any(word in question for word in ("key", "account", "connect", "login")):
        return ("Open the Dream Labs platform, sign in, create an API key in your account settings, "
                "then paste it into Connect Dream account. The coach validates it and saves it only "
                "in the local Dream SDK credentials file.")
    if any(word in question for word in ("demo", "data", "record", "teleop")):
        return ("First define a task and measure a few baseline runs. In Demonstrations, record one "
                "supervised example at a failure position or import a LeRobot recording. Review its "
                "camera views and motion, mark Keep or Redo, and repeat where coverage is missing.")
    if any(word in question for word in ("train", "fine", "faas", "cost", "step")):
        return ("Once kept demonstrations cover the observed failures, create a dataset version "
                "in Training and run the local worker to validate it. Review the step count and "
                "Dream account charges before explicitly submitting a paid fine-tune.")
    if any(word in question for word in ("eval", "result", "better", "success")):
        return ("Plan the comparison before testing the candidate. Run base and candidate on "
                "the same held-out scenes, label every attempt, then save the paired audit. "
                "Only an audited improvement can be promoted.")
    if any(word in question for word in ("robot", "simulat", "hardware", "camera")):
        return ("Check Preflight first. A missing station or stale camera needs a setup fix. "
                "Without a robot, you can inspect the included simulator evaluation demo, "
                "but collecting new task demonstrations needs a recorder or simulator setup.")
    return (f"Your current step is {value.phase or 'getting started'}. "
            f"Next: {value.next_action or 'Connect Dream Labs and define a task.'} "
            "Ask about account setup, recording data, fine-tuning, or evaluating a result for details.")


def answer(value: AssistantQuestion) -> AssistantAnswer:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not value.allow_external_ai or not key:
        return AssistantAnswer(answer=local_answer(value), mode="guided",
                               external_ai_available=bool(key))
    payload = {
        "model": os.getenv("COACH_ASSISTANT_MODEL", "gpt-4.1-mini"),
        "instructions": (
            "You are a concise beginner coach for Dream-1 robot fine-tuning. Explain one safe next step "
            "using only the supplied workflow state. Never claim to have moved a robot, uploaded a dataset, "
            "started paid training, verified an API key, or proven an improvement. Do not ask the user to "
            "paste secrets into chat. If unsure, say what to check in the app. Max 140 words."
        ),
        "input": (f"Current phase: {value.phase}\nSuggested next action: {value.next_action}\n"
                  f"User question: {value.question}"),
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        text = "\n".join(part.get("text", "") for item in data.get("output", [])
                         for part in item.get("content", []) if part.get("type") == "output_text")
        if text.strip():
            return AssistantAnswer(answer=text.strip(), mode="ai", external_ai_available=True)
    except (OSError, ValueError, KeyError):
        pass
    return AssistantAnswer(answer=local_answer(value) + " The optional AI service is unavailable.",
                           mode="guided", external_ai_available=True)
