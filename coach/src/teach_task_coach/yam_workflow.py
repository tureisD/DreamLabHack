"""Bounded background YAM collection and paired simulator evaluation for DreamCoach."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import re
import subprocess
import sys
from collections import OrderedDict
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Literal
from uuid import UUID, uuid4
from zipfile import ZipFile

from dream.errors import DreamError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from teach_task_coach.demos import DemoStore, read_demo
from teach_task_coach.faas import FaaSStore, FineTuneRecord
from teach_task_coach.paired_audit import (
    InterruptedAttempt,
    MatchedPair,
    PairAttempt,
    PairedReport,
    PairedRequest,
    PairPlan,
    evaluate_paired,
)
from teach_task_coach.preflight import ModelSummary, PreflightService
from teach_task_coach.simulator_process import SimulatorProcessCancelled, run_simulator_process
from teach_task_coach.simulator_setup import SimulatorSetup
from teach_task_coach.tasks import TaskInput, TaskStore
from teach_task_coach.yam_goals import BOWL_EVALUATION_RULE, BOWL_PROMPT, BOWL_TASK_RULE

BASE = "dreamlabs/dream-1-beta"
PROMPT = "pick up the apple"
SUCCESS_RULE = "Hold the apple at least 8 cm above its starting height for two continuous seconds."
REQUESTS_PER_TRIAL = 12
MIN_ACTION_ROWS = REQUESTS_PER_TRIAL * 48
SCRIPTS = Path(__file__).resolve().parents[2] / "experiments/yam_sim_faas"
BUNDLED_DATASET_HASH = "779f088ac959f21dcd4b50d3947912442b7e9ef950efe862d18808bdd2c64212"
BUNDLED_EVIDENCE = (
    ("apple_paired_confirmation.json", "dima24kor/apple-grasp-varied-3374a5388381"),
    ("second_account_paired_confirmation.json", "mary.m.koryakina/apple-grasp-independent-779f088ac959"),
)
RESET_TIMEOUT = 10
YamGoal = Literal["pickup", "bowl"]


class CollectionRequest(BaseModel):
    scenes: int = Field(default=4, ge=1, le=8)
    source: Literal["fresh", "bundled"] = "fresh"


class ComparisonRequest(BaseModel):
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    job_id: str = Field(min_length=1, max_length=200)
    pairs: int = Field(default=4, ge=2, le=8)


class ExistingComparisonRequest(BaseModel):
    checkpoint: str = Field(min_length=1, max_length=200)
    goal: YamGoal = "pickup"


class ExistingCheckpoint(BaseModel):
    checkpoint: str
    dataset: str
    steps: int | None


class TrialDiagnosis(BaseModel):
    code: str
    title: str
    summary: str
    evidence: list[str]
    next_step: str | None = None


class TrainingTrialDiagnosis(BaseModel):
    scene: int
    seed: int
    diagnosis: TrialDiagnosis


class YamJob(BaseModel):
    id: str
    kind: Literal["collection", "import", "comparison"]
    task_id: str
    total: int
    completed: int = 0
    demos: int = 0
    state: Literal["running", "stopping", "completed", "cancelled", "failed"] = "running"
    message: str
    goal: YamGoal = "pickup"
    training_trial_diagnostics: list[TrainingTrialDiagnosis] = Field(default_factory=list)


class YamComparison(BaseModel):
    task_id: str
    baseline: str
    candidate: str
    report: PairedReport
    goal: YamGoal = "pickup"


class YamComparisonDiagnostics(BaseModel):
    evaluation_id: str
    trials: dict[str, TrialDiagnosis]


class SavedComparison(BaseModel):
    seeds: tuple[int, ...]
    evidence: PairedRequest
    pending: InterruptedAttempt | None = None


class ResumableComparison(BaseModel):
    id: str
    task_id: str
    task: str
    candidate: str
    completed: int
    total: int
    created_at: dt.datetime
    goal: YamGoal = "pickup"


class SavedDiagnosis(BaseModel):
    checkpoint: str
    seed: int
    outcome: Literal["success", "failure", "invalid"]
    diagnosis: TrialDiagnosis


class SimulatorRunError(RuntimeError):
    def __init__(self, message: str, code: str = "unverified_rollout", *, evidence: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.evidence = evidence


def unverified_rollout(code: str, detail: str | None = None) -> TrialDiagnosis:
    causes = {
        "simulator_timeout": ("Simulation timed out", "The recorder or replay did not finish within its time limit."),
        "recording_failed": ("Recording failed", "The simulator could not finish recording the model's actions."),
        "replay_failed": ("Replay could not be verified", "The local scorer could not verify this recorded trajectory."),
        "short_recording": ("Rollout stopped before scoring", "The recording ended before the planned action budget was used."),
        "missing_height": ("Apple height was missing", "The recording did not supply the height needed to score the hold."),
        "dream_session_replaced": ("Dream replaced the inference session", "The inference session ended before the rollout could finish."),
        "action_chunk_rejected": ("YAM rejected a model action", "The simulator rejected an action response before executing that chunk."),
        "dream_warming_timeout": ("Model was still warming", "Dream had not made the model ready before the trial clock expired."),
    }
    title, summary = causes.get(code, (
        "Trial could not be scored", "There is no verified result for this recording."
    ))
    next_step = {
        "dream_session_replaced": "Check whether the selected checkpoint is available, then resume the comparison.",
        "action_chunk_rejected": "Check that the checkpoint uses the YAM joint-space action format and inspect the local rejected-action log.",
        "dream_warming_timeout": "Wait for the checkpoint to become ready before running another comparison.",
    }.get(code, "Check the simulator run status, then repeat the trial to get a scored result.")
    evidence = ["This attempt cannot establish whether the task succeeded or failed."]
    if detail:
        evidence.insert(0, detail)
    return TrialDiagnosis(
        code=code, title=title, summary=summary,
        evidence=evidence, next_step=next_step,
    )


def saved_metrics_diagnosis(attempt: PairAttempt, threshold_m: float) -> TrialDiagnosis:
    if attempt.outcome in ("invalid", "unknown"):
        return unverified_rollout("unverified_rollout")
    if attempt.bowl_placement is not None:
        placement = attempt.bowl_placement
        return TrialDiagnosis(
            code="bowl_placed" if attempt.outcome == "success" else "bowl_miss",
            title="Bowl placement passed" if attempt.outcome == "success" else "Bowl placement missed",
            summary=f"The apple was settled in the bowl for the final {placement.settled_s:.2f} seconds.",
            evidence=[f"Final distance from bowl center: {100 * placement.final_distance_m:.1f} cm."],
            next_step=None if attempt.outcome == "success" else "Review the grasp, transfer, and release.",
        )
    evidence = []
    if attempt.held_lift_m is not None:
        evidence.append(f"Best two-second lift: {max(0, attempt.held_lift_m) * 100:.2f} cm.")
    if attempt.peak_lift_m is not None:
        evidence.append(f"Peak lift: {max(0, attempt.peak_lift_m) * 100:.2f} cm.")
    if attempt.first_close_after_warmup_s is not None:
        evidence.append(f"First recorded left-gripper close command: {attempt.first_close_after_warmup_s:.2f} s after warm-up.")
    if attempt.outcome == "success":
        return TrialDiagnosis(
            code="passed", title="Lift and hold passed",
            summary="The saved score confirms the apple met the height and hold rule.",
            evidence=evidence,
        )
    target = threshold_m * 100
    if attempt.peak_lift_m is None:
        title, summary = "Cause unavailable", "The saved result records a miss without enough evidence to locate the cause."
    elif attempt.peak_lift_m >= threshold_m:
        title = "Lift was too brief"
        summary = f"The apple reached {target:g} cm but did not stay there for two continuous seconds."
    else:
        title = "Lift stayed below target"
        summary = f"The apple never reached the {target:g} cm target. The score alone cannot distinguish a missed grasp from a weak lift."
    return TrialDiagnosis(
        code="saved_score_only", title=title, summary=summary,
        evidence=[*evidence, "Verified replay details are unavailable for this trial."],
        next_step="Inspect the original trace or repeat the scene to see what happened at the grasp.",
    )


def recording_failure(folder: Path) -> SimulatorRunError | None:
    sidecar = next(folder.glob("*/rollout.json"), None)
    if sidecar is None:
        return None
    try:
        rollout = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rollout, dict):
        return None
    simulation = rollout.get("simulation", {})
    if not isinstance(simulation, dict):
        simulation = {}
    if simulation.get("action_chunk_rejected") is True:
        return SimulatorRunError(
            "The YAM control loop rejected a model action before executing that chunk.",
            "action_chunk_rejected",
        )
    if simulation.get("warming_timeout") is True:
        return SimulatorRunError(
            "Dream was still warming this checkpoint when the trial reached its time limit.",
            "dream_warming_timeout",
        )
    if rollout.get("error") != "DreamSessionExpired":
        return None
    replacement_reason = simulation.get("last_session_replacement_reason")
    reason = {
        "expired": "the previous session expired",
        "unknown": "Dream no longer recognized the previous session",
        "serve_died": "the model server stopped",
    }.get(replacement_reason) if isinstance(replacement_reason, str) else None
    rows = simulation.get("model_action_rows", 0)
    replacements = simulation.get("session_replacements")
    if not isinstance(replacements, int):
        outcome = "The rollout ended when Dream replaced its inference session."
    else:
        outcome = f"The rollout reached the retry limit after {replacements} Dream session replacements."
    if reason:
        outcome += f" Dream reported that {reason}."
    else:
        outcome += " Dream’s specific reason is unavailable."
    if isinstance(rows, int):
        outcome += f" The partial recording saved {rows} of {MIN_ACTION_ROWS} model actions."
    return SimulatorRunError(outcome, "dream_session_replaced", evidence=outcome)


def write_json(path: Path, data: str) -> None:
    next_path = path.with_suffix(".tmp")
    next_path.write_text(data, encoding="utf-8")
    next_path.replace(path)


def command(script: str, *args: str, timeout: int, cancel: Event | None = None) -> str:
    try:
        result = run_simulator_process(
            [sys.executable, str(SCRIPTS / script), *args],
            cwd=SCRIPTS,
            timeout=timeout,
            cancel=cancel,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise SimulatorRunError(
            "The simulator exceeded its time limit. Check Dream model availability.", "simulator_timeout",
        ) from exc
    if result.returncode:
        # Child diagnostics can include provider responses. Only expose fixed guidance to chat.
        raise SimulatorRunError(
            "A Dream rollout or local replay failed. Check the selected checkpoint and Dream access before retrying.",
            "recording_failed" if script == "record_dream_model_rollout.py" else "replay_failed",
        )
    return result.stdout


def workflow_result(*args: str, timeout: int = 90, cancel: Event | None = None) -> dict[str, Any]:
    output = command("score_workflow_rollout.py", *args, timeout=timeout, cancel=cancel)
    for line in reversed(output.splitlines()):
        if line.startswith("WORKFLOW_RESULT="):
            return json.loads(line.removeprefix("WORKFLOW_RESULT="))
    raise SimulatorRunError("The simulator did not return a verified result.")


class YamWorkflow:
    def __init__(self, root: Path, tasks: TaskStore, demos: DemoStore, faas: FaaSStore,
                 setup: SimulatorSetup, preflight: PreflightService,
                 list_finetunes: Callable[[], list[dict[str, Any]]] | None = None) -> None:
        self.root = root
        self.tasks = tasks
        self.demos = demos
        self.faas = faas
        self.setup = setup
        self.preflight = preflight
        self.list_finetunes = list_finetunes
        self.lock = Lock()
        self._diagnosis_lock = Lock()
        self._diagnosis_cache: OrderedDict[tuple[Path, str], TrialDiagnosis] = OrderedDict()
        self.cancel = Event()
        self._reset_lock = Lock()
        self._reset_requested = Event()
        self._thread: Thread | None = None
        self.job: YamJob | None = None
        self.root.mkdir(parents=True, exist_ok=True)
        saved = self.root / "job.json"
        if saved.is_file():
            self.job = YamJob.model_validate_json(saved.read_text(encoding="utf-8"))
            if self.job.state in ("running", "stopping"):
                recovered = {
                    "state": "failed", "message": "The server restarted during the simulator run. Saved evidence is retained."
                }
                if self.job.kind == "comparison":
                    snapshot = self._comparison_snapshot(self.job.task_id, self.job.id)
                    if snapshot is not None:
                        usable = evaluate_paired(snapshot).usable_pairs
                        recovered["completed"] = usable
                        if usable == self.job.total:
                            recovered.update(state="completed", message="Matched simulator comparison finished.")
                self._save(self.job.model_copy(update=recovered))

    def _save(self, job: YamJob) -> None:
        write_json(self.root / "job.json", job.model_dump_json())
        self.job = job

    def _update(self, **changes: Any) -> None:
        with self.lock:
            if self._reset_requested.is_set():
                return
            assert self.job is not None
            self._save(self.job.model_copy(update=changes))

    def status(self) -> YamJob | None:
        with self.lock:
            return self.job

    def reset_session(self) -> None:
        """Stop simulator work and clear the last run summary after the worker exits."""
        with self._reset_lock:
            with self.lock:
                self._reset_requested.set()
                thread = self._thread
                if self.job and self.job.state in ("running", "stopping"):
                    self._save(self.job.model_copy(update={
                        "state": "stopping", "message": "Resetting the simulator for a fresh session."
                    }))
            if thread is not None:
                thread.join(timeout=RESET_TIMEOUT)
                if thread.is_alive():
                    raise TimeoutError("The simulator is still stopping. Try Begin again.")
            with self.lock:
                (self.root / "job.json").unlink(missing_ok=True)
                self.job = None
                self._thread = None
                self.cancel.clear()
                self._reset_requested.clear()

    def _check_start(self, *checkpoints: str) -> list[ModelSummary]:
        if self._reset_requested.is_set():
            raise ValueError("The simulator is resetting. Try again after it stops.")
        if self.job and self.job.state in ("running", "stopping"):
            raise ValueError("Finish or stop the current simulator run first.")
        if not checkpoints:
            return []
        if self.setup.status().state != "ready":
            raise ValueError("Prepare the YAM simulator before recording.")
        check, models = self.preflight.check_dream()
        if check.state != "ready":
            raise ValueError(check.message)
        ready = {model.id for model in models if model.servable}
        if not ready.issuperset(checkpoints):
            raise ValueError("The requested checkpoints are not all available in this Dream account.")
        return models

    def _launch(self, job: YamJob, worker, *args: Any) -> YamJob:
        self.cancel.clear()
        self._save(job)
        self._thread = Thread(
            target=self._work, args=(worker, *args), daemon=True, name="dreamcoach-yam"
        )
        self._thread.start()
        return job

    def _work(self, worker, *args: Any) -> None:
        try:
            worker(*args)
        except SimulatorProcessCancelled:
            return
        except SimulatorRunError as exc:
            self._update(state="failed", message=str(exc))
        except Exception:  # noqa: BLE001 - deliver an error state even on unexpected worker failures
            self._update(state="failed", message="The simulator could not finish. Check local simulator setup and try again.")

    def _new_task(self, scenes: int, *, goal: YamGoal = "pickup") -> tuple[Path, list[int], list[int]]:
        task = self.tasks.create_task(TaskInput(
            name="Apple placement · click to correct" if goal == "bowl" else "Apple pickup · YAM simulator",
            prompt=BOWL_PROMPT if goal == "bowl" else PROMPT,
            baseline_checkpoint=BASE, success_rule=BOWL_TASK_RULE if goal == "bowl" else SUCCESS_RULE,
        ))
        folder = self.root / task.id
        folder.mkdir()
        rng = random.SystemRandom()
        # Disjoint namespaces keep our held-out scenes out of all guided training batches.
        heldout = rng.sample(range(2**31, 2**32), 8)
        training = rng.sample(range(1_000_000, 2**31), scenes)
        write_json(folder / "scenes.json", json.dumps({"training": training, "heldout": heldout}))
        return folder, training, heldout

    def start_collection(self, value: CollectionRequest) -> YamJob:
        with self.lock:
            if value.source == "bundled":
                self._check_start()
                folder, _, _ = self._new_task(0)
                job = YamJob(id=uuid4().hex, kind="import", task_id=folder.name, total=24,
                             message="Opening the bundled apple pickup demos.")
                return self._launch(job, self._import_bundled, job, folder)
            self._check_start(BASE)
            folder, training, _ = self._new_task(value.scenes)
            job = YamJob(id=uuid4().hex, kind="collection", task_id=folder.name, total=value.scenes,
                         message="Starting Dream-1 on fresh YAM training scenes.")
            return self._launch(job, self._collect, job, folder, training)

    def _import_bundled(self, job: YamJob, folder: Path) -> None:
        if self._stopped():
            return
        archive = SCRIPTS / "grasp_training/independent.zip"
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != BUNDLED_DATASET_HASH:
                raise SimulatorRunError("The bundled archive did not match its published hash.")
        output = folder / "demos"
        with ZipFile(archive) as zipped:
            zipped.extractall(output)
        paths = sorted(output.glob("*/meta/info.json"))
        if len(paths) != job.total:
            raise SimulatorRunError("The bundled archive did not contain 24 valid apple pickup demos.")
        demos = []
        for index, path in enumerate(paths, 1):
            if self._stopped():
                return
            demo = read_demo(path.parent.parent, job.task_id)
            if not demo.valid or demo.task_text != PROMPT:
                raise SimulatorRunError("The bundled archive did not contain 24 valid apple pickup demos.")
            demos.append(demo)
            self._update(completed=index, message=f"Checked {index} of {job.total} bundled demos.")
        if self._stopped():
            return
        for demo in demos:
            self.demos.upsert(demo)
        self._update(state="completed", completed=job.total, demos=len(demos),
                     message="The bundled apple pickup demos are ready to review.")

    def existing_checkpoints(self) -> list[str]:
        return [item.checkpoint for item in self._bundled_choices()]

    def _bundled_choices(self) -> list[ExistingCheckpoint]:
        resources = files("teach_task_coach").joinpath("examples")
        choices = []
        for name, dataset in BUNDLED_EVIDENCE:
            example = PairedRequest.model_validate_json(resources.joinpath(name).read_text(encoding="utf-8"))
            choices.append(ExistingCheckpoint(checkpoint=example.plan.candidate_checkpoint, dataset=dataset, steps=500))
        return choices

    def list_existing_checkpoints(self, goal: YamGoal = "pickup") -> list[ExistingCheckpoint]:
        check, models = self.preflight.check_dream()
        return self._eligible_choices(models, goal) if check.state == "ready" else []

    def _eligible_choices(self, models: list[ModelSummary], goal: YamGoal = "pickup") -> list[ExistingCheckpoint]:
        ready = {model.id for model in models if model.servable}
        if BASE not in ready:
            return []
        choices = ({item.checkpoint: item for item in self._bundled_choices() if item.checkpoint in ready}
                   if goal == "pickup" else {})
        if self.list_finetunes is None:
            return list(choices.values())
        try:
            jobs = self.list_finetunes()
        except DreamError:
            return list(choices.values())

        remote = {
            job["fine_tuned_model"]: job for job in jobs
            if job.get("status") == "succeeded" and isinstance(job.get("fine_tuned_model"), str)
            and job["fine_tuned_model"] in ready
        }
        for checkpoint, item in choices.items():
            job = remote.get(checkpoint)
            if job and isinstance(job.get("dataset"), str) and job["dataset"].strip():
                choices[checkpoint] = item.model_copy(update={"dataset": job["dataset"]})

        # The remote catalogue identifies the training dataset, but does not attest its
        # task or joint conventions. For other models require a proven local YAM workflow.
        for job in self.faas.list_finetunes():
            checkpoint = job.checkpoint
            if not checkpoint or checkpoint in choices or checkpoint == BASE or job.status != "succeeded" or job.use_eef:
                continue
            account_job = remote.get(checkpoint)
            if not account_job or not job.remote_job_id or account_job.get("id") != job.remote_job_id:
                continue
            dataset = self.faas.get_dataset(job.dataset_version_id)
            if dataset is None or dataset.status != "validated" or not dataset.remote_name:
                continue
            if account_job.get("dataset") != dataset.remote_name or account_job.get("base_model") != BASE:
                continue
            parameters = account_job.get("hyperparameters")
            if isinstance(parameters, dict) and parameters.get("use_eef") is True:
                continue
            task = self.tasks.get_task(dataset.task_id)
            if task is None or task.offline_mode or self._task_goal(task) != goal:
                continue
            if goal == "pickup" and not (self.root / task.id / "scenes.json").is_file():
                continue
            if goal == "bowl":
                try:
                    self._bowl_training_seeds(job)
                except ValueError:
                    continue
            choices[checkpoint] = ExistingCheckpoint(checkpoint=checkpoint, dataset=dataset.remote_name, steps=job.steps)
        return list(choices.values())

    def start_existing_comparison(self, value: ExistingComparisonRequest) -> YamJob:
        with self.lock:
            models = self._check_start(BASE, value.checkpoint)
            if not any(item.checkpoint == value.checkpoint for item in self._eligible_choices(models, value.goal)):
                raise ValueError("Choose an available joint-space YAM checkpoint verified for this task.")
            folder, _, heldout = self._new_task(0, goal=value.goal)
            if value.goal == "bowl":
                source = next(job for job in self.faas.list_finetunes() if job.checkpoint == value.checkpoint)
                heldout = self._bowl_seeds(self._bowl_training_seeds(source), 4)
            job = YamJob(id=uuid4().hex, kind="comparison", task_id=folder.name, total=4,
                         goal=value.goal, message="Starting fresh held-out trials with the existing checkpoint.")
            return self._start_new_comparison(job, folder, heldout[:4], value.checkpoint)

    @staticmethod
    def _task_goal(task) -> YamGoal | None:
        if task.baseline_checkpoint != BASE:
            return None
        if task.prompt == BOWL_PROMPT and task.success_rule == BOWL_TASK_RULE:
            return "bowl"
        if task.prompt == PROMPT and task.success_rule == SUCCESS_RULE:
            return "pickup"
        return None

    @staticmethod
    def _bowl_seeds(excluded: set[int], pairs: int) -> list[int]:
        rng = random.SystemRandom()
        seeds = rng.sample(range(2**31, 2**32), pairs)
        while excluded.intersection(seeds):
            seeds = rng.sample(range(2**31, 2**32), pairs)
        return seeds

    def _bowl_training_seeds(self, job: FineTuneRecord) -> set[int]:
        error = "Bowl evaluation needs the original YAM Fruit correction demos with recorded training seeds."
        seeds: set[int] = set()
        parents = {item.checkpoint: item for item in self.faas.list_finetunes() if item.checkpoint}
        seen = set()
        current: FineTuneRecord | None = job
        while current is not None:
            if current.id in seen or current.use_eef or current.status != "succeeded":
                raise ValueError(error)
            seen.add(current.id)
            dataset = self.faas.get_dataset(current.dataset_version_id)
            if dataset is None or dataset.status != "validated" or not dataset.demo_ids:
                raise ValueError(error)
            for demo_id in dataset.demo_ids:
                demo = self.demos.get(demo_id)
                if demo is None or demo.task_text != BOWL_PROMPT or demo.origin != "scripted_reference":
                    raise ValueError(error)
                try:
                    receipt = json.loads((Path(demo.source_path) / "click_correction.json").read_text(encoding="utf-8"))
                    if (receipt["method"] != "click_to_correct_simulation" or receipt["goal"]["kind"] != "bowl"
                        or receipt["goal"]["fruit"] != "apple" or receipt["physics"]["passed"] is not True
                        or receipt["export_replay"]["passed"] is not True
                        or type(receipt["seed"]) is not int or not 0 <= receipt["seed"] < 2**32):
                        raise ValueError(error)
                    seeds.add(receipt["seed"])
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    raise ValueError(error) from exc
            if current.resume_from is None:
                return seeds
            current = parents.get(current.resume_from)
            if current is None:
                raise ValueError(error)
        return seeds

    def start_comparison(self, value: ComparisonRequest) -> YamJob:
        with self.lock:
            folder = self.root / value.task_id
            split = folder / "scenes.json"
            task = self.tasks.get_task(value.task_id)
            job = self.faas.get_finetune(value.job_id)
            dataset = self.faas.get_dataset(job.dataset_version_id) if job else None
            goal = self._task_goal(task) if task and not task.offline_mode else None
            if (goal is None or not job or not dataset or dataset.task_id != task.id
                or (goal == "pickup" and not split.is_file())):
                raise ValueError("Choose a completed fine-tune from this guided YAM task.")
            if job.status != "succeeded" or not job.checkpoint or job.checkpoint == BASE:
                raise ValueError("Wait until Dream publishes the fine-tuned checkpoint.")
            if job.use_eef:
                raise ValueError("Choose a checkpoint trained in YAM joint space. This comparison cannot use end-effector actions.")
            if goal == "bowl":
                seeds = self._bowl_seeds(self._bowl_training_seeds(job), value.pairs)
                self._check_start(BASE, job.checkpoint)
                folder.mkdir(exist_ok=True)
                current = YamJob(id=uuid4().hex, kind="comparison", task_id=task.id, total=len(seeds),
                                 goal=goal, message="Starting matched apple-into-bowl trials.")
                return self._start_new_comparison(current, folder, seeds, job.checkpoint)
            split_problem = "The saved task does not have enough distinct held-out scenes outside training. Create a fresh YAM comparison."
            try:
                manifest = json.loads(split.read_text(encoding="utf-8"))
                training, heldout = manifest["training"], manifest["heldout"]
            except (OSError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(split_problem) from exc
            if not all(isinstance(group, list) and all(
                type(seed) is int and 0 <= seed < 2**32 for seed in group
            ) for group in (training, heldout)):
                raise ValueError(split_problem)
            seeds = heldout[:value.pairs]
            if len(set(seeds)) != value.pairs or set(seeds).intersection(training):
                raise ValueError(split_problem)
            self._check_start(BASE, job.checkpoint)
            current = YamJob(id=uuid4().hex, kind="comparison", task_id=task.id, total=len(seeds),
                             message="Starting matched base and fine-tune simulator trials.")
            return self._start_new_comparison(current, folder, seeds, job.checkpoint)

    def _start_new_comparison(self, job: YamJob, folder: Path, seeds: list[int], candidate: str) -> YamJob:
        bowl = job.goal == "bowl"
        plan = PairPlan(
            evaluation_id=job.id, task=BOWL_PROMPT if bowl else PROMPT,
            success_rule=BOWL_EVALUATION_RULE if bowl else SUCCESS_RULE,
            reset_protocol="Reset YAM and the apple to the same seed for each model.",
            assignment_protocol="Alternate whether the fine-tune or base runs first.",
            protocol_ref="apple-into-bowl-v1" if bowl else "scenes.json",
            baseline_checkpoint=BASE, candidate_checkpoint=candidate,
            collection_mode="simulation", planned_pairs=len(seeds), created_at=dt.datetime.now(dt.UTC),
            required_model_rows=MIN_ACTION_ROWS, simulator_hold_threshold_m=None if bowl else 0.08,
            simulator_goal="apple_into_bowl_v1" if bowl else None,
        )
        self._write_run(folder, SavedComparison(seeds=tuple(seeds), evidence=PairedRequest(plan=plan, pairs=())))
        return self._launch(job, self._compare, job, folder, seeds, candidate)

    def resumable_comparisons(self) -> list[ResumableComparison]:
        with self.lock:
            results = []
            for folder in self.root.iterdir():
                if not re.fullmatch(r"[0-9a-f]{32}", folder.name) or not folder.is_dir():
                    continue
                comparison_ids = {path.stem for path in (folder / "comparisons").glob("*.json")}
                try:
                    legacy = self._legacy_snapshot(folder)
                    if legacy is not None:
                        comparison_ids.add(legacy.plan.evaluation_id)
                except (OSError, ValidationError):
                    pass
                for comparison_id in comparison_ids:
                    if self.job and self.job.id == comparison_id and self.job.state in ("running", "stopping"):
                        continue
                    try:
                        run = self._resumable_run(folder, comparison_id)
                    except ValueError:
                        continue
                    plan = run.evidence.plan
                    results.append(ResumableComparison(
                        id=plan.evaluation_id, task_id=folder.name, task=plan.task, candidate=plan.candidate_checkpoint,
                        completed=self._completed_pairs(run), total=plan.planned_pairs, created_at=plan.created_at,
                        goal="bowl" if plan.simulator_goal else "pickup",
                    ))
            return sorted(results, key=lambda option: option.created_at, reverse=True)

    def resume_comparison(self, task_id: str, comparison_id: str) -> YamJob:
        with self.lock:
            folder = self.root / task_id
            run = self._resumable_run(folder, comparison_id)
            plan = run.evidence.plan
            self._check_start(plan.baseline_checkpoint, plan.candidate_checkpoint)
            job = YamJob(id=comparison_id, kind="comparison", task_id=task_id, total=plan.planned_pairs,
                         goal="bowl" if plan.simulator_goal else "pickup",
                         completed=self._completed_pairs(run), message="Resuming the same held-out comparison.")
            self._write_run(folder, run)
            return self._launch(job, self._compare, job, folder, list(run.seeds), plan.candidate_checkpoint)

    def stop(self) -> YamJob | None:
        with self.lock:
            if self.job and self.job.state == "running":
                self.cancel.set()
                self._save(self.job.model_copy(update={
                    "state": "stopping", "message": "Stopping after the current simulator rollout."
                }))
            return self.job

    def _stopped(self) -> bool:
        if self._reset_requested.is_set():
            return True
        if not self.cancel.is_set():
            return False
        self._update(state="cancelled", message="Stopped. Completed trials remain available.")
        return True

    def _record(self, folder: Path, checkpoint: str, seed: int, *, heldout: bool = False,
                goal: YamGoal = "pickup") -> dict:
        split_args = ("--comparison-trial",) if heldout else ()
        task_args = ("--task", BOWL_PROMPT) if goal == "bowl" else ()
        pose = "home" if goal == "bowl" else "wrist-visible"
        try:
            command(
                "record_dream_model_rollout.py", "--output", str(folder), "--model", checkpoint,
                "--seed", str(seed), "--start-pose", pose, "--max-requests",
                str(REQUESTS_PER_TRIAL), "--score-only", *split_args, *task_args,
                timeout=660, cancel=self._reset_requested,
            )
        except SimulatorRunError as exc:
            failure = recording_failure(folder)
            if failure is not None:
                raise failure from exc
            raise
        goal_args = {"goal": goal} if goal == "bowl" else {}
        return self._score_recording(folder, checkpoint, seed, heldout=heldout, **goal_args)

    def _score_recording(self, folder: Path, checkpoint: str, seed: int, *, heldout: bool,
                         goal: YamGoal = "pickup") -> dict:
        args = ("--held-out-seed", str(seed)) if heldout else ()
        score = workflow_result(str(folder), *args, "--diagnose", cancel=self._reset_requested)
        if score["seed"] != seed or score["checkpoint"] != checkpoint:
            raise SimulatorRunError("The saved rollout did not match the selected scene and checkpoint.")
        if score["model_action_rows"] < MIN_ACTION_ROWS:
            raise SimulatorRunError(
                "The rollout ended before the full action budget.", "short_recording",
                evidence=f"The saved recording has {score['model_action_rows']} of {MIN_ACTION_ROWS} model actions.",
            )
        if score["height_source"] != "recorded":
            raise SimulatorRunError("The rollout lacked recorded apple height.", "missing_height")
        if goal == "bowl" and (score.get("task") != BOWL_PROMPT or score.get("bowl_placement") is None):
            raise SimulatorRunError("The rollout lacked recorded apple-into-bowl evidence.", "replay_failed")
        if goal == "pickup" and score.get("bowl_placement") is not None:
            raise SimulatorRunError("This recording belongs to a different simulator task.", "replay_failed")
        try:
            diagnosis = TrialDiagnosis.model_validate(score.get("diagnosis"))
        except ValidationError:
            score["diagnosis"] = None
        else:
            score["diagnosis"] = diagnosis
            self._save_diagnosis(folder, checkpoint, seed, "success" if score["success"] else "failure", diagnosis)
        return score

    @staticmethod
    def _save_diagnosis(folder: Path, checkpoint: str, seed: int,
                        outcome: Literal["success", "failure", "invalid"], diagnosis: TrialDiagnosis) -> None:
        saved = SavedDiagnosis(checkpoint=checkpoint, seed=seed, outcome=outcome, diagnosis=diagnosis)
        try:
            folder.mkdir(exist_ok=True)
            write_json(folder / "diagnosis.json", saved.model_dump_json())
        except OSError:
            # A derived diagnostic must not invalidate the authoritative score.
            pass

    def _collect(self, job: YamJob, folder: Path, seeds: list[int]) -> None:
        eligible = folder / "failures"
        eligible.mkdir()
        failures = 0
        diagnosed = []
        for index, seed in enumerate(seeds, 1):
            if self._stopped():
                return
            self._update(message=f"Recording Dream-1 on training scene {index} of {job.total}.")
            try:
                score = self._record(folder / f"training-{index}", BASE, seed)
            except SimulatorRunError as exc:
                diagnosed.append(TrainingTrialDiagnosis(
                    scene=index, seed=seed, diagnosis=unverified_rollout(exc.code, exc.evidence),
                ))
                self._update(training_trial_diagnostics=diagnosed.copy())
                raise
            if score.get("diagnosis") is not None:
                diagnosed.append(TrainingTrialDiagnosis(scene=index, seed=seed, diagnosis=score["diagnosis"]))
            if not score["success"]:
                source = Path(score["folder"])
                source.rename(eligible / source.name)
                failures += 1
            self._update(completed=index, training_trial_diagnostics=diagnosed.copy())
        if self._stopped():
            return
        if failures == 0:
            self._update(state="completed", message="All recorded training scenes succeeded. No corrections were needed.")
            return
        self._update(message=f"Generating and validating corrections for {failures} failed scenes.")
        output = folder / "demos"
        manifest = workflow_result(
            str(eligible), "--collect-into", str(output), "--max-demos", str(job.total),
            timeout=1200, cancel=self._reset_requested,
        )
        if self._stopped():
            return
        sessions = [read_demo(output / item["demo_folder"], job.task_id) for item in manifest["sessions"]]
        if not sessions or any(not demo.valid or demo.task_text != PROMPT for demo in sessions):
            raise SimulatorRunError("The generated demos did not pass DreamCoach validation.")
        for demo in sessions:
            self.demos.upsert(demo)
        self._update(state="completed", demos=len(sessions),
                     message="Validated simulator demos are ready for camera review.")

    @staticmethod
    def _legacy_snapshot(folder: Path) -> PairedRequest | None:
        path = folder / "comparison-evidence.json"
        return PairedRequest.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None

    @staticmethod
    def _write_run(folder: Path, run: SavedComparison) -> None:
        directory = folder / "comparisons"
        directory.mkdir(exist_ok=True)
        write_json(directory / f"{run.evidence.plan.evaluation_id}.json", run.model_dump_json(indent=2))

    @staticmethod
    def _completed_pairs(run: SavedComparison) -> int:
        return sum(pair.baseline is not None and pair.candidate is not None
                   and pair.baseline.outcome in ("success", "failure")
                   and pair.candidate.outcome in ("success", "failure") for pair in run.evidence.pairs)

    def _resumable_run(self, folder: Path, comparison_id: str) -> SavedComparison:
        error = "This comparison has no unfinished trials with a verifiable saved plan."
        if not re.fullmatch(r"[0-9a-f]{32}", comparison_id):
            raise ValueError(error)
        task = self.tasks.get_task(folder.name)
        if task is None or task.offline_mode:
            raise ValueError(error)
        path = folder / "comparisons" / f"{comparison_id}.json"
        try:
            if path.is_file():
                run = SavedComparison.model_validate_json(path.read_text(encoding="utf-8"))
            else:
                legacy = self._legacy_snapshot(folder)
                if legacy is None:
                    raise ValueError(error)
                split = json.loads((folder / "scenes.json").read_text(encoding="utf-8"))
                seeds = tuple(split["heldout"][:legacy.plan.planned_pairs])
                if set(seeds).intersection(split["training"]):
                    raise ValueError(error)
                run = SavedComparison(seeds=seeds, evidence=legacy)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError(error) from exc
        plan = run.evidence.plan
        goal = self._task_goal(task)
        expected_rule = BOWL_EVALUATION_RULE if goal == "bowl" else SUCCESS_RULE
        expected_protocol = "apple-into-bowl-v1" if goal == "bowl" else "scenes.json"
        scene_ids = [str(seed) for seed in run.seeds]
        if (
            goal is None or (goal == "bowl") != (plan.simulator_goal is not None)
            or plan.task != task.prompt or plan.success_rule != expected_rule or plan.protocol_ref != expected_protocol
            or plan.simulator_hold_threshold_m != (None if goal == "bowl" else 0.08)
            or plan.evaluation_id != comparison_id or plan.collection_mode != "simulation"
            or plan.baseline_checkpoint != BASE or plan.required_model_rows != MIN_ACTION_ROWS
            or len(set(run.seeds)) != plan.planned_pairs or len(run.seeds) != plan.planned_pairs
            or any(not 0 <= seed < 2**32 for seed in run.seeds)
            or any(pair.pair_id != pair.scenario_id or pair.scenario_id not in scene_ids
                   for pair in run.evidence.pairs)
            or [pair.scenario_id for pair in run.evidence.pairs] != scene_ids[:len(run.evidence.pairs)]
            or any(item.scenario_id not in scene_ids for item in run.evidence.interruptions)
            or (run.pending and not self._valid_pending(run.pending, plan, scene_ids))
            or self._completed_pairs(run) == plan.planned_pairs
        ):
            raise ValueError(error)
        return run

    @staticmethod
    def _valid_pending(item: InterruptedAttempt, plan: PairPlan, scene_ids: list[str]) -> bool:
        checkpoint = plan.baseline_checkpoint if item.role == "baseline" else plan.candidate_checkpoint
        return (
            item.scenario_id in scene_ids and item.attempt.checkpoint_id == checkpoint
            and item.attempt.training_exposure == "held_out"
            and item.attempt.outcome == "invalid"
            and YamWorkflow._matches_trial(item.attempt, plan.evaluation_id, item.scenario_id, item.role)
        )

    def _comparison_snapshot(self, task_id: str, evaluation_id: str | None = None) -> PairedRequest | None:
        folder = self.root / task_id
        with self.lock:
            if evaluation_id is None and self.job and self.job.task_id == task_id and self.job.kind == "comparison":
                evaluation_id = self.job.id
            archive = folder / "comparisons"
            if evaluation_id is None:
                path = max(archive.glob("*.json"), key=lambda value: value.stat().st_mtime_ns, default=None)
            else:
                path = archive / f"{evaluation_id}.json"
            if path is not None and path.is_file():
                return SavedComparison.model_validate_json(path.read_text(encoding="utf-8")).evidence
            legacy = self._legacy_snapshot(folder)
            return legacy if legacy is not None and evaluation_id in (None, legacy.plan.evaluation_id) else None

    def comparison(self, task_id: str, evaluation_id: str | None = None) -> YamComparison | None:
        snapshot = self._comparison_snapshot(task_id, evaluation_id)
        if snapshot is None:
            return None
        return YamComparison(task_id=task_id, baseline=snapshot.plan.baseline_checkpoint,
                             candidate=snapshot.plan.candidate_checkpoint, report=evaluate_paired(snapshot),
                             goal="bowl" if snapshot.plan.simulator_goal else "pickup")

    @staticmethod
    def _matches_trial(attempt: PairAttempt, evaluation_id: str, scene_id: str, role: str) -> bool:
        prefix = f"{evaluation_id}-{scene_id}-{role}"
        return bool(re.fullmatch(re.escape(prefix) + r"(?:-retry-[0-9a-f]{8})?", attempt.trial_id)
                    and attempt.source_uri == f"local-rollout://{attempt.trial_id}")

    def comparison_diagnostics(self, task_id: str, evaluation_id: str | None = None) -> YamComparisonDiagnostics | None:
        snapshot = self._comparison_snapshot(task_id, evaluation_id)
        if snapshot is None:
            return None
        plan = snapshot.plan
        threshold = plan.simulator_hold_threshold_m or 0.08
        trials = {}
        local_trials = []
        attempts = [(pair.scenario_id, role, attempt) for pair in snapshot.pairs
                    for role, attempt in (("baseline", pair.baseline), ("candidate", pair.candidate)) if attempt]
        attempts.extend((entry.scenario_id, entry.role, entry.attempt) for entry in snapshot.interruptions)
        for scene_id, role, attempt in attempts:
            trials[attempt.trial_id] = saved_metrics_diagnosis(attempt, threshold)
            if (re.fullmatch(r"[0-9]{1,10}", scene_id) and re.fullmatch(r"[0-9a-f]{32}", plan.evaluation_id)
                and int(scene_id) < 2**32 and self._matches_trial(attempt, plan.evaluation_id, scene_id, role)):
                trial = self._local_trial_folder(task_id, attempt.trial_id)
                if trial is not None:
                    local_trials.append((trial, int(scene_id), attempt))
        trials.update(self._diagnose_local_trials(local_trials, threshold))
        return YamComparisonDiagnostics(evaluation_id=plan.evaluation_id, trials=trials)

    def _local_trial_folder(self, task_id: str, trial_id: str) -> Path | None:
        task_folder = (self.root / task_id).resolve()
        trial = (task_folder / trial_id).resolve()
        if task_folder.parent != self.root.resolve() or trial.parent != task_folder or not trial.is_dir():
            return None
        return trial

    @staticmethod
    def _read_saved_diagnosis(trial: Path, seed: int, attempt: PairAttempt) -> TrialDiagnosis | None:
        try:
            path = (trial / "diagnosis.json").resolve()
            if path.parent == trial:
                saved = SavedDiagnosis.model_validate_json(path.read_text(encoding="utf-8"))
                if (saved.seed, saved.checkpoint, saved.outcome) == (seed, attempt.checkpoint_id, attempt.outcome):
                    return saved.diagnosis
        except (OSError, ValidationError):
            pass
        return None

    def _diagnose_local_trials(
        self, trials: list[tuple[Path, int, PairAttempt]], threshold: float,
    ) -> dict[str, TrialDiagnosis]:
        diagnosed = {}
        pending = []
        with self._diagnosis_lock:
            for trial, seed, attempt in trials:
                key = (trial, attempt.outcome)
                saved = self._read_saved_diagnosis(trial, seed, attempt)
                if saved is not None:
                    diagnosed[attempt.trial_id] = saved
                elif key in self._diagnosis_cache:
                    self._diagnosis_cache.move_to_end(key)
                    diagnosed[attempt.trial_id] = self._diagnosis_cache[key]
                elif attempt.outcome in ("success", "failure") and self._verified_trace(trial, seed, attempt):
                    pending.append((trial, seed, attempt))
            if pending:
                args = [{"folder": str(trial), "seed": seed} for trial, seed, _ in pending]
                try:
                    scores = workflow_result(
                        "--diagnose-batch", json.dumps(args), timeout=max(45, 7 * len(args) + 7),
                    ).get("scores", {})
                except (SimulatorRunError, ValueError):
                    scores = {}
                for trial, seed, attempt in pending:
                    score = scores.get(str(trial)) if isinstance(scores, dict) else None
                    diagnosis = self._diagnosis_from_score(score, seed, attempt)
                    diagnosis = diagnosis or saved_metrics_diagnosis(attempt, threshold)
                    diagnosed[attempt.trial_id] = diagnosis
                    self._diagnosis_cache[(trial, attempt.outcome)] = diagnosis
                    if len(self._diagnosis_cache) > 128:
                        self._diagnosis_cache.popitem(last=False)
        return diagnosed

    @staticmethod
    def _verified_trace(trial: Path, seed: int, attempt: PairAttempt) -> bool:
        try:
            [sidecar] = trial.glob("*/rollout.json")
            parquet = sidecar.parent / "data/chunk-000/episode_000000.parquet"
            if not sidecar.resolve().is_relative_to(trial) or not parquet.resolve().is_relative_to(trial):
                return False
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            return (
                metadata["status"] == "complete" and metadata["simulation"]["source"] == "model"
                and metadata["simulation"]["seed"] == seed and metadata["checkpoint"] == attempt.checkpoint_id
            )
        except (OSError, ValueError, KeyError, TypeError):
            return False

    @staticmethod
    def _diagnosis_from_score(score: dict | None, seed: int, attempt: PairAttempt) -> TrialDiagnosis | None:
        if not isinstance(score, dict):
            return None
        try:
            if (
                score["seed"] != seed or score["checkpoint"] != attempt.checkpoint_id
                or score["model_action_rows"] != attempt.model_action_rows
                or score["success"] != (attempt.outcome == "success")
                or score["height_source"] != attempt.height_source
            ):
                return None
            if attempt.bowl_placement is not None:
                if (score.get("task") != BOWL_PROMPT
                    or score.get("bowl_placement") != attempt.bowl_placement.model_dump()):
                    return None
            elif attempt.held_lift_m is None or abs(score["held_lift_m"] - attempt.held_lift_m) > 0.0001:
                return None
            return TrialDiagnosis.model_validate(score.get("diagnosis"))
        except (ValueError, KeyError, TypeError):
            return None

    @staticmethod
    def _scored_attempt(attempt: PairAttempt, score: dict) -> PairAttempt:
        return PairAttempt.model_validate(attempt.model_dump() | {
            "recorded_at": score["started_at"],
            "outcome": "success" if score["success"] else "failure",
            "model_action_rows": score["model_action_rows"], "held_lift_m": score["held_lift_m"],
            "peak_lift_m": score["peak_lift_m"], "duration_s": score["duration_s"],
            "first_close_after_warmup_s": score["first_close_after_warmup_s"],
            "replay_max_state_error_m": score["replay_max_state_error"], "height_source": "recorded",
            "bowl_placement": score.get("bowl_placement"),
        })

    def _recover_score(self, trial: Path, pending: InterruptedAttempt, goal: YamGoal) -> dict | None:
        if not any(trial.glob("*/rollout.json")):
            return None
        try:
            goal_args = {"goal": goal} if goal == "bowl" else {}
            return self._score_recording(
                trial, pending.attempt.checkpoint_id, int(pending.scenario_id), heldout=True, **goal_args,
            )
        except (SimulatorRunError, ValueError, KeyError, TypeError):
            return None

    def _store_outcome(
        self, folder: Path, run: SavedComparison, pair: MatchedPair | None,
        scene_id: str, role: str, attempt: PairAttempt,
    ) -> SavedComparison:
        attempts = {"baseline": pair.baseline, "candidate": pair.candidate} if pair else {}
        attempts[role] = attempt
        result = MatchedPair(pair_id=scene_id, scenario_id=scene_id, **attempts)
        pairs = tuple(result if saved.scenario_id == scene_id else saved for saved in run.evidence.pairs)
        if pair is None:
            pairs += (result,)
        updated = run.model_copy(update={"pending": None, "evidence": run.evidence.model_copy(update={"pairs": pairs})})
        with self.lock:
            self._write_run(folder, updated)
        return updated

    def _compare(self, job: YamJob, folder: Path, seeds: list[int], candidate: str) -> None:
        path = folder / "comparisons" / f"{job.id}.json"
        run = SavedComparison.model_validate_json(path.read_text(encoding="utf-8"))
        plan = run.evidence.plan
        for index, seed in enumerate(seeds, 1):
            scene_id = str(seed)
            roles = (("baseline", plan.baseline_checkpoint), ("candidate", candidate))
            for role, checkpoint in roles if index % 2 else reversed(roles):
                if self._stopped():
                    return
                pair = next((item for item in run.evidence.pairs if item.scenario_id == scene_id), None)
                previous = getattr(pair, role) if pair else None
                if previous is not None and previous.outcome in ("success", "failure"):
                    continue
                label = "base" if role == "baseline" else "fine-tune"
                self._update(message=f"Running {label} on held-out scene {index} of {job.total}.")
                pending = run.pending
                if pending and (pending.scenario_id, pending.role) != (scene_id, role):
                    raise SimulatorRunError("The saved in-flight trial does not match the frozen scene order.")
                if pending is not None:
                    trial_dir = folder / pending.attempt.trial_id
                    score = self._recover_score(trial_dir, pending, job.goal)
                    if score is not None:
                        run = self._store_outcome(folder, run, pair, scene_id, role,
                                                  self._scored_attempt(pending.attempt, score))
                        continue
                    self._save_diagnosis(trial_dir, checkpoint, seed, "invalid", unverified_rollout(
                        "interrupted", "The previous run stopped before a complete score could be recovered.",
                    ))
                elif previous is not None:
                    pending = InterruptedAttempt(scenario_id=scene_id, role=role, attempt=previous)

                interruptions = run.evidence.interruptions
                if pending:
                    interruptions += (pending,)
                trial = f"{job.id}-{seed}-{role}"
                if (folder / trial).exists() or any(
                    (item.scenario_id, item.role) == (scene_id, role) for item in interruptions
                ):
                    trial += f"-retry-{uuid4().hex[:8]}"
                attempt = PairAttempt(
                    trial_id=trial, episode_id=trial, checkpoint_id=checkpoint,
                    source_uri=f"local-rollout://{trial}", session_id=trial,
                    outcome="invalid", training_exposure="held_out",
                )
                # The invalid prior slot and its replacement marker are written together.
                # A restart can recover the replacement from a completed local recording.
                pairs = run.evidence.pairs
                if previous is not None:
                    other_role = "candidate" if role == "baseline" else "baseline"
                    other = getattr(pair, other_role)
                    pairs = tuple(
                        item for item in pairs if item.scenario_id != scene_id or other is not None
                    )
                    if other is not None:
                        pair = pair.model_copy(update={role: None})
                        pairs = tuple(pair if item.scenario_id == scene_id else item for item in pairs)
                    else:
                        pair = None
                run = run.model_copy(update={
                    "evidence": run.evidence.model_copy(update={"pairs": pairs, "interruptions": interruptions}),
                    "pending": InterruptedAttempt(scenario_id=scene_id, role=role, attempt=attempt),
                })
                with self.lock:
                    self._write_run(folder, run)
                try:
                    goal_args = {"goal": job.goal} if job.goal == "bowl" else {}
                    score = self._record(folder / trial, checkpoint, seed, heldout=True, **goal_args)
                except SimulatorRunError as exc:
                    if self._reset_requested.is_set():
                        return
                    self._save_diagnosis(folder / trial, checkpoint, seed, "invalid",
                                         unverified_rollout(exc.code, exc.evidence))
                    self._store_outcome(folder, run, pair, scene_id, role, attempt)
                    raise
                run = self._store_outcome(folder, run, pair, scene_id, role, self._scored_attempt(attempt, score))
            if index > job.completed:
                self._update(completed=index)
        self._update(state="completed", message="Matched simulator comparison finished.")


def yam_router(workflow: YamWorkflow) -> APIRouter:
    router = APIRouter(prefix="/api/simulator")

    @router.get("/workflow", response_model=YamJob | None)
    def status() -> YamJob | None:
        return workflow.status()

    @router.post("/collect", response_model=YamJob, status_code=202)
    def collect(value: CollectionRequest) -> YamJob:
        try:
            return workflow.start_collection(value)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/compare", response_model=YamJob, status_code=202)
    def compare(value: ComparisonRequest) -> YamJob:
        try:
            return workflow.start_comparison(value)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/example-checkpoints", response_model=list[str])
    def example_checkpoints() -> list[str]:
        return workflow.existing_checkpoints()

    @router.get("/existing-checkpoints", response_model=list[ExistingCheckpoint])
    def existing_checkpoints(goal: YamGoal = "pickup") -> list[ExistingCheckpoint]:
        return workflow.list_existing_checkpoints(goal)

    @router.post("/compare-existing", response_model=YamJob, status_code=202)
    def compare_existing(value: ExistingComparisonRequest) -> YamJob:
        try:
            return workflow.start_existing_comparison(value)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/workflow/stop", response_model=YamJob | None)
    def stop() -> YamJob | None:
        return workflow.stop()

    @router.post("/workflow/quit")
    def quit_run() -> None:
        try:
            workflow.reset_session()
        except TimeoutError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/resumable-comparisons", response_model=list[ResumableComparison])
    def resumable_comparisons() -> list[ResumableComparison]:
        return workflow.resumable_comparisons()

    @router.post("/comparisons/{task_id}/{comparison_id}/resume", response_model=YamJob, status_code=202)
    def resume_comparison(task_id: str, comparison_id: str) -> YamJob:
        try:
            return workflow.resume_comparison(UUID(hex=task_id).hex, UUID(hex=comparison_id).hex)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/comparisons/{task_id}", response_model=YamComparison | None)
    def comparison(task_id: str, evaluation_id: str | None = None) -> YamComparison | None:
        try:
            normalized = UUID(hex=task_id).hex
            selected = UUID(hex=evaluation_id).hex if evaluation_id else None
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Simulator task not found.") from exc
        return workflow.comparison(normalized, selected)

    @router.get("/comparisons/{task_id}/diagnostics", response_model=YamComparisonDiagnostics | None)
    def comparison_diagnostics(task_id: str, evaluation_id: str | None = None) -> YamComparisonDiagnostics | None:
        try:
            normalized = UUID(hex=task_id).hex
            selected = UUID(hex=evaluation_id).hex if evaluation_id else None
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Simulator task not found.") from exc
        return workflow.comparison_diagnostics(normalized, selected)

    return router
