"""Optional local fixture interface for placing held-out evaluation scenes."""

from __future__ import annotations

import json
import os
from urllib import request
from urllib.parse import urlsplit

from pydantic import BaseModel

from teach_task_coach.tasks import HeldoutScene


class PlacementResult(BaseModel):
    placed: bool
    detail: str


class SceneAdapter:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.getenv("COACH_SCENE_ADAPTER_URL", "")
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
                raise ValueError("Scene adapter must be a local HTTP service.")

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def place(self, scene: HeldoutScene) -> PlacementResult:
        if not self.configured:
            raise ValueError("Set COACH_SCENE_ADAPTER_URL for a physical scene fixture.")
        payload = json.dumps(scene.model_dump()).encode("utf-8")
        call = request.Request(
            self.base_url.rstrip("/") + "/place", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with request.urlopen(call, timeout=45) as response:
            result = PlacementResult.model_validate(json.load(response))
        if not result.placed:
            raise ValueError(result.detail)
        return result
