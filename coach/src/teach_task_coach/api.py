"""HTTP API for the local coach UI."""

from pathlib import Path
from typing import Literal

from dream.errors import DreamError
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from teach_task_coach.coverage import CoveragePlan, plan
from teach_task_coach.demos import Demo, DemoError, DemoScanner, DemoStore
from teach_task_coach.episodes import EpisodeSummary, RolloutScanner
from teach_task_coach.faas import (
    DatasetVersion,
    DreamGateway,
    FaaSStore,
    FineTuneRecord,
    FineTuneRequest,
)
from teach_task_coach.preflight import PreflightResult, PreflightService
from teach_task_coach.station import StationRejected, StationUnavailable
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import Task, TaskInput, TaskStore, Trial, TrialInput, TrialStateError
from teach_task_coach.trials import TrialError, TrialRunner


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


class TrialLabel(BaseModel):
    success: bool
    failure_stage: Literal["approach", "grasp", "transport", "release", "other"] | None = None
    note: str | None = Field(default=None, max_length=2000)


class AbandonReason(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class DemoDecision(BaseModel):
    decision: Literal["keep", "redo"]
    start_cell: int | None = Field(default=None, ge=0, le=8)
    note: str | None = Field(default=None, max_length=2000)


class DatasetRequest(BaseModel):
    embodiment_name: str = Field(min_length=3, max_length=140)


class EmbodimentSummary(BaseModel):
    name: str
    id: str | None
    video_roles: list[str]


def create_app(
    service: PreflightService | None = None,
    store: EpisodeStore | None = None,
    scanner: RolloutScanner | None = None,
    task_store: TaskStore | None = None,
    trial_runner: TrialRunner | None = None,
    demo_store: DemoStore | None = None,
    demo_scanner: DemoScanner | None = None,
    faas_store: FaaSStore | None = None,
    dream_gateway: DreamGateway | None = None,
) -> FastAPI:
    app = FastAPI(title="Teach it a task", version="0.1.0")
    preflight = service or PreflightService()
    episodes = store or EpisodeStore()
    rollouts = scanner or RolloutScanner()
    tasks = task_store or TaskStore(episodes.data_dir)
    runner = trial_runner or TrialRunner(tasks, episodes, preflight.station, rollouts)
    demos = demo_store or DemoStore(episodes.data_dir)
    recorder = demo_scanner or DemoScanner()
    faas = faas_store or FaaSStore(episodes.data_dir)
    dream = dream_gateway or DreamGateway()

    @app.get("/api/preflight", response_model=PreflightResult)
    def get_preflight() -> PreflightResult:
        return preflight.run()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend/dist"
    if (frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")

    @app.get("/", response_model=None)
    def frontend() -> FileResponse | dict[str, str]:
        index = frontend_dist / "index.html"
        return FileResponse(index) if index.is_file() else {"message": "Build coach/frontend first."}

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

    @app.post("/api/tasks", response_model=Task, status_code=201)
    def create_task(value: TaskInput) -> Task:
        return tasks.create_task(value)

    @app.get("/api/tasks", response_model=list[Task])
    def list_tasks() -> list[Task]:
        return tasks.list_tasks()

    @app.get("/api/tasks/{task_id}", response_model=Task)
    def get_task(task_id: str) -> Task:
        task = tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return task

    @app.post("/api/tasks/{task_id}/baseline-trials", response_model=Trial, status_code=201)
    def create_baseline_trial(task_id: str, value: TrialInput) -> Trial:
        try:
            return tasks.create_trial(task_id, value)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found.") from exc

    @app.get("/api/tasks/{task_id}/baseline-trials", response_model=list[Trial])
    def list_baseline_trials(task_id: str) -> list[Trial]:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return tasks.list_trials(task_id)

    @app.post("/api/trials/{trial_id}/start", response_model=Trial)
    def start_trial(trial_id: str) -> Trial:
        try:
            return runner.start(trial_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError, StationRejected) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/trials/{trial_id}/stop", response_model=Trial)
    def stop_trial(trial_id: str) -> Trial:
        try:
            return runner.stop(trial_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError, StationRejected) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/trials/{trial_id}/sync", response_model=Trial)
    def sync_trial(trial_id: str) -> Trial:
        try:
            return runner.sync(trial_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/trials/{trial_id}/reconcile", response_model=Trial)
    def reconcile_trial(trial_id: str) -> Trial:
        try:
            return runner.reconcile_start(trial_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/trials/{trial_id}/label", response_model=Trial)
    def label_trial(trial_id: str, label: TrialLabel) -> Trial:
        try:
            return runner.label(trial_id, label.success, label.failure_stage, label.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/trials/{trial_id}/abandon", response_model=Trial)
    def abandon_trial(trial_id: str, value: AbandonReason) -> Trial:
        try:
            return runner.abandon(trial_id, value.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/demos/import", response_model=ImportResult)
    def import_demos(task_id: str) -> ImportResult:
        task = tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        found, skipped = recorder.scan(task_id, task.prompt)
        imported = 0
        for demo in found:
            try:
                demos.upsert(demo)
            except DemoError as exc:
                skipped.append(f"{Path(demo.source_path).name}: {exc}")
            else:
                imported += 1
        return ImportResult(imported=imported, skipped=skipped)

    @app.get("/api/tasks/{task_id}/demos", response_model=list[Demo])
    def list_demos(task_id: str) -> list[Demo]:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return demos.list(task_id)

    @app.post("/api/demos/{demo_id}/decision", response_model=Demo)
    def decide_demo(demo_id: str, value: DemoDecision) -> Demo:
        demo = demos.get(demo_id)
        if demo is None:
            raise HTTPException(status_code=404, detail="Demo not found.")
        if value.decision == "keep":
            if value.start_cell is None:
                raise HTTPException(status_code=422, detail="Choose a start cell for a kept demo.")
            if not demo.valid:
                raise HTTPException(status_code=409, detail="Fix hard validation issues before keeping this demo.")
        result = demos.decide(demo_id, value.decision, value.start_cell, value.note)
        assert result is not None
        return result

    @app.get("/api/demos/{demo_id}/video/{role}")
    def get_demo_video(demo_id: str, role: str) -> FileResponse:
        demo = demos.get(demo_id)
        if demo is None:
            raise HTTPException(status_code=404, detail="Demo not found.")
        key = f"observation.images.{role}"
        if key not in demo.camera_keys:
            raise HTTPException(status_code=404, detail="Camera not found.")
        root = Path(demo.source_path).resolve()
        files = [
            path
            for path in (root / "videos").rglob("*.mp4")
            if key in path.parts and path.resolve().is_relative_to(root)
        ]
        if not files:
            raise HTTPException(status_code=404, detail="Video not found.")
        return FileResponse(files[0], media_type="video/mp4")

    @app.get("/api/tasks/{task_id}/demo-plan", response_model=CoveragePlan)
    def get_demo_plan(task_id: str) -> CoveragePlan:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return plan(task_id, tasks, episodes, demos)

    @app.get("/api/embodiments", response_model=list[EmbodimentSummary])
    def list_embodiments() -> list[EmbodimentSummary]:
        try:
            bodies = dream.embodiments()
        except DreamError as exc:
            raise HTTPException(
                status_code=503,
                detail="Could not list Dream embodiments. Check credentials and connectivity.",
            ) from exc
        return [
            EmbodimentSummary(
                name=body.name,
                id=body.id,
                video_roles=sorted(body.embodiment_config.get("video", {})),
            )
            for body in bodies
        ]

    @app.post("/api/tasks/{task_id}/datasets", response_model=DatasetVersion, status_code=201)
    def create_dataset_version(task_id: str, value: DatasetRequest) -> DatasetVersion:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        selected = [demo for demo in demos.list(task_id) if demo.decision == "keep" and demo.valid]
        if not selected:
            raise HTTPException(status_code=409, detail="Keep at least one valid demonstration first.")
        try:
            embodiments = dream.embodiments()
        except DreamError as exc:
            raise HTTPException(
                status_code=503,
                detail="Could not verify Dream embodiment. Check credentials and connectivity.",
            ) from exc
        if value.embodiment_name not in {body.name for body in embodiments}:
            raise HTTPException(status_code=422, detail="Choose an embodiment in your Dream account.")
        return faas.create_dataset(task_id, value.embodiment_name, [demo.id for demo in selected])

    @app.get("/api/tasks/{task_id}/datasets", response_model=list[DatasetVersion])
    def list_dataset_versions(task_id: str) -> list[DatasetVersion]:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return faas.list_datasets(task_id)

    @app.get("/api/datasets/{version_id}", response_model=DatasetVersion)
    def get_dataset_version(version_id: str) -> DatasetVersion:
        result = faas.get_dataset(version_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Dataset version not found.")
        return result

    @app.post("/api/datasets/{version_id}/finetunes", response_model=FineTuneRecord, status_code=201)
    def submit_finetune(version_id: str, settings: FineTuneRequest) -> FineTuneRecord:
        version = faas.get_dataset(version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Dataset version not found.")
        if version.status != "validated":
            raise HTTPException(status_code=409, detail="Dataset must pass local validation first.")
        if any(job.dataset_version_id == version_id for job in faas.list_finetunes()):
            raise HTTPException(status_code=409, detail="This dataset version already has a fine-tune job.")
        return faas.create_finetune(version_id, settings)

    @app.get("/api/tasks/{task_id}/finetunes", response_model=list[FineTuneRecord])
    def list_finetunes(task_id: str) -> list[FineTuneRecord]:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return faas.list_finetunes(task_id)

    @app.get("/api/finetunes/{job_id}", response_model=FineTuneRecord)
    def get_finetune(job_id: str) -> FineTuneRecord:
        result = faas.get_finetune(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Fine-tune job not found.")
        return result

    return app


app = create_app()
