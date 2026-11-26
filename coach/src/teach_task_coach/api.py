"""HTTP API for the local coach UI."""

import hashlib
import json
import re
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from threading import Lock
from typing import Literal
from urllib.parse import urlparse

from dream.errors import DreamError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dreamlab.contracts import EvaluationReport as StatisticalReport
from dreamlab.contracts import EvaluationRequest as StatisticalRequest
from dreamlab.evaluation.engine import StatisticalEvaluator
from dreamlab.evaluation.methods.planning import plan_fixed_horizon
from teach_task_coach.account import (
    AccountConnect,
    AccountService,
    AccountStatus,
    AccountWorkspace,
    WorkspaceItem,
)
from teach_task_coach.assistant import (
    AiConnect,
    AiStatus,
    AssistantAnswer,
    AssistantQuestion,
    ChatReply,
    ChatRequest,
    ai_status,
    chat,
    connect_ai,
)
from teach_task_coach.assistant import answer as assistant_answer
from teach_task_coach.baseline_workflow import (
    FindingReview,
    SimAssignment,
    SimLink,
    WorkflowFinding,
    acknowledge,
    assignment,
    link_episode,
)
from teach_task_coach.benchmark import analyze as analyze_coach_effect
from teach_task_coach.consistency import ConsistencyReview, review_task
from teach_task_coach.coverage import CoveragePlan, plan
from teach_task_coach.demos import Demo, DemoError, DemoScanner, DemoStore
from teach_task_coach.diagnosis import TaskDiagnosis, diagnose
from teach_task_coach.episodes import EpisodeSummary, RolloutScanner
from teach_task_coach.evaluation import (
    Evaluation,
    EvaluationReport,
    EvaluationRequest,
    EvaluationStore,
    LiveEvaluation,
    scene_for_trial,
)
from teach_task_coach.faas import (
    DatasetVersion,
    DreamGateway,
    FaaSStore,
    FineTuneAlreadySubmitted,
    FineTuneRecord,
    FineTuneRequest,
)
from teach_task_coach.guidance import Guidance, guidance
from teach_task_coach.impact import TaskFootprint, footprint
from teach_task_coach.offline_review import OfflineReview
from teach_task_coach.offline_review import review as offline_review
from teach_task_coach.paired_audit import PairedReport, PairedRequest, evaluate_paired
from teach_task_coach.paired_planning import PairedPlanEstimate, PairedPlanInput, plan_pairs
from teach_task_coach.paired_snapshot import export_paired_snapshot
from teach_task_coach.preflight import PreflightResult, PreflightService
from teach_task_coach.repair import RepairReport, RepairRequest, RepairStore, RepairStudy
from teach_task_coach.rollout_audit import IntentAudit, audit_rollout
from teach_task_coach.scene import PlacementResult, SceneAdapter
from teach_task_coach.sim_correction import SimCorrectionService
from teach_task_coach.simulator_setup import SimulatorSetup, SimulatorStatus
from teach_task_coach.station import StationRejected, StationUnavailable
from teach_task_coach.storage import EpisodeStore, StaleReviewError
from teach_task_coach.tasks import Task, TaskInput, TaskStore, Trial, TrialInput, TrialStateError
from teach_task_coach.teleop import SO101Recorder, TeleopRequest, TeleopStatus
from teach_task_coach.trials import TrialError, TrialRunner
from teach_task_coach.yam_workflow import YamWorkflow, yam_router


class ImportResult(BaseModel):
    imported: int
    skipped: list[str]


class SimCorrectionInput(BaseModel):
    kind: Literal["lift", "bowl"]
    fruit: Literal["apple", "banana"]
    seed: int = Field(ge=0, le=2**32 - 1)
    object_pixel: tuple[float, float]
    target_pixel: tuple[float, float] | None = None


class SceneTaskInput(BaseModel):
    spec: dict
    seed: int = Field(ge=0, le=2**32 - 1)


class StatisticalPlanRequest(BaseModel):
    baseline_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    alternative_gain: float = Field(gt=0, le=1, allow_inf_nan=False)
    minimum_improvement: float = Field(ge=0, lt=1, allow_inf_nan=False)
    max_trials_per_arm: int = Field(ge=1, le=512)
    target_power: float = Field(default=0.8, gt=0, lt=1, allow_inf_nan=False)
    alpha: float = Field(default=0.05, gt=0, lt=1, allow_inf_nan=False)


class RunListSimulation(BaseModel):
    source: str | None = None
    seed: int | None = None


class EpisodeListItem(BaseModel):
    id: str
    task: str
    checkpoint: str
    status: str
    started_at_utc: str | None
    success: bool | None
    finding_count: int
    simulation: RunListSimulation | None = None


class EpisodeLabel(BaseModel):
    # Older clients may write a first label, but never overwrite an existing review.
    expected_revision: int = Field(default=0, ge=0, le=2**53 - 1, strict=True)
    success: bool | None
    failure_stage: Literal["approach", "grasp", "transport", "release", "other"] | None = None
    note: str | None = Field(default=None, max_length=2000)


class TrialLabel(BaseModel):
    success: bool
    failure_stage: Literal["approach", "grasp", "transport", "release", "other"] | None = None
    note: str | None = Field(default=None, max_length=2000)
    reviewer_id: str | None = Field(default=None, min_length=1, max_length=120)
    interventions: int = Field(default=0, ge=0)
    first_response_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class PairedSnapshotAttestation(BaseModel):
    heldout_attested: bool
    resets_attested: bool


class RepairAttestation(BaseModel):
    reset_attested: bool


class CoachEffectInput(BaseModel):
    plan: dict
    outcomes: list[dict]


class RepairTriage(BaseModel):
    task_id: str
    action: Literal["fix_camera", "fix_station", "fix_setup", "measure_baseline", "compare_cheap_fix", "use_fix", "collect_demos"]
    reason: str
    evidence: list[str]


class AbandonReason(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class DemoDecision(BaseModel):
    decision: Literal["keep", "redo"]
    start_cell: int | None = Field(default=None, ge=0, le=8)
    defer_coverage_label: bool = False
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


class SimulatorSessionReset(BaseModel):
    yam_active: bool
    recorder_active: bool


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
    repair_store: RepairStore | None = None,
    scene_adapter: SceneAdapter | None = None,
    account_service: AccountService | None = None,
    simulator_setup: SimulatorSetup | None = None,
    offline_only: bool = False,
) -> FastAPI:
    app = FastAPI(title="DreamCoach", version="0.1.0")

    @app.middleware("http")
    async def local_browser_writes_only(request: Request, call_next):
        if offline_only and request.url.path.startswith("/api/"):
            read_routes = {
                ("GET", "/api/mode"),
                ("GET", "/api/episodes"),
                ("GET", "/api/tasks"),
            }
            path = request.url.path
            method = request.method
            allowed = (method, path) in read_routes or any(
                method == verb and re.fullmatch(pattern, path)
                for verb, pattern in (
                    ("GET", r"/api/offline-review/[A-Za-z0-9_-]+"),
                    ("GET", r"/api/episodes/[A-Za-z0-9_-]+"),
                    ("GET", r"/api/episodes/[A-Za-z0-9_-]+/video/[A-Za-z0-9_.-]+"),
                    ("GET", r"/api/tasks/[A-Za-z0-9_-]+/demos"),
                    ("GET", r"/api/demos/[A-Za-z0-9_-]+/video/[A-Za-z0-9_.-]+"),
                    ("POST", r"/api/rollouts/import"),
                    ("POST", r"/api/tasks/[A-Za-z0-9_-]+/demos/import"),
                    ("POST", r"/api/episodes/[A-Za-z0-9_-]+/label"),
                    ("POST", r"/api/demos/[A-Za-z0-9_-]+/decision"),
                )
            )
            if not allowed:
                return JSONResponse(status_code=403, content={"detail": "This action is disabled in the offline walkthrough."})
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
    sim_correction = SimCorrectionService(recorder.root, demos)
    teleop = SO101Recorder(recorder, preflight.station)
    faas = faas_store or FaaSStore(episodes.data_dir)
    dream = dream_gateway or DreamGateway()
    evaluations = evaluation_store or EvaluationStore(episodes.data_dir)
    repairs = repair_store or RepairStore(episodes.data_dir)
    scene_fixture = scene_adapter or SceneAdapter()
    station_movement = Lock()
    account = account_service or AccountService()
    simulator = simulator_setup or SimulatorSetup()
    yam = YamWorkflow(
        episodes.data_dir / "yam-workflow", tasks, demos, faas, simulator, preflight,
        list_finetunes=None if offline_only else lambda: dream.finetunes(),
    )
    app.include_router(yam_router(yam))

    @app.get("/api/account/status", response_model=AccountStatus)
    def account_status() -> AccountStatus:
        return account.status()

    @app.post("/api/account/connect", response_model=AccountStatus)
    def connect_account(value: AccountConnect) -> AccountStatus:
        try:
            return account.connect(value.api_key)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/account/workspace", response_model=AccountWorkspace)
    def account_workspace() -> AccountWorkspace:
        if not account.status().configured:
            return AccountWorkspace(state="disconnected", message="Connect Dream Labs to inspect account resources.")
        try:
            datasets = dream.datasets()
            jobs = dream.finetunes()
            models = dream.client.get_models()
        except DreamError:
            return AccountWorkspace(state="unavailable", message="Dream account resources could not be loaded right now.")
        return AccountWorkspace(
            state="ready", message="Read-only Dream account inventory loaded.",
            datasets=[WorkspaceItem(id=item.id, name=item.name, status=item.status) for item in datasets[:20]],
            fine_tuning_jobs=[WorkspaceItem(id=str(item.get("id", "")),
                                                 name=str(item.get("dataset", "Fine-tuning job")),
                                                 status=str(item.get("status", "unknown"))) for item in jobs[:20]],
            models=[WorkspaceItem(id=item.id, name=item.id,
                                  status="servable" if item.servable else "pending") for item in models[:20]],
        )

    @app.post("/api/assistant/ask", response_model=AssistantAnswer)
    def ask_assistant(value: AssistantQuestion) -> AssistantAnswer:
        return assistant_answer(value)

    @app.get("/api/assistant/status", response_model=AiStatus)
    def get_ai_status() -> AiStatus:
        return ai_status()

    @app.post("/api/assistant/connect", response_model=AiStatus)
    def connect_ai_account(value: AiConnect) -> AiStatus:
        try:
            return connect_ai(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/assistant/chat", response_model=ChatReply)
    def chat_with_coach(value: ChatRequest) -> ChatReply:
        try:
            return chat(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def require_live_task(task_id: str) -> Task:
        task = tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        if task.offline_mode:
            raise HTTPException(status_code=409, detail="Offline walkthrough tasks cannot use robot, training, evaluation, or deployment actions.")
        return task

    def require_live_dataset(version_id: str) -> DatasetVersion:
        version = faas.get_dataset(version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Dataset version not found.")
        require_live_task(version.task_id)
        return version

    def require_live_trial(trial_id: str) -> Trial:
        trial = tasks.get_trial(trial_id)
        if trial is None:
            raise HTTPException(status_code=404, detail="Trial not found.")
        require_live_task(trial.task_id)
        return trial

    def require_live_evaluation(evaluation_id: str) -> Evaluation:
        evaluation = evaluations.get(evaluation_id)
        if evaluation is None:
            raise HTTPException(status_code=404, detail="Evaluation not found.")
        require_live_task(evaluation.task_id)
        return evaluation

    @app.get("/api/mode")
    def get_mode() -> dict[str, bool]:
        return {"offline_only": offline_only}

    @app.get("/api/preflight", response_model=PreflightResult)
    def get_preflight() -> PreflightResult:
        if offline_only:
            from teach_task_coach.preflight import Check
            return PreflightResult(
                station=Check(state="unavailable", message="Robot access is disabled in this offline walkthrough."),
                dream=Check(state="unavailable", message="Dream access is disabled in this offline walkthrough."),
                station_status=None,
                models=[],
            )
        return preflight.run()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/docs/simulator")
    def simulator_setup_guide() -> FileResponse:
        path = Path(__file__).resolve().parents[2] / "experiments/yam_sim_faas/FAILURE_CONDITIONED_SIM.md"
        return FileResponse(path, media_type="text/markdown")

    @app.get("/api/sim-correction/scene")
    def sim_correction_scene(fruit: str = "apple", seed: int = 41) -> dict:
        try:
            return sim_correction.preview(fruit, seed)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/sim-correction")
    def start_sim_correction(task_id: str, value: SimCorrectionInput) -> dict:
        task = require_live_task(task_id)
        try:
            return sim_correction.start(task_id, task.prompt, value.kind, value.fruit,
                                        value.seed, value.object_pixel, value.target_pixel)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/sim-correction/status")
    def sim_correction_status() -> dict:
        return sim_correction.status()

    @app.post("/api/scene-task/preview")
    def preview_scene_task(value: SceneTaskInput) -> dict:
        try:
            return sim_correction.preview_scene_task(value.spec, value.seed)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/scene-task")
    def start_scene_task(task_id: str, value: SceneTaskInput) -> dict:
        task = require_live_task(task_id)
        try:
            return sim_correction.start_scene_task(task_id, task.prompt, value.spec, value.seed)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/simulator/status", response_model=SimulatorStatus)
    def get_simulator_status() -> SimulatorStatus:
        return simulator.status()

    @app.post("/api/simulator/prepare", response_model=SimulatorStatus)
    def prepare_simulator() -> SimulatorStatus:
        return simulator.prepare()

    @app.post("/api/simulator/session/reset", response_model=SimulatorSessionReset)
    def reset_simulator_session() -> SimulatorSessionReset:
        try:
            yam.reset_session()
            sim_correction.reset_session()
        except TimeoutError as exc:
            raise HTTPException(
                status_code=409,
                detail="The previous simulator run is still stopping. Press Begin again in a moment.",
            ) from exc
        return SimulatorSessionReset(yam_active=False, recorder_active=False)

    @app.get("/api/docs/apple-training")
    def apple_training_guide() -> FileResponse:
        path = Path(__file__).resolve().parents[2] / "experiments/yam_sim_faas/grasp_training/README.md"
        return FileResponse(path, media_type="text/markdown")

    @app.get("/api/docs/apple-evaluation")
    def apple_evaluation_report() -> FileResponse:
        path = Path(__file__).resolve().parents[2] / "experiments/yam_sim_faas/grasp_training/SECOND_ACCOUNT_500_STEP_EVAL.md"
        return FileResponse(path, media_type="text/markdown")

    @app.post("/api/coach-effect/analyze")
    def analyze_operator_study(value: CoachEffectInput) -> dict:
        try:
            return analyze_coach_effect(value.plan, value.outcomes)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/coach-effect/synthetic-example")
    def synthetic_operator_study() -> CoachEffectInput:
        import json

        root = files("teach_task_coach").joinpath("examples")
        return CoachEffectInput(
            plan=json.loads(root.joinpath("coach_effect_plan.synthetic.json").read_text(encoding="utf-8")),
            outcomes=json.loads(root.joinpath("coach_effect_outcomes.synthetic.json").read_text(encoding="utf-8")),
        )

    @app.get("/api/tasks/{task_id}/footprint", response_model=TaskFootprint)
    def task_footprint(task_id: str) -> TaskFootprint:
        try:
            return footprint(task_id, tasks, demos, faas, evaluations, episodes, repairs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found.") from exc

    @app.post("/api/statistical-evaluations/analyze", response_model=StatisticalReport)
    def analyze_independent_trials(value: StatisticalRequest) -> StatisticalReport:
        """Audit a supplied immutable snapshot; no robot, Dream API, or deployment action."""
        return StatisticalEvaluator().evaluate(value)

    @app.post("/api/statistical-evaluations/plan")
    def plan_independent_trials(value: StatisticalPlanRequest) -> dict:
        """Prospective sample-size calculation for the same fixed-horizon decision rule."""
        try:
            result = plan_fixed_horizon(**value.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return asdict(result) | {"feasible": result.feasible}

    @app.post("/api/paired-evaluations/analyze", response_model=PairedReport)
    def analyze_matched_scenes(value: PairedRequest) -> PairedReport:
        """Audit predeclared matched scenes without robot or Dream API calls."""
        return evaluate_paired(value)

    @app.post("/api/paired-evaluations/plan", response_model=PairedPlanEstimate)
    def plan_matched_scenes(value: PairedPlanInput) -> PairedPlanEstimate:
        return plan_pairs(value)

    @app.get("/api/paired-evaluations/demo", response_model=PairedRequest)
    def apple_confirmation_demo() -> PairedRequest:
        """Return the frozen summary of eight simulator rollouts for a read-only demo."""
        source = files("teach_task_coach").joinpath("examples/apple_paired_confirmation.json")
        return PairedRequest.model_validate_json(source.read_text(encoding="utf-8"))

    @app.get("/api/paired-evaluations/demo/second-account", response_model=PairedRequest)
    def second_account_confirmation_demo() -> PairedRequest:
        """Return the frozen summary of the independent 24-demo checkpoint comparison."""
        source = files("teach_task_coach").joinpath("examples/second_account_paired_confirmation.json")
        return PairedRequest.model_validate_json(source.read_text(encoding="utf-8"))

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend/dist"
    if (frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")
    if (frontend_dist / "dream").is_dir():
        app.mount("/dream", StaticFiles(directory=frontend_dist / "dream"), name="frontend-dream-assets")

    @app.get("/", response_model=None)
    def frontend() -> FileResponse | dict[str, str]:
        index = frontend_dist / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        return {"message": "Build coach/frontend first."}

    def offline_episode_for_task(episode: EpisodeSummary, task_id: str | None = None) -> bool:
        simulation = episode.simulation or {}
        owner = simulation.get("offline_task_id")
        scene_id = simulation.get("offline_scene_id")
        if (
            simulation.get("policy_origin") != "offline_fixture"
            or not isinstance(owner, str)
            or not isinstance(scene_id, str)
            or episode.status != "complete"
            or not episode.evidence_sha256
        ):
            return False
        task = tasks.get_task(owner)
        if task is None or not task.offline_mode or task.prompt != episode.task:
            return False
        manifest_path = tasks.db.data_dir / "offline-protocol.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema") != "coach-offline-walkthrough-v1" or manifest.get("task_id") != owner:
                return False
            spec = next((item for item in manifest.get("scenes", []) if item.get("id") == scene_id), None)
            if spec is None or episode.simulation.get("seed") != spec.get("seed"):
                return False
            if episode.checkpoint != f"offline-fixture/{episode.simulation.get('comparison_role')}":
                return False
            if (episode.simulation.get("policy_origin") != "offline_fixture"
                    or episode.simulation.get("protocol_sha256") != hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    or episode.simulation.get("protocol") != manifest.get("schema")
                    or episode.simulation.get("rule_version") != manifest.get("rule_version")):
                return False
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            return False
        return task_id is None or owner == task_id

    @app.post("/api/rollouts/import", response_model=ImportResult)
    def import_rollouts() -> ImportResult:
        found, skipped = rollouts.scan()
        imported = 0
        for episode in found:
            simulation = episode.simulation or {}
            if simulation.get("policy_origin") == "offline_fixture" or isinstance(simulation.get("offline_task_id"), str):
                if not offline_only or not offline_episode_for_task(episode):
                    skipped.append(f"{Path(episode.source_path).name}: offline fixture belongs only to its isolated offline workspace")
                    continue
            elif offline_only:
                skipped.append(f"{Path(episode.source_path).name}: offline workspace imports explicitly tagged fixtures only")
                continue
            episodes.upsert(episode)
            imported += 1
        return ImportResult(imported=imported, skipped=skipped)

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
                simulation=RunListSimulation(
                    source=episode.simulation.get('source') if isinstance(episode.simulation.get('source'), str) else None,
                    seed=episode.simulation.get('seed') if type(episode.simulation.get('seed')) is int else None,
                ) if episode.simulation is not None else None,
            )
            for episode in episodes.list()
            if (
                offline_episode_for_task(episode)
                if offline_only
                else (episode.simulation or {}).get("policy_origin") != "offline_fixture"
                     and not isinstance((episode.simulation or {}).get("offline_task_id"), str)
            )
        ]

    @app.get("/api/offline-review/{task_id}", response_model=OfflineReview)
    def get_offline_review(task_id: str) -> OfflineReview:
        if not offline_only:
            raise HTTPException(status_code=404, detail="Offline review is available only in the isolated offline application.")
        try:
            return offline_review(task_id, tasks, episodes, demos)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/episodes/{episode_id}", response_model=EpisodeSummary)
    def get_episode(episode_id: str) -> EpisodeSummary:
        episode = episodes.get(episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found.")
        if offline_only and not offline_episode_for_task(episode):
            raise HTTPException(status_code=404, detail="Episode not found in this offline workspace.")
        if not offline_only and (
            (episode.simulation or {}).get("policy_origin") == "offline_fixture"
            or isinstance((episode.simulation or {}).get("offline_task_id"), str)
        ):
            raise HTTPException(status_code=404, detail="Offline fixture episodes are not part of the live workspace.")
        return episode

    @app.get("/api/episodes/{episode_id}/intent-audit", response_model=IntentAudit)
    def get_intent_audit(episode_id: str) -> IntentAudit:
        episode = episodes.get(episode_id)
        if episode is None or (episode.simulation or {}).get("policy_origin") == "offline_fixture" or isinstance((episode.simulation or {}).get("offline_task_id"), str):
            raise HTTPException(status_code=404, detail="Episode not found.")
        try:
            return audit_rollout(Path(episode.source_path))
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=f"Cannot audit this rollout: {exc}") from exc

    @app.get("/api/episodes/{episode_id}/video/{role}")
    def get_video(episode_id: str, role: str) -> FileResponse:
        episode = episodes.get(episode_id)
        if episode is not None and (
            (offline_only and not offline_episode_for_task(episode))
            or (not offline_only and (
                (episode.simulation or {}).get("policy_origin") == "offline_fixture"
                or isinstance((episode.simulation or {}).get("offline_task_id"), str)
            ))
        ):
            raise HTTPException(status_code=404, detail="Video not found.")
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
        current = episodes.get(episode_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Episode not found.")
        if offline_only:
            if not offline_episode_for_task(current):
                raise HTTPException(status_code=404, detail="Episode not found in this offline workspace.")
        elif (
            (current.simulation or {}).get("policy_origin") == "offline_fixture"
            or isinstance((current.simulation or {}).get("offline_task_id"), str)
        ):
            raise HTTPException(status_code=409, detail="Offline fixture labels can only be changed in their isolated offline walkthrough.")
        try:
            episode = episodes.label(episode_id, label.success, label.failure_stage, label.note,
                                     expected_revision=label.expected_revision)
        except StaleReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found.")
        return episode

    @app.post("/api/tasks", response_model=Task, status_code=201)
    def create_task(value: TaskInput) -> Task:
        return tasks.create_task(value)

    @app.get("/api/tasks", response_model=list[Task])
    def list_tasks() -> list[Task]:
        values = tasks.list_tasks()
        return [task for task in values if task.offline_mode] if offline_only else [task for task in values if not task.offline_mode]

    @app.get("/api/tasks/{task_id}", response_model=Task)
    def get_task(task_id: str) -> Task:
        task = tasks.get_task(task_id)
        if task is None or (offline_only and not task.offline_mode) or (not offline_only and task.offline_mode):
            raise HTTPException(status_code=404, detail="Task not found.")
        return task

    @app.get('/api/episodes/{episode_id}/sim-baseline', response_model=SimLink | None)
    def get_sim_assignment(episode_id: str):
        episode = episodes.get(episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail='Episode not found.')
        return assignment(tasks, episode)

    @app.post('/api/tasks/{task_id}/sim-baselines', response_model=SimLink)
    def assign_sim_baseline(task_id: str, value: SimAssignment):
        require_live_task(task_id)
        try:
            return link_episode(tasks, task_id, value)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TrialStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post('/api/tasks/{task_id}/findings/{finding_id}/review', response_model=WorkflowFinding)
    def review_finding(task_id: str, finding_id: str, value: FindingReview):
        require_live_task(task_id)
        try:
            return acknowledge(task_id, finding_id, value, tasks, episodes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/guidance", response_model=Guidance)
    def get_guidance(task_id: str) -> Guidance:
        task = tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        if task.offline_mode:
            raise HTTPException(status_code=409, detail="Use the offline walkthrough review for fixture tasks.")
        return guidance(task_id, tasks, episodes, demos, faas, evaluations, repairs)

    @app.get("/api/tasks/{task_id}/diagnosis", response_model=TaskDiagnosis)
    def get_diagnosis(task_id: str) -> TaskDiagnosis:
        require_live_task(task_id)
        return diagnose(task_id, tasks, episodes)

    @app.get("/api/tasks/{task_id}/repair/triage", response_model=RepairTriage)
    def triage_repair(task_id: str) -> RepairTriage:
        task = tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        try:
            status = preflight.station.status()
        except StationUnavailable:
            return RepairTriage(task_id=task_id, action="fix_station",
                                reason="Robot station is unavailable; inspect it before spending on training.",
                                evidence=["Station status request failed."])
        cameras = status.get("cameras") or {}
        if not cameras or any(age is None or age > 2 for age in cameras.values()):
            return RepairTriage(task_id=task_id, action="fix_camera",
                                reason="A camera feed is missing or stale; verify model inputs first.",
                                evidence=[f"{name}: {age if age is not None else 'no frame'} s"
                                          for name, age in cameras.items()] or ["No camera feeds reported."])
        arms = status.get("arms") or {}
        if not arms or not all(arms.values()) or status.get("last_error"):
            return RepairTriage(task_id=task_id, action="fix_station",
                                reason="Robot arm or station fault needs attention before testing a model.",
                                evidence=[str(status.get("last_error") or arms)])
        diagnosis = diagnose(task_id, tasks, episodes)
        if diagnosis.setup_count:
            return RepairTriage(task_id=task_id, action="fix_setup",
                                reason="Recorded runs contain station or setup problems; inspect them first.",
                                evidence=[f"{diagnosis.setup_count} affected runs."])
        latest = repairs.list(task_id)
        if latest:
            report = repairs.report(latest[0], tasks, episodes)
            if report.decision == "use_fix":
                return RepairTriage(task_id=task_id, action="use_fix", reason=report.recommendation,
                                    evidence=[f"{report.usable_pairs} paired repair trials; {report.input_sha256}."])
            if report.decision == "consider_faas":
                return RepairTriage(task_id=task_id, action="collect_demos", reason=report.recommendation,
                                    evidence=[f"{report.usable_pairs} paired repair trials; {report.input_sha256}."])
        labelled = [episodes.get(trial.episode_id) for trial in tasks.list_trials(task_id)
                    if trial.status == "completed" and trial.episode_id]
        if not any(episode and episode.success is False for episode in labelled):
            return RepairTriage(task_id=task_id, action="measure_baseline",
                                reason="Record and label baseline failures before choosing a repair.",
                                evidence=[f"{len(labelled)} labelled baseline trials."])
        return RepairTriage(task_id=task_id, action="compare_cheap_fix",
                            reason="Test a prompt or setup change on matched scenes before buying a fine-tune.",
                            evidence=[f"{sum(episode.success is False for episode in labelled if episode)} baseline failures."])

    @app.post("/api/tasks/{task_id}/repair-studies", response_model=RepairStudy, status_code=201)
    def create_repair_study(task_id: str, value: RepairRequest) -> RepairStudy:
        try:
            return repairs.create(task_id, value, tasks)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/repair-studies", response_model=list[RepairStudy])
    def list_repair_studies(task_id: str) -> list[RepairStudy]:
        if tasks.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return repairs.list(task_id)

    @app.get("/api/repair-studies/{study_id}/trials", response_model=list[Trial])
    def list_repair_trials(study_id: str) -> list[Trial]:
        if repairs.get(study_id) is None:
            raise HTTPException(status_code=404, detail="Repair study not found.")
        return tasks.list_repair_trials(study_id)

    @app.get("/api/repair-studies/{study_id}/report", response_model=RepairReport)
    def get_repair_report(study_id: str) -> RepairReport:
        study = repairs.get(study_id)
        if study is None:
            raise HTTPException(status_code=404, detail="Repair study not found.")
        return repairs.report(study, tasks, episodes)

    @app.post("/api/repair-studies/{study_id}/audit", response_model=RepairReport)
    def audit_repair(study_id: str, value: RepairAttestation) -> RepairReport:
        study = repairs.get(study_id)
        if study is None:
            raise HTTPException(status_code=404, detail="Repair study not found.")
        try:
            return repairs.save_audit(study, tasks, episodes, reset_attested=value.reset_attested)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/consistency", response_model=ConsistencyReview)
    def get_consistency(task_id: str) -> ConsistencyReview:
        require_live_task(task_id)
        return review_task(task_id, tasks, episodes)

    @app.post("/api/tasks/{task_id}/baseline-trials", response_model=Trial, status_code=201)
    def create_baseline_trial(task_id: str, value: TrialInput) -> Trial:
        require_live_task(task_id)
        try:
            return tasks.create_trial(task_id, value)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found.") from exc

    @app.get("/api/tasks/{task_id}/baseline-trials", response_model=list[Trial])
    def list_baseline_trials(task_id: str) -> list[Trial]:
        require_live_task(task_id)
        return tasks.list_trials(task_id)

    @app.get("/api/tasks/{task_id}/deployment", response_model=DeploymentStatus)
    def get_deployment(task_id: str) -> DeploymentStatus:
        task = require_live_task(task_id)
        return DeploymentStatus(
            task_id=task_id, checkpoint=tasks.deployed_checkpoint(task_id),
            baseline_checkpoint=task.baseline_checkpoint,
        )

    @app.post("/api/tasks/{task_id}/deployment/rollback", response_model=DeploymentStatus)
    def rollback_deployment(task_id: str) -> DeploymentStatus:
        task = require_live_task(task_id)
        tasks.set_deployment(task_id, task.baseline_checkpoint, None)
        return get_deployment(task_id)

    @app.post("/api/tasks/{task_id}/deployed-trials", response_model=Trial, status_code=201)
    def create_deployed_trial(task_id: str, value: TrialInput) -> Trial:
        require_live_task(task_id)
        try:
            return tasks.create_deployed_trial(task_id, value)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found.") from exc

    @app.get("/api/tasks/{task_id}/deployed-trials", response_model=list[Trial])
    def list_deployed_trials(task_id: str) -> list[Trial]:
        require_live_task(task_id)
        return tasks.list_deployed_trials(task_id)

    @app.post("/api/trials/{trial_id}/start", response_model=Trial)
    def start_trial(trial_id: str) -> Trial:
        require_live_trial(trial_id)
        if not station_movement.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Another station start or scene placement is in progress.")

        def place_evaluation_scene(trial: Trial) -> None:
            if trial.evaluation_id is None:
                return
            scene = scene_for_trial(trial, tasks)
            if scene is None:
                raise TrialError("Scene manifest is missing.")
            scene_fixture.place(scene)

        try:
            if scene_fixture.configured:
                return runner.start(trial_id, before_start=place_evaluation_scene)
            return runner.start(trial_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError, StationRejected) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            station_movement.release()

    @app.get("/api/trials/{trial_id}/warmups", response_model=list[EpisodeSummary])
    def trial_warmups(trial_id: str) -> list[EpisodeSummary]:
        require_live_trial(trial_id)
        return [
            episode for episode_id in tasks.warmup_episode_ids(trial_id)
            if (episode := episodes.get(episode_id)) is not None
        ]

    @app.post("/api/trials/{trial_id}/stop", response_model=Trial)
    def stop_trial(trial_id: str) -> Trial:
        require_live_trial(trial_id)
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
        require_live_trial(trial_id)
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
        require_live_trial(trial_id)
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
        require_live_trial(trial_id)
        try:
            result = runner.label(
                trial_id, label.success, label.failure_stage, label.note,
                label.reviewer_id, label.interventions, label.first_response_s,
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trial not found.") from exc
        except (TrialError, TrialStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/trials/{trial_id}/abandon", response_model=Trial)
    def abandon_trial(trial_id: str, value: AbandonReason) -> Trial:
        require_live_trial(trial_id)
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
        task = get_task(task_id)
        found, skipped = recorder.scan(task_id, task.prompt)
        imported = 0
        for demo in found:
            if task.offline_mode and (
                demo.offline_task_id != task_id
                or demo.origin == "offline_fixture"
            ):
                skipped.append(f"{Path(demo.source_path).name}: demo is not an eligible reference for this offline task")
                continue
            if not task.offline_mode and demo.offline_task_id is not None:
                skipped.append(f"{Path(demo.source_path).name}: offline-owned demos cannot be imported into a live task")
                continue
            try:
                demos.upsert(demo)
            except DemoError as exc:
                skipped.append(f"{Path(demo.source_path).name}: {exc}")
            else:
                imported += 1
        return ImportResult(imported=imported, skipped=skipped)

    @app.post("/api/tasks/{task_id}/teleop/start", response_model=TeleopStatus)
    def start_teleop(task_id: str, value: TeleopRequest) -> TeleopStatus:
        task = require_live_task(task_id)
        try:
            return teleop.start(task.prompt, value)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/teleop/status", response_model=TeleopStatus)
    def teleop_status() -> TeleopStatus:
        return teleop.status()

    @app.post("/api/teleop/stop", response_model=TeleopStatus)
    def stop_teleop() -> TeleopStatus:
        try:
            return teleop.stop()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/demos", response_model=list[Demo])
    def list_demos(task_id: str) -> list[Demo]:
        task = tasks.get_task(task_id)
        if task is None or (offline_only and not task.offline_mode) or (not offline_only and task.offline_mode):
            raise HTTPException(status_code=404, detail="Task not found.")
        return demos.list(task_id)

    @app.post("/api/demos/{demo_id}/decision", response_model=Demo)
    def decide_demo(demo_id: str, value: DemoDecision) -> Demo:
        demo = demos.get(demo_id)
        if demo is None:
            raise HTTPException(status_code=404, detail="Demo not found.")
        task = tasks.get_task(demo.task_id)
        if task is None or (offline_only and not task.offline_mode) or (not offline_only and task.offline_mode):
            raise HTTPException(status_code=404, detail="Task not found.")
        if value.decision == "keep":
            if value.start_cell is None and not value.defer_coverage_label:
                raise HTTPException(status_code=422, detail="Choose a start cell for a kept demo.")
            if not demo.valid:
                raise HTTPException(status_code=409, detail="Fix hard validation issues before keeping this demo.")
            if demo.origin not in ("human", "scripted_reference"):
                raise HTTPException(status_code=409, detail="This demo's source is unknown or offline-only and cannot be kept for training.")
            if task.offline_mode and (
                demo.origin != "scripted_reference"
                or not demo.source_episode_id
                or not any(
                    episode.id == demo.source_episode_id and offline_episode_for_task(episode, task.id)
                    for episode in episodes.list()
                )
            ):
                raise HTTPException(status_code=409, detail="Only a scripted reference linked to this task's fixture can be kept in the offline walkthrough.")
        result = demos.decide(demo_id, value.decision, value.start_cell, value.note)
        assert result is not None
        return result

    @app.get("/api/demos/{demo_id}/video/{role}")
    def get_demo_video(demo_id: str, role: str) -> FileResponse:
        demo = demos.get(demo_id)
        if demo is not None:
            task = tasks.get_task(demo.task_id)
            if task is None or (offline_only and not task.offline_mode) or (not offline_only and task.offline_mode):
                raise HTTPException(status_code=404, detail="Video not found.")
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
        require_live_task(task_id)
        selected = [demo for demo in demos.training_eligible(task_id) if demo.decision == "keep" and demo.valid]
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
        require_live_task(task_id)
        return faas.list_datasets(task_id)

    @app.get("/api/datasets/{version_id}", response_model=DatasetVersion)
    def get_dataset_version(version_id: str) -> DatasetVersion:
        return require_live_dataset(version_id)

    @app.post("/api/datasets/{version_id}/finetunes", response_model=FineTuneRecord, status_code=201)
    def submit_finetune(version_id: str, settings: FineTuneRequest) -> FineTuneRecord:
        version = require_live_dataset(version_id)
        if version.status != "validated":
            raise HTTPException(status_code=409, detail="Dataset must pass local validation first.")
        eligible_ids = {demo.id for demo in demos.training_eligible(version.task_id)}
        if not set(version.demo_ids).issubset(eligible_ids):
            raise HTTPException(status_code=409, detail="The validated dataset contains an unavailable or offline-only demonstration.")
        if settings.resume_from:
            existing_jobs = faas.list_finetunes()
            parent = next((job for job in existing_jobs if job.checkpoint == settings.resume_from), None)
            parent_version = None if parent is None else faas.get_dataset(parent.dataset_version_id)
            if (
                parent is None or parent.status != "succeeded" or parent.lr_schedule != "constant"
                or settings.lr_schedule != "constant" or parent.use_eef != settings.use_eef
                or parent.base_share != settings.base_share or parent_version is None
                or parent_version.embodiment_name != version.embodiment_name
                or parent_version.task_id != version.task_id
            ):
                raise HTTPException(status_code=409, detail="Resume requires a completed constant-schedule model with matching training settings and embodiment.")
            if any(job.resume_from == settings.resume_from for job in existing_jobs):
                raise HTTPException(status_code=409, detail="This checkpoint already has a continuation job.")
            parent_evaluations = [
                item for item in evaluations.list(version.task_id) if item.fine_tune_job_id == parent.id
            ]
            if not any(
                (report := evaluations.report(item, tasks, episodes)).usable_pairs == 30
                and report.decision == "inconclusive"
                and (report.paired_difference or 0) > 0
                for item in parent_evaluations
            ):
                raise HTTPException(status_code=409, detail="Complete the parent checkpoint's paired evaluation before continuing; only a positive but inconclusive gain supports more steps.")
        try:
            return faas.create_finetune(version_id, settings)
        except FineTuneAlreadySubmitted as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/finetunes", response_model=list[FineTuneRecord])
    def list_finetunes(task_id: str) -> list[FineTuneRecord]:
        require_live_task(task_id)
        return faas.list_finetunes(task_id)

    @app.post('/api/finetunes/{job_id}/retry-processing', response_model=FineTuneRecord)
    def retry_processing(job_id: str):
        job = faas.get_finetune(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Fine-tune job not found.")
        version = faas.get_dataset(job.dataset_version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Dataset version not found.")
        require_live_task(version.task_id)
        try:
            return faas.request_retry(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Job not found.') from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/finetunes/{job_id}", response_model=FineTuneRecord)
    def get_finetune(job_id: str) -> FineTuneRecord:
        result = faas.get_finetune(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Fine-tune job not found.")
        version = faas.get_dataset(result.dataset_version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Dataset version not found.")
        require_live_task(version.task_id)
        return result

    @app.post("/api/tasks/{task_id}/evaluations", response_model=Evaluation, status_code=201)
    def create_evaluation(task_id: str, value: EvaluationRequest) -> Evaluation:
        if value.auto_promote:
            raise HTTPException(status_code=409, detail="Automatic promotion is disabled; complete an audit and promote explicitly.")
        require_live_task(task_id)
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
            return evaluations.create(
                task_id, job.id, job.checkpoint, value.minimum_effect, tasks,
                value.auto_promote, value.planned_pairs,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/evaluations", response_model=list[Evaluation])
    def list_evaluations(task_id: str) -> list[Evaluation]:
        require_live_task(task_id)
        return evaluations.list(task_id)

    @app.get("/api/evaluations/latest", response_model=LiveEvaluation | None)
    def latest_evaluation(task_id: str | None = None) -> LiveEvaluation | None:
        evaluation = next(iter(evaluations.list(task_id)), None) if task_id is not None else evaluations.latest()
        if evaluation is None:
            return None
        task = require_live_task(evaluation.task_id)
        return LiveEvaluation(
            task_name=task.name,
            evaluation=evaluation,
            report=evaluations.report(evaluation, tasks, episodes),
        )

    @app.get("/api/evaluations/{evaluation_id}", response_model=Evaluation)
    def get_evaluation(evaluation_id: str) -> Evaluation:
        return require_live_evaluation(evaluation_id)

    @app.get("/api/evaluations/{evaluation_id}/trials", response_model=list[Trial])
    def list_evaluation_trials(evaluation_id: str) -> list[Trial]:
        require_live_evaluation(evaluation_id)
        return tasks.list_evaluation_trials(evaluation_id)

    @app.post("/api/evaluations/{evaluation_id}/paired-snapshot", response_model=PairedRequest)
    def paired_snapshot(evaluation_id: str, value: PairedSnapshotAttestation) -> PairedRequest:
        evaluation = require_live_evaluation(evaluation_id)
        if not value.heldout_attested or not value.resets_attested:
            raise HTTPException(status_code=409, detail="Confirm training holdout and scene resets before final audit.")
        try:
            evaluations.audit(
                evaluation, tasks, episodes,
                heldout_attested=value.heldout_attested,
                resets_attested=value.resets_attested,
            )
            return export_paired_snapshot(
                evaluation, tasks, episodes,
                heldout_attested=value.heldout_attested,
                resets_attested=value.resets_attested,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/evaluations/{evaluation_id}/audit", response_model=PairedReport)
    def get_saved_paired_audit(evaluation_id: str) -> PairedReport:
        evaluation = require_live_evaluation(evaluation_id)
        saved = evaluations.latest_audit(evaluation_id)
        if saved is None:
            raise HTTPException(status_code=404, detail="No paired audit has been saved.")
        snapshot, stored = saved
        current = evaluate_paired(export_paired_snapshot(
            evaluation, tasks, episodes,
            heldout_attested=snapshot.plan.heldout_attested,
            resets_attested=snapshot.plan.resets_attested,
        ))
        if current.input_sha256 != stored.input_sha256:
            return current.model_copy(update={
                "decision": "not_evaluable", "observed_difference": None,
                "difference_interval": None, "interval_method": None,
                "problems": (*current.problems, "Evidence changed since the saved audit; run it again."),
            })
        return stored

    @app.get("/api/scene-adapter/status")
    def scene_adapter_status() -> dict[str, bool]:
        return {"configured": scene_fixture.configured}

    @app.post("/api/trials/{trial_id}/prepare-scene", response_model=PlacementResult)
    def prepare_scene(trial_id: str) -> PlacementResult:
        if not station_movement.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Another station start or scene placement is in progress.")
        try:
            trial = require_live_trial(trial_id)
            if trial.status != "planned" or not trial.evaluation_id:
                raise HTTPException(status_code=409, detail="Only a planned evaluation scene can be placed.")
            next_trial = tasks.next_evaluation_trial(trial.evaluation_id)
            active = tasks.active_trial()
            if next_trial is None or next_trial.id != trial.id or active is not None:
                raise HTTPException(status_code=409, detail="Finish the preceding trial before placing this scene.")
            scene = scene_for_trial(trial, tasks)
            if scene is None:
                raise HTTPException(status_code=409, detail="Scene manifest is missing.")
            if preflight.station.status()["state"] != "idle":
                raise HTTPException(status_code=409, detail="Wait for the robot station to be idle.")
            return scene_fixture.place(scene)
        except StationUnavailable as exc:
            raise HTTPException(status_code=503, detail="Robot station is unavailable.") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            station_movement.release()

    @app.get("/api/evaluations/{evaluation_id}/report", response_model=EvaluationReport)
    def get_evaluation_report(evaluation_id: str) -> EvaluationReport:
        evaluation = require_live_evaluation(evaluation_id)
        return evaluations.report(evaluation, tasks, episodes)

    @app.post("/api/evaluations/{evaluation_id}/promote", response_model=DeploymentStatus)
    def promote_evaluation(evaluation_id: str) -> DeploymentStatus:
        evaluation = require_live_evaluation(evaluation_id)
        if evaluations.report(evaluation, tasks, episodes).decision != "improved":
            raise HTTPException(status_code=409, detail="The evaluation has not verified improvement.")
        tasks.set_deployment(evaluation.task_id, evaluation.candidate_checkpoint, evaluation.id)
        return get_deployment(evaluation.task_id)

    return app


app = create_app()
