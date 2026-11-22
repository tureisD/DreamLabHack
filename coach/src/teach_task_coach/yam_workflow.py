"""Bounded background YAM collection and paired simulator evaluation for DreamCoach."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
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
from teach_task_coach.faas import FaaSStore
from teach_task_coach.paired_audit import (
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


class CollectionRequest(BaseModel):
    scenes: int = Field(default=4, ge=1, le=8)
    source: Literal["fresh", "bundled"] = "fresh"


class ComparisonRequest(BaseModel):
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    job_id: str = Field(min_length=1, max_length=200)
    pairs: int = Field(default=4, ge=2, le=8)


class ExistingComparisonRequest(BaseModel):
    checkpoint: str = Field(min_length=1, max_length=200)


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
    training_trial_diagnostics: list[TrainingTrialDiagnosis] = Field(default_factory=list)


class YamComparison(BaseModel):
    task_id: str
    baseline: str
    candidate: str
    report: PairedReport


class YamComparisonDiagnostics(BaseModel):
    evaluation_id: str
    trials: dict[str, TrialDiagnosis]


class SavedDiagnosis(BaseModel):
    checkpoint: str
    seed: int
    outcome: Literal["success", "failure", "invalid"]
    diagnosis: TrialDiagnosis


class SimulatorRunError(RuntimeError):
    def __init__(self, message: str, code: str = "unverified_rollout") -> None:
        super().__init__(message)
        self.code = code


def unverified_rollout(code: str) -> TrialDiagnosis:
    causes = {
        "simulator_timeout": ("Simulation timed out", "The recorder or replay did not finish within its time limit."),
        "recording_failed": ("Recording failed", "The simulator could not finish recording the model's actions."),
        "replay_failed": ("Replay could not be verified", "The local scorer could not verify this recorded trajectory."),
        "short_recording": ("Rollout stopped before scoring", "The recording ended before the planned action budget was used."),
        "missing_height": ("Apple height was missing", "The recording did not supply the height needed to score the hold."),
    }
    title, summary = causes.get(code, (
        "Trial could not be scored", "There is no verified result for this recording."
    ))
    return TrialDiagnosis(
        code=code, title=title, summary=summary,
        evidence=["This attempt cannot establish whether the grasp succeeded or failed."],
        next_step="Check the simulator run status, then repeat the trial to get a scored result.",
    )


def saved_metrics_diagnosis(attempt: PairAttempt, threshold_m: float) -> TrialDiagnosis:
    if attempt.outcome in ("invalid", "unknown"):
        return unverified_rollout("unverified_rollout")
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


def session_failure_message(folder: Path) -> str | None:
    sidecar = next(folder.glob("*/rollout.json"), None)
    if sidecar is None:
        return None
    try:
        rollout = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rollout, dict) or rollout.get("error") != "DreamSessionExpired":
        return None
    simulation = rollout.get("simulation")
    if not isinstance(simulation, dict):
        return "The rollout ended when Dream replaced its inference session."
    reason = {
        "expired": "the previous session expired",
        "unknown": "Dream no longer recognized the previous session",
        "serve_died": "the model server stopped",
    }.get(simulation.get("last_session_replacement_reason"))
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
    return outcome


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
        self._diagnosis_cache: OrderedDict[tuple[str, str, str], TrialDiagnosis] = OrderedDict()
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
                self._save(self.job.model_copy(update={
                    "state": "failed", "message": "The server restarted during the simulator run. Saved evidence is retained."
                }))

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

    def _new_task(self, scenes: int) -> tuple[Path, list[int], list[int]]:
        task = self.tasks.create_task(TaskInput(
            name="Apple pickup · YAM simulator", prompt=PROMPT,
            baseline_checkpoint=BASE, success_rule=SUCCESS_RULE,
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
                job = YamJob(id=uuid4().hex, kind="import", task_id=folder.name, total=1,
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
        if self._stopped():
            return
        demos = [read_demo(path.parent.parent, job.task_id) for path in output.glob("*/meta/info.json")]
        if len(demos) != 24 or any(not demo.valid or demo.task_text != PROMPT for demo in demos):
            raise SimulatorRunError("The bundled archive did not contain 24 valid apple pickup demos.")
        for demo in demos:
            self.demos.upsert(demo)
        self._update(state="completed", completed=1, demos=len(demos),
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

    def list_existing_checkpoints(self) -> list[ExistingCheckpoint]:
        check, models = self.preflight.check_dream()
        return self._eligible_choices(models) if check.state == "ready" else []

    def _eligible_choices(self, models: list[ModelSummary]) -> list[ExistingCheckpoint]:
        ready = {model.id for model in models if model.servable}
        if BASE not in ready:
            return []
        choices = {item.checkpoint: item for item in self._bundled_choices() if item.checkpoint in ready}
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
            if task is None or task.prompt != PROMPT or task.success_rule != SUCCESS_RULE or task.baseline_checkpoint != BASE:
                continue
            if not (self.root / task.id / "scenes.json").is_file():
                continue
            choices[checkpoint] = ExistingCheckpoint(checkpoint=checkpoint, dataset=dataset.remote_name, steps=job.steps)
        return list(choices.values())

    def start_existing_comparison(self, value: ExistingComparisonRequest) -> YamJob:
        with self.lock:
            models = self._check_start(BASE, value.checkpoint)
            if not any(item.checkpoint == value.checkpoint for item in self._eligible_choices(models)):
                raise ValueError("Choose an available checkpoint verified for the joint-space YAM apple task.")
            folder, _, heldout = self._new_task(0)
            job = YamJob(id=uuid4().hex, kind="comparison", task_id=folder.name, total=4,
                         message="Starting fresh held-out trials with the existing checkpoint.")
            return self._launch(job, self._compare, job, folder, heldout[:4], value.checkpoint)

    def start_comparison(self, value: ComparisonRequest) -> YamJob:
        with self.lock:
            folder = self.root / value.task_id
            split = folder / "scenes.json"
            task = self.tasks.get_task(value.task_id)
            job = self.faas.get_finetune(value.job_id)
            dataset = self.faas.get_dataset(job.dataset_version_id) if job else None
            if not task or not split.is_file() or not job or not dataset or dataset.task_id != task.id:
                raise ValueError("Choose a completed fine-tune from this guided YAM task.")
            if job.status != "succeeded" or not job.checkpoint or job.checkpoint == BASE:
                raise ValueError("Wait until Dream publishes the fine-tuned checkpoint.")
            self._check_start(BASE, job.checkpoint)
            seeds = json.loads(split.read_text(encoding="utf-8"))["heldout"][:value.pairs]
            current = YamJob(id=uuid4().hex, kind="comparison", task_id=task.id, total=len(seeds),
                             message="Starting matched base and fine-tune simulator trials.")
            return self._launch(current, self._compare, current, folder, seeds, job.checkpoint)

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

    def _record(self, folder: Path, checkpoint: str, seed: int, *, heldout: bool = False) -> dict:
        try:
            command(
                "record_dream_model_rollout.py", "--output", str(folder), "--model", checkpoint,
                "--seed", str(seed), "--start-pose", "wrist-visible", "--max-requests",
                str(REQUESTS_PER_TRIAL), "--score-only", timeout=660, cancel=self._reset_requested,
            )
        except SimulatorRunError as exc:
            message = session_failure_message(folder)
            if message:
                raise SimulatorRunError(message, exc.code) from exc
            raise
        args = ("--held-out-seed", str(seed)) if heldout else ()
        score = workflow_result(str(folder), *args, "--diagnose", cancel=self._reset_requested)
        if score["seed"] != seed or score["checkpoint"] != checkpoint:
            raise SimulatorRunError("The saved rollout did not match the selected scene and checkpoint.")
        if score["model_action_rows"] < MIN_ACTION_ROWS:
            raise SimulatorRunError("The rollout ended before the full action budget.", "short_recording")
        if score["height_source"] != "recorded":
            raise SimulatorRunError("The rollout lacked recorded apple height.", "missing_height")
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
                diagnosed.append(TrainingTrialDiagnosis(scene=index, seed=seed, diagnosis=unverified_rollout(exc.code)))
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

    def _save_comparison(self, folder: Path, plan: PairPlan, pairs: list[MatchedPair]) -> None:
        snapshot = PairedRequest(plan=plan, pairs=tuple(pairs))
        with self.lock:
            write_json(folder / "comparison-evidence.json", snapshot.model_dump_json(indent=2))

    def _comparison_snapshot(self, task_id: str) -> PairedRequest | None:
        path = self.root / task_id / "comparison-evidence.json"
        with self.lock:
            if not path.is_file():
                return None
            return PairedRequest.model_validate_json(path.read_text(encoding="utf-8"))

    def comparison(self, task_id: str) -> YamComparison | None:
        snapshot = self._comparison_snapshot(task_id)
        if snapshot is None:
            return None
        return YamComparison(task_id=task_id, baseline=snapshot.plan.baseline_checkpoint,
                             candidate=snapshot.plan.candidate_checkpoint, report=evaluate_paired(snapshot))

    def comparison_diagnostics(self, task_id: str) -> YamComparisonDiagnostics | None:
        snapshot = self._comparison_snapshot(task_id)
        if snapshot is None:
            return None
        plan = snapshot.plan
        threshold = plan.simulator_hold_threshold_m or 0.08
        trials = {}
        for pair in snapshot.pairs:
            for role, attempt in (("baseline", pair.baseline), ("candidate", pair.candidate)):
                if attempt is None:
                    continue
                diagnosis = None
                if (
                    pair.scenario_id.isascii() and pair.scenario_id.isdecimal()
                    and len(pair.scenario_id) <= 10 and len(plan.evaluation_id) == 32
                    and all(char in "0123456789abcdef" for char in plan.evaluation_id)
                ):
                    seed = int(pair.scenario_id)
                    expected = f"{plan.evaluation_id}-{seed}-{role}"
                    if seed < 2**32 and attempt.trial_id == expected and attempt.source_uri == f"local-rollout://{expected}":
                        diagnosis = self._local_trial_diagnosis(task_id, seed, attempt, threshold)
                trials[attempt.trial_id] = diagnosis or saved_metrics_diagnosis(attempt, threshold)
        return YamComparisonDiagnostics(evaluation_id=plan.evaluation_id, trials=trials)

    def _local_trial_diagnosis(
        self, task_id: str, seed: int, attempt: PairAttempt, threshold: float,
    ) -> TrialDiagnosis | None:
        task_folder = (self.root / task_id).resolve()
        trial = (task_folder / attempt.trial_id).resolve()
        if task_folder.parent != self.root.resolve() or trial.parent != task_folder or not trial.is_dir():
            return None
        try:
            path = (trial / "diagnosis.json").resolve()
            if path.parent == trial:
                saved = SavedDiagnosis.model_validate_json(path.read_text(encoding="utf-8"))
                if (saved.seed, saved.checkpoint, saved.outcome) == (seed, attempt.checkpoint_id, attempt.outcome):
                    return saved.diagnosis
        except (OSError, ValidationError):
            pass
        if attempt.outcome not in ("success", "failure"):
            return None
        key = (task_id, attempt.trial_id, attempt.outcome)
        with self._diagnosis_lock:
            if key in self._diagnosis_cache:
                self._diagnosis_cache.move_to_end(key)
                return self._diagnosis_cache[key]
            diagnosis = self._replay_diagnosis(trial, seed, attempt) or saved_metrics_diagnosis(attempt, threshold)
            self._diagnosis_cache[key] = diagnosis
            if len(self._diagnosis_cache) > 128:
                self._diagnosis_cache.popitem(last=False)
            return diagnosis

    @staticmethod
    def _replay_diagnosis(trial: Path, seed: int, attempt: PairAttempt) -> TrialDiagnosis | None:
        try:
            [sidecar] = trial.glob("*/rollout.json")
            parquet = sidecar.parent / "data/chunk-000/episode_000000.parquet"
            if not sidecar.resolve().is_relative_to(trial) or not parquet.resolve().is_relative_to(trial):
                return None
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            if (
                metadata["status"] != "complete" or metadata["simulation"]["source"] != "model"
                or metadata["simulation"]["seed"] != seed or metadata["checkpoint"] != attempt.checkpoint_id
            ):
                return None
            score = workflow_result(str(trial), "--held-out-seed", str(seed), "--diagnose", timeout=15)
            if (
                score["seed"] != seed or score["checkpoint"] != attempt.checkpoint_id
                or score["model_action_rows"] != attempt.model_action_rows
                or score["success"] != (attempt.outcome == "success")
                or score["height_source"] != attempt.height_source
                or attempt.held_lift_m is None or abs(score["held_lift_m"] - attempt.held_lift_m) > 0.0001
            ):
                return None
            return TrialDiagnosis.model_validate(score.get("diagnosis"))
        except (OSError, ValueError, KeyError, TypeError, SimulatorRunError):
            return None

    def _compare(self, job: YamJob, folder: Path, seeds: list[int], candidate: str) -> None:
        plan = PairPlan(
            evaluation_id=job.id, task=PROMPT, success_rule=SUCCESS_RULE,
            reset_protocol="Reset YAM and the apple to the same seed for each model.",
            assignment_protocol="Alternate whether the fine-tune or base runs first.",
            protocol_ref="scenes.json", baseline_checkpoint=BASE, candidate_checkpoint=candidate,
            collection_mode="simulation", planned_pairs=len(seeds), created_at=dt.datetime.now(dt.UTC),
            required_model_rows=MIN_ACTION_ROWS, simulator_hold_threshold_m=0.08,
        )
        pairs: list[MatchedPair] = []
        self._save_comparison(folder, plan, pairs)
        for index, seed in enumerate(seeds, 1):
            roles = (("baseline", BASE), ("candidate", candidate))
            attempts: dict[str, PairAttempt] = {}
            for role, checkpoint in roles if index % 2 else reversed(roles):
                if self._stopped():
                    return
                label = "base" if role == "baseline" else "fine-tune"
                self._update(message=f"Running {label} on held-out scene {index} of {job.total}.")
                trial = f"{job.id}-{seed}-{role}"
                try:
                    score = self._record(folder / trial, checkpoint, seed, heldout=True)
                except SimulatorRunError as exc:
                    if self._reset_requested.is_set():
                        return
                    self._save_diagnosis(folder / trial, checkpoint, seed, "invalid", unverified_rollout(exc.code))
                    attempts[role] = PairAttempt(
                        trial_id=trial, episode_id=trial, checkpoint_id=checkpoint,
                        source_uri=f"local-rollout://{trial}", session_id=trial,
                        outcome="invalid", training_exposure="held_out",
                    )
                    self._save_comparison(folder, plan, [*pairs, MatchedPair(
                        pair_id=str(seed), scenario_id=str(seed), **attempts,
                    )])
                    raise
                attempts[role] = PairAttempt(
                    trial_id=trial, episode_id=trial, checkpoint_id=checkpoint,
                    source_uri=f"local-rollout://{trial}", session_id=trial, recorded_at=score["started_at"],
                    outcome="success" if score["success"] else "failure", training_exposure="held_out",
                    model_action_rows=score["model_action_rows"], held_lift_m=score["held_lift_m"],
                    peak_lift_m=score["peak_lift_m"], duration_s=score["duration_s"],
                    first_close_after_warmup_s=score["first_close_after_warmup_s"],
                    replay_max_state_error_m=score["replay_max_state_error"], height_source="recorded",
                )
                self._save_comparison(folder, plan, [*pairs, MatchedPair(
                    pair_id=str(seed), scenario_id=str(seed), **attempts,
                )])
            pairs.append(MatchedPair(pair_id=str(seed), scenario_id=str(seed), **attempts))
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
    def existing_checkpoints() -> list[ExistingCheckpoint]:
        return workflow.list_existing_checkpoints()

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

    @router.get("/comparisons/{task_id}", response_model=YamComparison | None)
    def comparison(task_id: str) -> YamComparison | None:
        try:
            normalized = UUID(hex=task_id).hex
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Simulator task not found.") from exc
        return workflow.comparison(normalized)

    @router.get("/comparisons/{task_id}/diagnostics", response_model=YamComparisonDiagnostics | None)
    def comparison_diagnostics(task_id: str) -> YamComparisonDiagnostics | None:
        try:
            normalized = UUID(hex=task_id).hex
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Simulator task not found.") from exc
        return workflow.comparison_diagnostics(normalized)

    return router
