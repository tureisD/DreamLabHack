"""Local Dream account setup; API keys never appear in read responses or logs."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from dream import DreamClient, credentials
from dream.errors import DreamError
from pydantic import BaseModel, Field, SecretStr


class AccountStatus(BaseModel):
    configured: bool
    source: str
    message: str
    dashboard_url: str = "https://platform.dreamlabs.ai/api-keys"


class AccountConnect(BaseModel):
    api_key: SecretStr = Field(min_length=12)


class WorkspaceItem(BaseModel):
    id: str
    name: str
    status: str


class AccountWorkspace(BaseModel):
    state: str
    message: str
    datasets: list[WorkspaceItem] = Field(default_factory=list)
    fine_tuning_jobs: list[WorkspaceItem] = Field(default_factory=list)
    models: list[WorkspaceItem] = Field(default_factory=list)


class AccountService:
    def __init__(self, validator: Callable[[str], object] | None = None,
                 path: Path | None = None) -> None:
        self.validator = validator or (lambda key: DreamClient(api_key=key).get_models())
        self.path = path or credentials.file_path()

    def status(self) -> AccountStatus:
        try:
            loaded = credentials.load()
        except DreamError:
            return AccountStatus(configured=False, source="invalid_credentials",
                                 message="The local Dream credentials file needs repair before connecting.")
        env_key = bool(os.getenv("DREAM_API_KEY", "").strip())
        source = "environment" if env_key else "credentials_file" if loaded.api_key else "missing"
        return AccountStatus(
            configured=bool(loaded.api_key), source=source,
            message=("A Dream API key is configured on this local server. This does not check browser sign-in; verify live API access before training."
                     if loaded.api_key else "Create a Dream API key on the platform, then connect it here."),
        )

    def connect(self, secret: SecretStr) -> AccountStatus:
        key = secret.get_secret_value().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,300}", key):
            raise ValueError("Enter the API key exactly as shown by Dream Labs.")
        if os.getenv("DREAM_API_KEY", "").strip():
            raise ValueError("DREAM_API_KEY is set in this server's environment and overrides the file. Remove it and restart the server before connecting a new key here.")
        try:
            self.validator(key)
        except DreamError as exc:
            raise ValueError("Dream Labs could not validate this key. Check the account, site, and key, then retry.") from exc
        path = self.path.expanduser()
        if path.is_symlink():
            raise ValueError("The credentials path is a symlink; configure the key outside this page.")
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        kept = [line for line in old.splitlines()
                if not re.match(r"^\s*(?:export\s+)?DREAM_API_KEY\s*=", line)]
        content = "\n".join([*kept, f"DREAM_API_KEY={key}"]) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=".coach-credentials-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return AccountStatus(configured=True, source="credentials_file",
                             message="Dream key validated and saved on this local server. Browser sign-in is separate.")
