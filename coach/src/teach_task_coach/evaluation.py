"""Predeclared paired trials and a measured before/after verdict."""

from __future__ import annotations

import datetime as dt
import random
import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from teach_task_coach.storage import CoachDatabase, EpisodeStore
from teach_task_coach.tasks import HeldoutScene, TaskStore, Trial


class EvaluationRequest(BaseModel):
    fine_tune_job_id: str
    minimum_effect: float = Field(default=0.15, ge=0, lt=1, allow_inf_nan=False)
    auto_promote: bool = False
    planned_pairs: int = Field(default=30, ge=1, le=512)


class Evaluation(BaseModel):
    id: str
    task_id: str
    fine_tune_job_id: str
    baseline_checkpoint: str
    candidate_checkpoint: str
    minimum_effect: float
    created_at: str
    auto_promote: bool = False
    planned_pairs: int = 30


class EvaluationReport(BaseModel):
    evaluation_id: str
    target_pairs: int
    usable_pairs: int
    baseline_successes: int
    candidate_successes: int
    baseline_reviewed: int = 0
    candidate_reviewed: int = 0
    baseline_only: int
    candidate_only: int
    paired_difference: float | None
    ci_low: float | None
    ci_high: float | None
    exact_p_value: float | None
    baseline_safety_stops: int
    candidate_safety_stops: int
    decision: Literal["improved", "inconclusive", "worse", "not_evaluable"]
    reason: str
    problems: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    input_sha256: str | None = None
    baseline_interventions: int = 0
    candidate_interventions: int = 0
    baseline_mean_duration_s: float | None = None
    candidate_mean_duration_s: float | None = None
    baseline_mean_first_response_s: float | None = None
    candidate_mean_first_response_s: float | None = None


class LiveEvaluation(BaseModel):
    task_name: str
    evaluation: Evaluation
    report: EvaluationReport


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class EvaluationStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.db = CoachDatabase(data_dir)

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id),
                fine_tune_job_id TEXT NOT NULL,
                baseline_checkpoint TEXT NOT NULL,
                candidate_checkpoint TEXT NOT NULL,
                minimum_effect REAL NOT NULL,
                created_at TEXT NOT NULL,
                auto_promote INTEGER NOT NULL DEFAULT 0,
                planned_pairs INTEGER NOT NULL DEFAULT 30
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(evaluations)")}
        if "auto_promote" not in columns:
            connection.execute("ALTER TABLE evaluations ADD COLUMN auto_promote INTEGER NOT NULL DEFAULT 0")
        if "planned_pairs" not in columns:
            connection.execute("ALTER TABLE evaluations ADD COLUMN planned_pairs INTEGER NOT NULL DEFAULT 30")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS evaluation_audits (
                id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
                snapshot_json TEXT NOT NULL,
                report_json TEXT NOT NULL,
                audited_at TEXT NOT NULL
            )"""
        )

    def create(
        self,
        task_id: str,
        fine_tune_job_id: str,
        candidate_checkpoint: str,
        minimum_effect: float,
        tasks: TaskStore,
        auto_promote: bool = False,
        planned_pairs: int = 30,
    ) -> Evaluation:
        task = tasks.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        scenes = tasks.ensure_heldout_scenes(task_id, planned_pairs)
        if candidate_checkpoint == task.baseline_checkpoint:
            raise ValueError("Candidate and baseline checkpoints must differ.")
        evaluation = Evaluation(
            id=uuid.uuid4().hex,
            task_id=task_id,
            fine_tune_job_id=fine_tune_job_id,
            baseline_checkpoint=task.baseline_checkpoint,
            candidate_checkpoint=candidate_checkpoint,
            minimum_effect=minimum_effect,
            created_at=_now(),
            auto_promote=auto_promote,
            planned_pairs=planned_pairs,
        )
        rng = random.Random(int(evaluation.id[:16], 16))
        rng.shuffle(scenes)
        candidate_first = [True] * (planned_pairs // 2) + [False] * (planned_pairs - planned_pairs // 2)
        rng.shuffle(candidate_first)
        with self.db.connect() as connection:
            tasks._schema(connection)
            self._schema(connection)
            connection.execute(
                """INSERT INTO evaluations
                   (id, task_id, fine_tune_job_id, baseline_checkpoint, candidate_checkpoint,
                    minimum_effect, created_at, auto_promote, planned_pairs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evaluation.id, task_id, fine_tune_job_id,
                    evaluation.baseline_checkpoint, candidate_checkpoint,
                    minimum_effect, evaluation.created_at, int(auto_promote), planned_pairs,
                ),
            )
            sequence = 0
            for scene, first_is_candidate in zip(scenes, candidate_first, strict=True):
                checkpoints = (
                    (candidate_checkpoint, task.baseline_checkpoint)
                    if first_is_candidate else (task.baseline_checkpoint, candidate_checkpoint)
                )
                for checkpoint in checkpoints:
                    connection.execute(
                        """INSERT INTO trials
                           (id, task_id, start_cell, setup_note, status, created_at, checkpoint,
                            evaluation_id, scene_index, sequence_index, purpose)
                           VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, 'evaluation')""",
                        (
                            uuid.uuid4().hex, task_id, scene.start_cell,
                            (f"Held-out scene {scene.scene_index + 1}: place object at "
                             f"({scene.x_fraction:.3f}, {scene.y_fraction:.3f}) of marked table; "
                             f"rotate {scene.angle_deg} degrees."),
                            evaluation.created_at, checkpoint, evaluation.id,
                            scene.scene_index, sequence,
                        ),
                    )
                    sequence += 1
        return evaluation

    def get(self, evaluation_id: str) -> Evaluation | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute(
                "SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)
            ).fetchone()
        return None if row is None else Evaluation.model_validate(dict(row))

    def list(self, task_id: str) -> list[Evaluation]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM evaluations WHERE task_id = ? ORDER BY created_at DESC, rowid DESC", (task_id,)
            ).fetchall()
        return [Evaluation.model_validate(dict(row)) for row in rows]

    def latest(self) -> Evaluation | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute(
                "SELECT * FROM evaluations ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return None if row is None else Evaluation.model_validate(dict(row))

    def audit(
        self, evaluation: Evaluation, tasks: TaskStore, episodes: EpisodeStore,
        *, heldout_attested: bool, resets_attested: bool,
    ):
        """Append an auditable snapshot; never start or promote a robot run."""
        from teach_task_coach.paired_audit import evaluate_paired
        from teach_task_coach.paired_snapshot import export_paired_snapshot

        if not heldout_attested or not resets_attested:
            raise ValueError("Confirm training holdout and scene resets before final audit.")
        snapshot = export_paired_snapshot(
            evaluation, tasks, episodes,
            heldout_attested=heldout_attested, resets_attested=resets_attested,
        )
        report = evaluate_paired(snapshot)
        with self.db.connect() as connection:
            self._schema(connection)
            connection.execute(
                "INSERT INTO evaluation_audits VALUES (?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, evaluation.id, snapshot.model_dump_json(),
                 report.model_dump_json(), _now()),
            )
        return report

    def latest_audit(self, evaluation_id: str):
        from teach_task_coach.paired_audit import PairedReport, PairedRequest

        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute(
                """SELECT snapshot_json, report_json FROM evaluation_audits
                   WHERE evaluation_id = ? ORDER BY rowid DESC LIMIT 1""",
                (evaluation_id,),
            ).fetchone()
        if row is None:
            return None
        return (PairedRequest.model_validate_json(row["snapshot_json"]),
                PairedReport.model_validate_json(row["report_json"]))

    def report(
        self, evaluation: Evaluation, tasks: TaskStore, episodes: EpisodeStore
    ) -> EvaluationReport:
        from teach_task_coach.paired_audit import evaluate_paired
        from teach_task_coach.paired_snapshot import export_paired_snapshot

        saved = self.latest_audit(evaluation.id)
        if saved is None:
            snapshot = export_paired_snapshot(
                evaluation, tasks, episodes, heldout_attested=False, resets_attested=False,
            )
            audit = evaluate_paired(snapshot)
            problems = [*audit.problems, "No reviewed paired audit has been saved."]
        else:
            original, stored_report = saved
            snapshot = export_paired_snapshot(
                evaluation, tasks, episodes,
                heldout_attested=original.plan.heldout_attested,
                resets_attested=original.plan.resets_attested,
            )
            audit = evaluate_paired(snapshot)
            problems = list(audit.problems)
            if audit.input_sha256 != stored_report.input_sha256:
                problems.append("Evidence changed since the saved audit; run the audit again.")
        decision = audit.decision if not problems else "not_evaluable"
        interval = audit.difference_interval if decision != "not_evaluable" else None
        return EvaluationReport(
            evaluation_id=evaluation.id,
            target_pairs=evaluation.planned_pairs,
            usable_pairs=audit.usable_pairs,
            baseline_successes=audit.baseline_successes,
            candidate_successes=audit.candidate_successes,
            baseline_reviewed=sum(
                pair.baseline is not None and pair.baseline.outcome in {"success", "failure"}
                for pair in snapshot.pairs
            ),
            candidate_reviewed=sum(
                pair.candidate is not None and pair.candidate.outcome in {"success", "failure"}
                for pair in snapshot.pairs
            ),
            baseline_only=audit.baseline_only,
            candidate_only=audit.candidate_only,
            paired_difference=audit.observed_difference if interval else None,
            ci_low=interval[0] if interval else None,
            ci_high=interval[1] if interval else None,
            exact_p_value=None,
            baseline_safety_stops=audit.baseline_safety_stops,
            candidate_safety_stops=audit.candidate_safety_stops,
            decision="worse" if decision == "regressed" else decision,
            reason=("Saved audit verified a useful improvement." if decision == "improved"
                    else "Saved audit found regression." if decision == "regressed"
                    else "The evidence does not clear the predeclared improvement threshold."
                    if decision == "inconclusive" else "; ".join(problems)),
            problems=problems,
            warnings=list(audit.warnings),
            input_sha256=audit.input_sha256 if saved else None,
            baseline_interventions=audit.baseline_interventions,
            candidate_interventions=audit.candidate_interventions,
            baseline_mean_duration_s=audit.baseline_mean_duration_s,
            candidate_mean_duration_s=audit.candidate_mean_duration_s,
            baseline_mean_first_response_s=audit.baseline_mean_first_response_s,
            candidate_mean_first_response_s=audit.candidate_mean_first_response_s,
        )


def scene_for_trial(trial: Trial, tasks: TaskStore) -> HeldoutScene | None:
    if trial.scene_index is None:
        return None
    return next(
        (scene for scene in tasks.heldout_scenes(trial.task_id) if scene.scene_index == trial.scene_index),
        None,
    )
