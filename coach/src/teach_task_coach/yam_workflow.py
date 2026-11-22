"""Bounded background YAM collection and paired simulator evaluation for DreamCoach."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Literal
from uuid import UUID, uuid4
from zipfile import ZipFile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
from teach_task_coach.preflight import PreflightService
from teach_task_coach.simulator_setup import SimulatorSetup
from teach_task_coach.tasks import TaskInput, TaskStore

BASE = "dreamlabs/dream-1-beta"
PROMPT = "pick up the apple"
SUCCESS_RULE = "Hold the apple at least 8 cm above its starting height for two continuous seconds."
REQUESTS_PER_TRIAL = 12
MIN_ACTION_ROWS = REQUESTS_PER_TRIAL * 48
SCRIPTS = Path(__file__).resolve().parents[2] / "experiments/yam_sim_faas"
BUNDLED_DATASET_HASH = "779f088ac959f21dcd4b50d3947912442b7e9ef950efe862d18808bdd2c64212"
BUNDLED_EVIDENCE = ("apple_paired_confirmation.json", "second_account_paired_confirmation.json")


class CollectionRequest(BaseModel):
    scenes: int = Field(default=4, ge=1, le=8)
    source: Literal["fresh", "bundled"] = "fresh"


class ComparisonRequest(BaseModel):
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    job_id: str = Field(min_length=1, max_length=200)
    pairs: int = Field(default=4, ge=2, le=8)


class ExistingComparisonRequest(BaseModel):
    checkpoint: str = Field(min_length=1, max_length=200)


class YamJob(BaseModel):
    id: str
    kind: Literal["collection", "import", "comparison"]
    task_id: str
    total: int
    completed: int = 0
    demos: int = 0
    state: Literal["running", "stopping", "completed", "cancelled", "failed"] = "running"
    message: str


class YamComparison(BaseModel):
    task_id: str
    baseline: str
    candidate: str
    report: PairedReport


class SimulatorRunError(RuntimeError):
    pass


def write_json(path: Path, data: str) -> None:
    next_path = path.with_suffix(".tmp")
    next_path.write_text(data, encoding="utf-8")
    next_path.replace(path)


def command(script: str, *args: str, timeout: int) -> str:
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            cwd=SCRIPTS,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise SimulatorRunError("The simulator exceeded its time limit. Check Dream model availability.") from exc
    if result.returncode:
        # Child diagnostics can include provider responses. Only expose fixed guidance to chat.
        raise SimulatorRunError(
            "A Dream rollout or local replay failed. Check the selected checkpoint and Dream access before retrying."
        )
    return result.stdout


def workflow_result(*args: str, timeout: int = 90) -> dict[str, Any]:
    output = command("score_workflow_rollout.py", *args, timeout=timeout)
    for line in reversed(output.splitlines()):
        if line.startswith("WORKFLOW_RESULT="):
            return json.loads(line.removeprefix("WORKFLOW_RESULT="))
    raise SimulatorRunError("The simulator did not return a verified result.")


class YamWorkflow:
    def __init__(self, root: Path, tasks: TaskStore, demos: DemoStore, faas: FaaSStore,
                 setup: SimulatorSetup, preflight: PreflightService) -> None:
        self.root = root
        self.tasks = tasks
        self.demos = demos
        self.faas = faas
        self.setup = setup
        self.preflight = preflight
        self.lock = Lock()
        self.cancel = Event()
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
            assert self.job is not None
            self._save(self.job.model_copy(update=changes))

    def status(self) -> YamJob | None:
        with self.lock:
            return self.job

    def _check_start(self, *checkpoints: str) -> None:
        if self.job and self.job.state in ("running", "stopping"):
            raise ValueError("Finish or stop the current simulator run first.")
        if not checkpoints:
            return
        if self.setup.status().state != "ready":
            raise ValueError("Prepare the YAM simulator before recording.")
        check, models = self.preflight.check_dream()
        if check.state != "ready":
            raise ValueError(check.message)
        ready = {model.id for model in models if model.servable}
        if not ready.issuperset(checkpoints):
            raise ValueError("The requested checkpoints are not all available in this Dream account.")

    def _launch(self, job: YamJob, worker, *args: Any) -> YamJob:
        self.cancel.clear()
        self._save(job)
        Thread(target=self._work, args=(worker, *args), daemon=True, name="dreamcoach-yam").start()
        return job

    def _work(self, worker, *args: Any) -> None:
        try:
            worker(*args)
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
        archive = SCRIPTS / "grasp_training/independent.zip"
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != BUNDLED_DATASET_HASH:
                raise SimulatorRunError("The bundled archive did not match its published hash.")
        output = folder / "demos"
        with ZipFile(archive) as zipped:
            zipped.extractall(output)
        demos = [read_demo(path.parent.parent, job.task_id) for path in output.glob("*/meta/info.json")]
        if len(demos) != 24 or any(not demo.valid or demo.task_text != PROMPT for demo in demos):
            raise SimulatorRunError("The bundled archive did not contain 24 valid apple pickup demos.")
        for demo in demos:
            self.demos.upsert(demo)
        self._update(state="completed", completed=1, demos=len(demos),
                     message="The bundled apple pickup demos are ready to review.")

    def existing_checkpoints(self) -> list[str]:
        resources = files("teach_task_coach").joinpath("examples")
        return [
            PairedRequest.model_validate_json(resources.joinpath(name).read_text(encoding="utf-8"))
            .plan.candidate_checkpoint for name in BUNDLED_EVIDENCE
        ]

    def start_existing_comparison(self, value: ExistingComparisonRequest) -> YamJob:
        with self.lock:
            if value.checkpoint not in self.existing_checkpoints():
                raise ValueError("Only a checkpoint from the verified apple pickup examples can be reused here.")
            self._check_start(BASE, value.checkpoint)
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
        if not self.cancel.is_set():
            return False
        self._update(state="cancelled", message="Stopped. Completed trials remain available.")
        return True

    def _record(self, folder: Path, checkpoint: str, seed: int, *, heldout: bool = False) -> dict:
        command(
            "record_dream_model_rollout.py", "--output", str(folder), "--model", checkpoint,
            "--seed", str(seed), "--start-pose", "wrist-visible", "--max-requests",
            str(REQUESTS_PER_TRIAL), "--score-only", timeout=660,
        )
        args = ("--held-out-seed", str(seed)) if heldout else ()
        score = workflow_result(str(folder), *args)
        if (
            score["seed"] != seed or score["checkpoint"] != checkpoint
            or score["model_action_rows"] < MIN_ACTION_ROWS or score["height_source"] != "recorded"
        ):
            raise SimulatorRunError("A rollout ended before the full action budget or lacked recorded height.")
        return score

    def _collect(self, job: YamJob, folder: Path, seeds: list[int]) -> None:
        eligible = folder / "failures"
        eligible.mkdir()
        failures = 0
        for index, seed in enumerate(seeds, 1):
            if self._stopped():
                return
            self._update(message=f"Recording Dream-1 on training scene {index} of {job.total}.")
            score = self._record(folder / f"training-{index}", BASE, seed)
            if not score["success"]:
                source = Path(score["folder"])
                source.rename(eligible / source.name)
                failures += 1
            self._update(completed=index)
        if self._stopped():
            return
        if failures == 0:
            self._update(state="completed", message="All recorded training scenes succeeded. No corrections were needed.")
            return
        self._update(message=f"Generating and validating corrections for {failures} failed scenes.")
        output = folder / "demos"
        manifest = workflow_result(
            str(eligible), "--collect-into", str(output), "--max-demos", str(job.total), timeout=1200,
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

    def comparison(self, task_id: str) -> YamComparison | None:
        path = self.root / task_id / "comparison-evidence.json"
        with self.lock:
            if not path.is_file():
                return None
            snapshot = PairedRequest.model_validate_json(path.read_text(encoding="utf-8"))
        return YamComparison(task_id=task_id, baseline=snapshot.plan.baseline_checkpoint,
                             candidate=snapshot.plan.candidate_checkpoint, report=evaluate_paired(snapshot))

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
                except SimulatorRunError:
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

    @router.post("/compare-existing", response_model=YamJob, status_code=202)
    def compare_existing(value: ExistingComparisonRequest) -> YamJob:
        try:
            return workflow.start_existing_comparison(value)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/workflow/stop", response_model=YamJob | None)
    def stop() -> YamJob | None:
        return workflow.stop()

    @router.get("/comparisons/{task_id}", response_model=YamComparison | None)
    def comparison(task_id: str) -> YamComparison | None:
        try:
            normalized = UUID(hex=task_id).hex
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Simulator task not found.") from exc
        return workflow.comparison(normalized)

    return router
