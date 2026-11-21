"""HTTP API for the local coach UI."""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from teach_task_coach.episodes import EpisodeSummary, RolloutScanner
from teach_task_coach.preflight import PreflightResult, PreflightService
from teach_task_coach.storage import EpisodeStore


class ImportResult(BaseModel):
    imported: int
    skipped: list[str]


class EpisodeListItem(BaseModel):
    id: str
    task: str
    checkpoint: str
    status: str
    started_at_utc: str | None
    success: bool | None
    finding_count: int


class EpisodeLabel(BaseModel):
    success: bool | None
    failure_stage: Literal["approach", "grasp", "transport", "release", "other"] | None = None
    note: str | None = Field(default=None, max_length=2000)


def create_app(
    service: PreflightService | None = None,
    store: EpisodeStore | None = None,
    scanner: RolloutScanner | None = None,
) -> FastAPI:
    app = FastAPI(title="Teach it a task", version="0.1.0")
    preflight = service or PreflightService()
    episodes = store or EpisodeStore()
    rollouts = scanner or RolloutScanner()

    @app.get("/api/preflight", response_model=PreflightResult)
    def get_preflight() -> PreflightResult:
        return preflight.run()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/rollouts/import", response_model=ImportResult)
    def import_rollouts() -> ImportResult:
        found, skipped = rollouts.scan()
        for episode in found:
            episodes.upsert(episode)
        return ImportResult(imported=len(found), skipped=skipped)

    @app.get("/api/episodes", response_model=list[EpisodeListItem])
    def list_episodes() -> list[EpisodeListItem]:
        return [
            EpisodeListItem(
                id=episode.id,
                task=episode.task,
                checkpoint=episode.checkpoint,
                status=episode.status,
                started_at_utc=episode.started_at_utc,
                success=episode.success,
                finding_count=len(episode.findings),
            )
            for episode in episodes.list()
        ]

    @app.get("/api/episodes/{episode_id}", response_model=EpisodeSummary)
    def get_episode(episode_id: str) -> EpisodeSummary:
        episode = episodes.get(episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found.")
        return episode

    @app.get("/api/episodes/{episode_id}/video/{role}")
    def get_video(episode_id: str, role: str) -> FileResponse:
        episode = episodes.get(episode_id)
        path = None if episode is None else episode.videos.get(role)
        if (
            path is None
            or not Path(path).is_file()
            or not Path(path).resolve().is_relative_to(Path(episode.source_path).resolve())
        ):
            raise HTTPException(status_code=404, detail="Video not found.")
        return FileResponse(path, media_type="video/mp4")

    @app.post("/api/episodes/{episode_id}/label", response_model=EpisodeSummary)
    def label_episode(episode_id: str, label: EpisodeLabel) -> EpisodeSummary:
        episode = episodes.label(episode_id, label.success, label.failure_stage, label.note)
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found.")
        return episode

    return app


app = create_app()
