"""HTTP API for the local coach UI."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from dream.errors import DreamError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from teach_task_coach.coverage import CoveragePlan, plan
from teach_task_coach.demos import Demo, DemoError, DemoScanner, DemoStore
from teach_task_coach.episodes import EpisodeSummary, RolloutScanner
from teach_task_coach.evaluation import (
    Evaluation,
    EvaluationReport,
    EvaluationRequest,
    EvaluationStore,
    scene_for_trial,
)
from teach_task_coach.faas import (
    DatasetVersion,
    DreamGateway,
    FaaSStore,
    FineTuneRecord,
    FineTuneRequest,
)
from teach_task_coach.guidance import Guidance, guidance
from teach_task_coach.preflight import PreflightResult, PreflightService
from teach_task_coach.rollout_audit import IntentAudit, audit_rollout
from teach_task_coach.scene import PlacementResult, SceneAdapter
from teach_task_coach.station import StationRejected, StationUnavailable
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import Task, TaskInput, TaskStore, Trial, TrialInput, TrialStateError
from teach_task_coach.teleop import SO101Recorder, TeleopRequest, TeleopStatus
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


class DeploymentStatus(BaseModel):
    task_id: str
    checkpoint: str
    baseline_checkpoint: str


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
    evaluation_store: EvaluationStore | None = None,
    scene_adapter: SceneAdapter | None = None,
) -> FastAPI:
    app = FastAPI(title="Teach it a task", version="0.1.0")

    @app.middleware("http")
    async def local_browser_writes_only(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin:
                parsed = urlparse(origin)
                if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Coach writes require a local browser origin."},
                    )
        return await call_next(request)
    preflight = service or PreflightService()
    episodes = store or EpisodeStore()
    rollouts = scanner or RolloutScanner()
    tasks = task_store or TaskStore(episodes.data_dir)
    runner = trial_runner or TrialRunner(tasks, episodes, preflight.station, rollouts)
    demos = demo_store or DemoStore(episodes.data_dir)
    recorder = demo_scanner or DemoScanner()
    teleop = SO101Recorder(recorder, preflight.station)
    faas = faas_store or FaaSStore(episodes.data_dir)
    dream = dream_gateway or DreamGateway()
    evaluations = evaluation_store or EvaluationStore(episodes.data_dir)
    scene_fixture = scene_adapter or SceneAdapter()

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

    @app.get("/api/episodes/{episode_id}/intent-audit", response_model=IntentAudit)
    def get_intent_audit(episode_id: str) -> IntentAudit:
        episode = episodes.get(episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found.")
        try:
            return audit_rollout(Path(episode.source_path))
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=f"Cannot audit this rollout: {exc}") from exc

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

    @app.get("/api/tasks/{task_id}/guidance", response_model=Guidance)
    def get_guidance(task_id: str) -> Guidance:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return guidance(task_id, tasks, episodes, demos, faas, evaluations)

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

    @app.get("/api/tasks/{task_id}/deployment", response_model=DeploymentStatus)
    def get_deployment(task_id: str) -> DeploymentStatus:
        task = tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return DeploymentStatus(
            task_id=task_id, checkpoint=tasks.deployed_checkpoint(task_id),
            baseline_checkpoint=task.baseline_checkpoint,
        )

    @app.post("/api/tasks/{task_id}/deployment/rollback", response_model=DeploymentStatus)
    def rollback_deployment(task_id: str) -> DeploymentStatus:
        task = tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        tasks.set_deployment(task_id, task.baseline_checkpoint, None)
        return get_deployment(task_id)

    @app.post("/api/tasks/{task_id}/deployed-trials", response_model=Trial, status_code=201)
    def create_deployed_trial(task_id: str, value: TrialInput) -> Trial:
        try:
            return tasks.create_deployed_trial(task_id, value)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found.") from exc

    @app.get("/api/tasks/{task_id}/deployed-trials", response_model=list[Trial])
    def list_deployed_trials(task_id: str) -> list[Trial]:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return tasks.list_deployed_trials(task_id)

    @app.post("/api/trials/{trial_id}/start", response_model=Trial)
    def start_trial(trial_id: str) -> Trial:
        try:
            planned = tasks.get_trial(trial_id)
            if planned is not None and planned.status == "planned" and planned.evaluation_id and scene_fixture.configured:
                scene = scene_for_trial(planned, tasks)
                if scene is None:
                    raise HTTPException(status_code=409, detail="Scene manifest is missing.")
                if preflight.station.status()["state"] != "idle":
                    raise HTTPException(status_code=409, detail="Wait for the robot station to be idle.")
                scene_fixture.place(scene)
            return runner.start(trial_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError, StationRejected) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/trials/{trial_id}/warmups", response_model=list[EpisodeSummary])
    def trial_warmups(trial_id: str) -> list[EpisodeSummary]:
        if tasks.get_trial(trial_id) is None:
            raise HTTPException(status_code=404, detail="Trial not found.")
        return [
            episode for episode_id in tasks.warmup_episode_ids(trial_id)
            if (episode := episodes.get(episode_id)) is not None
        ]

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
            result = runner.label(trial_id, label.success, label.failure_stage, label.note)
            if result.evaluation_id:
                evaluation = evaluations.get(result.evaluation_id)
                if evaluation is not None and evaluation.auto_promote:
                    report = evaluations.report(evaluation, tasks, episodes)
                    if report.decision == "improved":
                        tasks.set_deployment(evaluation.task_id, evaluation.candidate_checkpoint, evaluation.id)
            return result
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

    @app.post("/api/tasks/{task_id}/teleop/start", response_model=TeleopStatus)
    def start_teleop(task_id: str, value: TeleopRequest) -> TeleopStatus:
        task = tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        try:
            return teleop.start(task.prompt, value)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/teleop/status", response_model=TeleopStatus)
    def teleop_status() -> TeleopStatus:
        return teleop.status()

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

    @app.post("/api/tasks/{task_id}/evaluations", response_model=Evaluation, status_code=201)
    def create_evaluation(task_id: str, value: EvaluationRequest) -> Evaluation:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        job = faas.get_finetune(value.fine_tune_job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Fine-tune job not found.")
        dataset = faas.get_dataset(job.dataset_version_id)
        if dataset is None or dataset.task_id != task_id:
            raise HTTPException(status_code=409, detail="Fine-tune job belongs to another task.")
        if job.status != "succeeded" or not job.checkpoint:
            raise HTTPException(status_code=409, detail="Fine-tune must have a completed checkpoint.")
        prior = [item for item in evaluations.list(task_id) if item.fine_tune_job_id == job.id]
        if prior:
            latest_trials = tasks.list_evaluation_trials(prior[0].id)
            if not any(trial.status == "abandoned" for trial in latest_trials) or any(
                trial.status in ("starting", "running", "awaiting_rollout", "awaiting_label")
                for trial in latest_trials
            ):
                raise HTTPException(status_code=409, detail="A replacement is allowed only after an unusable trial and no active run.")
        try:
            return evaluations.create(task_id, job.id, job.checkpoint, value.minimum_effect, tasks, value.auto_promote)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/evaluations", response_model=list[Evaluation])
    def list_evaluations(task_id: str) -> list[Evaluation]:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return evaluations.list(task_id)

    @app.get("/api/evaluations/{evaluation_id}", response_model=Evaluation)
    def get_evaluation(evaluation_id: str) -> Evaluation:
        result = evaluations.get(evaluation_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Evaluation not found.")
        return result

    @app.get("/api/evaluations/{evaluation_id}/trials", response_model=list[Trial])
    def list_evaluation_trials(evaluation_id: str) -> list[Trial]:
        if evaluations.get(evaluation_id) is None:
            raise HTTPException(status_code=404, detail="Evaluation not found.")
        return tasks.list_evaluation_trials(evaluation_id)

    @app.get("/api/scene-adapter/status")
    def scene_adapter_status() -> dict[str, bool]:
        return {"configured": scene_fixture.configured}

    @app.post("/api/trials/{trial_id}/prepare-scene", response_model=PlacementResult)
    def prepare_scene(trial_id: str) -> PlacementResult:
        trial = tasks.get_trial(trial_id)
        if trial is None:
            raise HTTPException(status_code=404, detail="Trial not found.")
        if trial.status != "planned" or not trial.evaluation_id:
            raise HTTPException(status_code=409, detail="Only a planned evaluation scene can be placed.")
        scene = scene_for_trial(trial, tasks)
        if scene is None:
            raise HTTPException(status_code=409, detail="Scene manifest is missing.")
        try:
            if preflight.station.status()["state"] != "idle":
                raise HTTPException(status_code=409, detail="Wait for the robot station to be idle.")
            return scene_fixture.place(scene)
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail="Robot station is unavailable.") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/evaluations/{evaluation_id}/report", response_model=EvaluationReport)
    def get_evaluation_report(evaluation_id: str) -> EvaluationReport:
        evaluation = evaluations.get(evaluation_id)
        if evaluation is None:
            raise HTTPException(status_code=404, detail="Evaluation not found.")
        return evaluations.report(evaluation, tasks, episodes)

    @app.post("/api/evaluations/{evaluation_id}/promote", response_model=DeploymentStatus)
    def promote_evaluation(evaluation_id: str) -> DeploymentStatus:
        evaluation = evaluations.get(evaluation_id)
        if evaluation is None:
            raise HTTPException(status_code=404, detail="Evaluation not found.")
        if evaluations.report(evaluation, tasks, episodes).decision != "improved":
            raise HTTPException(status_code=409, detail="The evaluation has not verified improvement.")
        tasks.set_deployment(evaluation.task_id, evaluation.candidate_checkpoint, evaluation.id)
        return get_deployment(evaluation.task_id)

    return app


app = create_app()
