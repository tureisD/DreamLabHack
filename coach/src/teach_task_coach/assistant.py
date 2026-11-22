"""Read-only workflow assistant with an optional opt-in language-model answer."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, ValidationError

_session_ai_key: str | None = None


def _credential_path() -> Path:
    return Path(os.getenv("COACH_AI_CREDENTIALS", str(Path.home() / ".dreamlabs" / "coach-ai-key.dpapi"))).expanduser()


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("Local AI credential encryption requires Windows; use OPENAI_API_KEY on this system.")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    source = ctypes.create_string_buffer(data)
    input_blob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = Blob()
    operation = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not operation(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def _stored_ai_key() -> str | None:
    path = _credential_path()
    if not path.is_file() or path.is_symlink() or os.name != "nt":
        return None
    try:
        return _dpapi(path.read_bytes(), decrypt=True).decode("utf-8")
    except (OSError, ValueError, UnicodeError):
        return None


def _active_ai_key() -> str | None:
    return os.getenv("OPENAI_API_KEY", "").strip() or _session_ai_key or _stored_ai_key()


def _save_ai_key(key: str) -> None:
    if os.name != "nt":
        return
    path = _credential_path()
    if path.is_symlink():
        raise ValueError("The AI credential path is a symlink. Configure OPENAI_API_KEY instead.")
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _dpapi(key.encode("utf-8"), decrypt=False)
    descriptor, temporary = tempfile.mkstemp(prefix=".coach-ai-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class AiStatus(BaseModel):
    configured: bool
    source: str


class AiConnect(BaseModel):
    api_key: SecretStr = Field(min_length=20, max_length=300)


def ai_status() -> AiStatus:
    return AiStatus(configured=bool(_active_ai_key()),
                    source="environment" if os.getenv("OPENAI_API_KEY") else
                    "session" if _session_ai_key else "local_credential" if _stored_ai_key() else "missing")


def connect_ai(value: AiConnect) -> AiStatus:
    global _session_ai_key
    key = value.api_key.get_secret_value().strip()
    if not re.fullmatch(r"sk-[A-Za-z0-9_-]{17,297}", key):
        raise ValueError("Enter a valid OpenAI API key in the masked field.")
    request = urllib.request.Request("https://api.openai.com/v1/models",
                                     headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except (OSError, ValueError) as exc:
        raise ValueError("OpenAI could not validate this key. Check it and try again.") from exc
    _save_ai_key(key)
    _session_ai_key = key
    return ai_status()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(max_length=24)
    state: dict = Field(default_factory=dict)
    stage: Literal["introduction", "guide"] = "guide"


class TaskDraft(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=500)
    success_rule: str = Field(min_length=1, max_length=1000)


class ChatReply(BaseModel):
    message: str
    input_kind: Literal["text", "dream_key"] = "text"
    suggested_screen: Literal["preflight", "tasks", "demos", "training", "evaluation", "statistical"] | None = None
    task_draft: TaskDraft | None = None
    suggestions: list[str] = Field(default_factory=list, max_length=3)
    setup_help: Literal["robot", "simulator"] | None = None


def chat(value: ChatRequest) -> ChatReply:
    key = _active_ai_key()
    if not key:
        raise ValueError("Connect an AI provider before starting the chat.")
    for message in value.messages:
        if re.search(r"\b(?:dl_live_|sk-)[A-Za-z0-9_-]{12,}", message.content):
            raise ValueError("API keys must be entered in the masked key field, not the chat.")
    state = json.dumps(value.state, ensure_ascii=False)[:5000]
    transcript = [{"role": item.role, "content": item.content} for item in value.messages[-20:]]
    introduction = (
        "You are DreamCoach, a Dream-1 fine-tuning coach. This is the introduction BEFORE the user clicks Begin. "
        "Introduce yourself as DreamCoach. Explain your purpose: guide a beginner from a task idea through "
        "Dream connection, baseline, demonstrations, fine-tuning, and evaluation. State the end goal: a custom "
        "Dream-1 checkpoint with measured improvement on the user's task. Say that you will ask questions one "
        "at a time after they press Begin. Do not ask a question, request a key, mention setup instructions, "
        "or suggest a screen yet. Return JSON with input_kind=text, suggested_screen=null, task_draft=null, "
        "suggestions=[], setup_help=null."
    )
    guide = (
            "You are DreamCoach, the interactive Dream-1 fine-tuning coach. The user has clicked Begin. "
            "Conduct a conversation with a complete beginner. "
            "On the FIRST guide turn, inspect dream_api_ready in the app state. This means API access from "
            "the local server, NOT browser login; never claim the user is signed in to the Dream website. "
            "If false, ask them to open "
            "platform.dreamlabs.ai/api-keys, sign in, create a key, and enter it in the private field in the app. "
            "Do not ask about their robot or task until the Dream connection is ready or they explicitly want "
            "to discuss a robot-free path first. "
            "When Dream API access is ready, inspect dream_account_inventory. If it contains existing datasets "
            "or fine-tuning jobs, briefly say what you found, including the latest job's status, and ask whether "
            "the user wants to continue that work or start a new task. Do not invent a console task list. "
            "The bundled_example in state is a committed YAM apple-pickup experiment with two reviewed datasets, "
            "published 500-step checkpoints, and held-out simulator evaluations. If the user is working on apples, "
            "offer to inspect the existing Dream dataset/job/checkpoint and run the committed statistical audit "
            "BEFORE proposing any new demo collection or paid training. The bundled failure-conditioned simulator "
            "collector is already present, so do not ask whether the user has a simulator for this apple example. "
            "Describe fresh simulator collection as an optional next iteration, with setup_help=simulator. "
            "Help the user confirm a task draft in chat. There is no Tasks button. "
            "The chat's evaluation sidebar refreshes saved evaluation results automatically. "
            "Ask ONE concrete question at a time, tailored to the supplied live app state and the user's answers. "
            "Never request a list of details in one turn. If the user describes a goal in ordinary words, "
            "infer a short task name, precise robot instruction, and observable success rule yourself. Return "
            "task_draft immediately and ask the user to confirm or correct it. For apple-in-basket, a useful "
            "proposed rule is that the apple ends inside the basket, the gripper releases it, and it remains "
            "there for two seconds. Do not ask the user to invent a formal success rule when you can propose one. "
            "If a crucial detail is ambiguous, ask only about that detail and offer 2-3 concrete suggested "
            "answers in suggestions, such as plausible robot instructions. "
            "If Dream API access is unavailable, explain how to make a key on platform.dreamlabs.ai/api-keys and set "
            "input_kind=dream_key. Never ask for a key in ordinary chat. "
            "Use task_draft so the UI can offer a Save task confirmation. Guide the user through setup/preflight, "
            "baseline trials, collecting and reviewing demos, dataset creation, explicit paid FaaS submission, "
            "and paired held-out evaluation, in that order when feasible. If no physical robot, ask about a simulator "
            "and explain that new training data needs a recorder or simulator. Set setup_help=robot when "
            "robot/camera setup is needed, or setup_help=simulator when a robot-free user needs the YAM simulator "
            "setup. The current bundled simulator collector supports YAM apple pickup, not arbitrary tasks. "
            "There is NO simulator screen. If setup_help=simulator, tell the user to use the Prepare YAM simulator "
            "card that appears below this message; set suggested_screen=null there and never invent a screen "
            "or installation flow. "
            "Ground claims in state; do not claim "
            "you moved hardware, created data, submitted training, or proved improvement. Suggest a screen when "
            "the user needs to act there. Never take a paid or robot action yourself. Keep responses under 100 words. "
            "Return only JSON with message, input_kind, suggested_screen, task_draft, suggestions, setup_help."
    )
    payload = {
        "model": os.getenv("COACH_ASSISTANT_MODEL", "gpt-4.1-mini"),
        "instructions": introduction if value.stage == "introduction" else guide,
        "input": [{"role": "user", "content": f"Current app state: {state}"}, *transcript],
        "text": {"format": {"type": "json_schema", "name": "coach_turn", "strict": True,
                 "schema": {"type": "object", "additionalProperties": False, "properties": {
                     "message": {"type": "string"},
                     "input_kind": {"type": "string", "enum": ["text", "dream_key"]},
                     "suggested_screen": {"type": ["string", "null"], "enum": ["preflight", "tasks", "demos", "training", "evaluation", "statistical", None]},
                     "task_draft": {"type": ["object", "null"], "additionalProperties": False,
                                    "properties": {"name": {"type": "string"}, "prompt": {"type": "string"},
                                                   "success_rule": {"type": "string"}},
                                    "required": ["name", "prompt", "success_rule"]},
                     "suggestions": {"type": "array", "items": {"type": "string"}},
                     "setup_help": {"type": ["string", "null"], "enum": ["robot", "simulator", None]}},
                     "required": ["message", "input_kind", "suggested_screen", "task_draft", "suggestions", "setup_help"]}}},
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
        parsed = json.loads(result)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("message"), str) or not parsed["message"].strip():
            raise ValueError("The AI coach returned an empty turn.")
        if value.stage == "introduction":
            return ChatReply(message=parsed["message"].strip())
        try:
            draft = TaskDraft.model_validate(parsed["task_draft"]) if parsed.get("task_draft") else None
        except ValidationError:
            draft = None
        screen = parsed.get("suggested_screen")
        setup_help = parsed.get("setup_help") if parsed.get("setup_help") in ("robot", "simulator") else None
        if setup_help == "simulator" and screen == "tasks":
            screen = None
        return ChatReply(message=parsed["message"].strip(),
                         input_kind="dream_key" if parsed.get("input_kind") == "dream_key" else "text",
                         suggested_screen=screen if screen in ("preflight", "tasks", "demos", "training", "evaluation", "statistical") else None,
                         task_draft=draft,
                         suggestions=[item[:300] for item in (parsed.get("suggestions") or [])
                                      if isinstance(item, str) and item.strip()][:3],
                         setup_help=setup_help)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ValueError("The AI key was refused. Connect a valid OpenAI key and retry.") from exc
        if exc.code == 429:
            raise ValueError("The AI provider is rate limited or out of credit. Wait or check your API billing, then retry.") from exc
        if exc.code == 400:
            raise ValueError("The AI provider rejected this turn. Please retry or start a new chat.") from exc
        raise ValueError(f"The AI provider returned HTTP {exc.code}. Try again shortly.") from exc
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
            "You are DreamCoach, a guide to Dream-1 robot fine-tuning. Explain one safe next step "
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
