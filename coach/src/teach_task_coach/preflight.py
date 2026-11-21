"""Check the two existing systems without moving the robot or creating FaaS work."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Literal

from dream import DreamClient
from dream.errors import DreamAuthError, DreamConfigError, DreamError, DreamProtocolError
from pydantic import BaseModel

from teach_task_coach.station import StationClient, StationUnavailable


class Check(BaseModel):
    state: Literal["ready", "blocked", "unavailable"]
    message: str


class ModelSummary(BaseModel):
    id: str
    owner: str
    embodiment: str | None
    servable: bool
    cameras: list[str] | None


class StationSummary(BaseModel):
    state: str
    checkpoint: str | None
    prompt: str | None
    arms: dict[str, bool]
    cameras_age_s: dict[str, float | None]
    last_error: dict[str, Any] | None


class PreflightResult(BaseModel):
    station: Check
    dream: Check
    station_status: StationSummary | None
    models: list[ModelSummary]


def _load_models() -> list[Any]:
    return DreamClient().get_models()


class PreflightService:
    def __init__(
        self,
        station: StationClient | None = None,
        model_loader: Callable[[], list[Any]] = _load_models,
    ) -> None:
        self.station = station or StationClient(
            base_url=os.getenv("COACH_STATION_URL", "http://127.0.0.1:8091")
        )
        self.model_loader = model_loader

    def run(self) -> PreflightResult:
        station_check, station_status = self._check_station()
        dream_check, models = self._check_dream()
        return PreflightResult(
            station=station_check,
            dream=dream_check,
            station_status=station_status,
            models=models,
        )

    def _check_station(self) -> tuple[Check, StationSummary | None]:
        try:
            status = self.station.status()
        except StationUnavailable:
            return Check(state="unavailable", message="Station unavailable at the configured URL."), None

        state = status["state"]
        arms = status.get("arms") or {}
        cameras = status.get("cameras") or {}
        summary = StationSummary(
            state=state,
            checkpoint=status.get("checkpoint"),
            prompt=status.get("prompt"),
            arms=arms,
            cameras_age_s=cameras,
            last_error=status.get("last_error"),
        )
        if state != "idle":
            return Check(state="blocked", message=f"Station is {state}."), summary
        if not arms:
            return Check(state="blocked", message="Station reported no robot arms."), summary
        if any(not available for available in arms.values()):
            return Check(state="blocked", message="One or more robot arms are unavailable."), summary
        if not cameras:
            return Check(state="blocked", message="Station reported no cameras."), summary
        if any(age is None or age > 2 for age in cameras.values()):
            return Check(state="blocked", message="A camera has no recent frame."), summary
        return Check(state="ready", message="Station is idle and responding."), summary

    def _check_dream(self) -> tuple[Check, list[ModelSummary]]:
        try:
            models = self.model_loader()
        except DreamAuthError:
            message = "Dream Labs rejected the configured API key."
        except DreamConfigError:
            message = "Configure DREAM_API_KEY or ~/.dreamlabs/credentials to list checkpoints."
        except DreamProtocolError:
            message = "Could not reach Dream Labs to list checkpoints."
        except DreamError:
            message = "Dream Labs could not list checkpoints."
        else:
            return (
                Check(state="ready", message=f"Found {len(models)} accessible checkpoints."),
                [
                    ModelSummary(
                        id=model.id,
                        owner=model.owner,
                        embodiment=model.embodiment,
                        servable=model.servable,
                        cameras=model.cameras,
                    )
                    for model in models
                ],
            )
        return Check(state="unavailable", message=message), []
