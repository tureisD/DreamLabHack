"""Predeclared paired trials and a measured before/after verdict."""

from __future__ import annotations

import datetime as dt
import math
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
    minimum_effect: float = Field(default=0.15, ge=0, le=1)
    auto_promote: bool = False


class Evaluation(BaseModel):
    id: str
    task_id: str
    fine_tune_job_id: str
    baseline_checkpoint: str
    candidate_checkpoint: str
    minimum_effect: float
    created_at: str
    auto_promote: bool = False


class EvaluationReport(BaseModel):
    rule_version: str = 'coach-paired-point-margin-v1'
    population: str = 'station'
    completeness: Literal['incomplete', 'complete']
    missing_pairs: int
    evaluation_id: str
    target_pairs: int
    usable_pairs: int
    baseline_successes: int
    candidate_successes: int
    baseline_only: int
    candidate_only: int
    paired_difference: float | None
    ci_low: float | None
    ci_high: float | None
    exact_p_value: float | None
    baseline_safety_stops: int
    candidate_safety_stops: int
    decision: Literal["improved", "inconclusive", "worse"]
    reason: str


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _paired_interval(differences: list[int], seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(differences)
    samples = sorted(
        sum(differences[rng.randrange(n)] for _ in range(n)) / n for _ in range(10000)
    )
    return samples[249], samples[9749]


def _exact_mcnemar(candidate_only: int, baseline_only: int) -> float:
    discordant = candidate_only + baseline_only
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(candidate_only, baseline_only) + 1))
    return min(1.0, 2 * tail / (2**discordant))


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
                auto_promote INTEGER NOT NULL DEFAULT 0
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(evaluations)")}
        if "auto_promote" not in columns:
            connection.execute("ALTER TABLE evaluations ADD COLUMN auto_promote INTEGER NOT NULL DEFAULT 0")

    def create(
        self,
        task_id: str,
        fine_tune_job_id: str,
        candidate_checkpoint: str,
        minimum_effect: float,
        tasks: TaskStore,
        auto_promote: bool = False,
    ) -> Evaluation:
        task = tasks.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        scenes = tasks.heldout_scenes(task_id)
        if len(scenes) != 30:
            raise ValueError("This task has no predeclared 30-scene evaluation manifest; create a new task.")
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
        )
        rng = random.Random(int(evaluation.id[:16], 16))
        rng.shuffle(scenes)
        candidate_first = [True] * 15 + [False] * 15
        rng.shuffle(candidate_first)
        with self.db.connect() as connection:
            tasks._schema(connection)
            self._schema(connection)
            connection.execute(
                """INSERT INTO evaluations
                   (id, task_id, fine_tune_job_id, baseline_checkpoint, candidate_checkpoint,
                    minimum_effect, created_at, auto_promote) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evaluation.id, task_id, fine_tune_job_id,
                    evaluation.baseline_checkpoint, candidate_checkpoint,
                    minimum_effect, evaluation.created_at, int(auto_promote),
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

    def report(
        self, evaluation: Evaluation, tasks: TaskStore, episodes: EpisodeStore
    ) -> EvaluationReport:
        trials = tasks.list_evaluation_trials(evaluation.id)
        pairs: dict[int, dict[str, Trial]] = {}
        safety = {"base": 0, "candidate": 0}
        for trial in trials:
            if trial.scene_index is None:
                continue
            role = "candidate" if trial.checkpoint == evaluation.candidate_checkpoint else "base"
            pairs.setdefault(trial.scene_index, {})[role] = trial
            if trial.episode_id:
                episode = episodes.get(trial.episode_id)
                if episode is not None and episode.stop_reason == "SafetyStop":
                    safety[role] += 1

        outcomes: list[tuple[bool, bool]] = []
        for pair in pairs.values():
            if "base" not in pair or "candidate" not in pair:
                continue
            base, candidate = pair["base"], pair["candidate"]
            if base.status != "completed" or candidate.status != "completed":
                continue
            left = episodes.get(base.episode_id) if base.episode_id else None
            right = episodes.get(candidate.episode_id) if candidate.episode_id else None
            if (
                left is None or right is None or left.status != "complete" or right.status != "complete"
                or left.simulation is not None or right.simulation is not None
                or left.collection_mode == 'simulation' or right.collection_mode == 'simulation'
                or left.checkpoint != evaluation.baseline_checkpoint or right.checkpoint != evaluation.candidate_checkpoint
                or left.stop_reason == "ModelReady" or right.stop_reason == "ModelReady"
                or left.success is None or right.success is None
            ):
                continue
            outcomes.append((left.success, right.success))

        n = len(outcomes)
        baseline_successes = sum(base for base, _ in outcomes)
        candidate_successes = sum(candidate for _, candidate in outcomes)
        candidate_only = sum(not base and candidate for base, candidate in outcomes)
        baseline_only = sum(base and not candidate for base, candidate in outcomes)
        difference = None
        low = high = p_value = None
        decision: Literal["improved", "inconclusive", "worse"] = "inconclusive"
        reason = f"{n} of 30 held-out setup pairs have usable labels."
        if n:
            changes = [int(candidate) - int(base) for base, candidate in outcomes]
            difference = sum(changes) / n
            low, high = _paired_interval(changes, int(evaluation.id[:16], 16))
            p_value = _exact_mcnemar(candidate_only, baseline_only)
        if n == 30 and difference is not None and low is not None and high is not None and p_value is not None:
            if safety["candidate"] > safety["base"]:
                reason = "Candidate had more safety stops than baseline; review them before switching."
            elif difference >= evaluation.minimum_effect and low > 0 and p_value < 0.05:
                decision = "improved"
                reason = "Observed gain met the practical margin; the interval excludes zero and the paired test passed. The interval need not exclude the practical margin."
            elif difference < 0 and high < 0 and p_value < 0.05:
                decision = "worse"
                reason = "Candidate performed worse on the held-out paired trials."
            else:
                reason = "The measured difference does not clear the predeclared evidence threshold."
        return EvaluationReport(
            evaluation_id=evaluation.id, completeness='complete' if n == 30 else 'incomplete', missing_pairs=30-n,
            target_pairs=30,
            usable_pairs=n,
            baseline_successes=baseline_successes,
            candidate_successes=candidate_successes,
            baseline_only=baseline_only,
            candidate_only=candidate_only,
            paired_difference=difference,
            ci_low=low,
            ci_high=high,
            exact_p_value=p_value,
            baseline_safety_stops=safety["base"],
            candidate_safety_stops=safety["candidate"],
            decision=decision,
            reason=reason,
        )


def scene_for_trial(trial: Trial, tasks: TaskStore) -> HeldoutScene | None:
    if trial.scene_index is None:
        return None
    return next(
        (scene for scene in tasks.heldout_scenes(trial.task_id) if scene.scene_index == trial.scene_index),
        None,
    )
