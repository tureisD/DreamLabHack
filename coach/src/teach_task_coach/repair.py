"""Pre-training matched trials for cheap prompt and setup fixes."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import random
import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from teach_task_coach.paired_snapshot import _source_digest, _time
from teach_task_coach.storage import CoachDatabase, EpisodeStore
from teach_task_coach.tasks import TaskStore, Trial


class RepairRequest(BaseModel):
    kind: Literal["prompt", "setup"]
    candidate_prompt: str | None = Field(default=None, min_length=1, max_length=500)
    setup_change: str | None = Field(default=None, min_length=1, max_length=500)
    planned_pairs: int = Field(default=12, ge=4, le=128)
    minimum_gain: float = Field(default=0.1, ge=0, lt=1, allow_inf_nan=False)
    alpha: float = Field(default=0.05, gt=0, lt=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def correct_variant(self) -> RepairRequest:
        if self.kind == "prompt" and (not self.candidate_prompt or self.setup_change):
            raise ValueError("Prompt studies need only a candidate prompt.")
        if self.kind == "setup" and (not self.setup_change or self.candidate_prompt):
            raise ValueError("Setup studies need only a setup change.")
        return self


class RepairStudy(RepairRequest):
    id: str
    task_id: str
    checkpoint: str
    created_at: str


class RepairAttempt(BaseModel):
    trial_id: str
    episode_id: str
    source_uri: str
    source_sha256: str | None
    session_id: str
    recorded_at: str | None
    outcome: Literal["success", "failure", "unknown", "invalid"]
    reviewer_id: str | None
    safety_stops: int


class RepairPair(BaseModel):
    pair_id: str
    scenario: str
    baseline: RepairAttempt | None
    candidate: RepairAttempt | None


class RepairReport(BaseModel):
    study_id: str
    decision: Literal["use_fix", "consider_faas", "inconclusive", "not_evaluable"]
    planned_pairs: int
    usable_pairs: int
    baseline_successes: int
    candidate_successes: int
    observed_gain: float | None
    difference_interval: tuple[float, float] | None
    baseline_safety_stops: int
    candidate_safety_stops: int
    problems: list[str]
    recommendation: str
    input_sha256: str
    pairs: list[RepairPair]


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="microseconds")


class RepairStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.db = CoachDatabase(data_dir)

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS repair_studies (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                checkpoint TEXT NOT NULL, kind TEXT NOT NULL,
                candidate_prompt TEXT, setup_change TEXT,
                planned_pairs INTEGER NOT NULL, minimum_gain REAL NOT NULL,
                alpha REAL NOT NULL, created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS repair_audits (
                id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES repair_studies(id),
                report_json TEXT NOT NULL, audited_at TEXT NOT NULL
            )"""
        )

    def create(self, task_id: str, value: RepairRequest, tasks: TaskStore) -> RepairStudy:
        task = tasks.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if value.kind == "prompt" and value.candidate_prompt.strip() == task.prompt.strip():
            raise ValueError("Candidate prompt must differ from the task prompt.")
        study = RepairStudy(
            id=uuid.uuid4().hex, task_id=task_id, checkpoint=task.baseline_checkpoint,
            created_at=_now(), **value.model_dump(),
        )
        rng = random.Random(int(study.id[:16], 16))
        first_candidate = [True] * (study.planned_pairs // 2) + [False] * (
            study.planned_pairs - study.planned_pairs // 2
        )
        rng.shuffle(first_candidate)
        with self.db.connect() as connection:
            tasks._schema(connection)
            self._schema(connection)
            connection.execute(
                "INSERT INTO repair_studies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (study.id, task_id, study.checkpoint, study.kind, study.candidate_prompt,
                 study.setup_change, study.planned_pairs, study.minimum_gain, study.alpha,
                 study.created_at),
            )
            sequence = 0
            for index, candidate_first in enumerate(first_candidate):
                cell = index % 9
                column, row = cell % 3, cell // 3
                x = (column + 0.2 + rng.random() * 0.6) / 3
                y = (row + 0.2 + rng.random() * 0.6) / 3
                angle = rng.choice((0, 90, 180, 270))
                scene = f"Diagnostic scene {index + 1}: object at ({x:.3f}, {y:.3f}) of marked table, rotated {angle} degrees."
                roles = ("candidate", "baseline") if candidate_first else ("baseline", "candidate")
                for role in roles:
                    note = scene + (f" Apply setup change: {study.setup_change}" if role == "candidate" and
                                    study.kind == "setup" else " Use original setup.")
                    connection.execute(
                        """INSERT INTO trials
                           (id, task_id, start_cell, setup_note, status, created_at, checkpoint,
                            scene_index, sequence_index, purpose, repair_id, repair_role,
                            prompt_override)
                           VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?, 'repair', ?, ?, ?)""",
                        (uuid.uuid4().hex, task_id, cell, note, study.created_at,
                         study.checkpoint, index, sequence, study.id, role,
                         study.candidate_prompt if role == "candidate" and study.kind == "prompt"
                         else None),
                    )
                    sequence += 1
        return study

    def get(self, study_id: str) -> RepairStudy | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute("SELECT * FROM repair_studies WHERE id = ?", (study_id,)).fetchone()
        return RepairStudy.model_validate(dict(row)) if row else None

    def list(self, task_id: str) -> list[RepairStudy]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM repair_studies WHERE task_id = ? ORDER BY rowid DESC", (task_id,)
            ).fetchall()
        return [RepairStudy.model_validate(dict(row)) for row in rows]

    def _snapshot(
        self, study: RepairStudy, tasks: TaskStore, episodes: EpisodeStore,
    ) -> list[RepairPair]:
        task = tasks.get_task(study.task_id)
        if task is None:
            raise ValueError("Task is missing.")
        grouped: dict[int, dict[str, Trial]] = {}
        for trial in tasks.list_repair_trials(study.id):
            if trial.scene_index is not None and trial.repair_role:
                grouped.setdefault(trial.scene_index, {})[trial.repair_role] = trial

        def attempt(trial: Trial | None) -> RepairAttempt | None:
            if trial is None or not trial.episode_id:
                return None
            episode = episodes.get(trial.episode_id)
            if episode is None:
                return None
            expected_prompt = trial.prompt_override or task.prompt
            outcome: Literal["success", "failure", "unknown", "invalid"] = (
                "unknown" if trial.status != "completed" or episode.success is None
                else "success" if episode.success else "failure"
            )
            if episode.status != "complete" or episode.task != expected_prompt or episode.checkpoint != study.checkpoint:
                outcome = "invalid"
            return RepairAttempt(
                trial_id=trial.id, episode_id=episode.id, source_uri=episode.source_path,
                source_sha256=_source_digest(episode),
                session_id=f"{trial.station_run}:{trial.station_started_at}" if trial.station_run is not None
                else episode.id, recorded_at=episode.started_at_utc, outcome=outcome,
                reviewer_id=episode.reviewer_id, safety_stops=int(episode.stop_reason == "SafetyStop"),
            )

        return [RepairPair(
            pair_id=f"{study.id}:{index}", scenario=f"diagnostic-{index + 1}",
            baseline=attempt(grouped.get(index, {}).get("baseline")),
            candidate=attempt(grouped.get(index, {}).get("candidate")),
        ) for index in range(study.planned_pairs)]

    def analyze(
        self, study: RepairStudy, tasks: TaskStore, episodes: EpisodeStore,
        *, reset_attested: bool,
    ) -> RepairReport:
        pairs = self._snapshot(study, tasks, episodes)
        attempts = [attempt for pair in pairs for attempt in (pair.baseline, pair.candidate)
                    if attempt is not None]
        problems: set[str] = set()
        if not reset_attested:
            problems.add("Scene resets have not been attested.")
        if any(pair.baseline is None or pair.candidate is None for pair in pairs):
            problems.add("The predeclared matched comparison is incomplete.")
        if any(attempt.outcome not in {"success", "failure"} for attempt in attempts):
            problems.add("Unknown or invalid outcomes cannot be omitted.")
        if any(not attempt.reviewer_id for attempt in attempts):
            problems.add("Every outcome needs a named reviewer.")
        if any(attempt.source_sha256 is None for attempt in attempts):
            problems.add("Every attempt needs recorded metadata matching its trial.")
        if any(_time(attempt.recorded_at) is None or
               _time(attempt.recorded_at) <= _time(study.created_at) for attempt in attempts):
            problems.add("Every recorded attempt must follow the frozen plan.")
        if len({attempt.session_id for attempt in attempts}) != len(attempts):
            problems.add("Repeated session IDs may indicate dependent attempts.")
        if len({attempt.source_uri for attempt in attempts}) != len(attempts):
            problems.add("Duplicate rollout sources cannot count twice.")
        usable = [pair for pair in pairs if pair.baseline and pair.candidate and
                  pair.baseline.outcome in {"success", "failure"} and
                  pair.candidate.outcome in {"success", "failure"}]
        baseline = sum(pair.baseline is not None and pair.baseline.outcome == "success" for pair in pairs)
        candidate = sum(pair.candidate is not None and pair.candidate.outcome == "success" for pair in pairs)
        base_stops = sum(attempt.safety_stops for pair in pairs if (attempt := pair.baseline) is not None)
        cand_stops = sum(attempt.safety_stops for pair in pairs if (attempt := pair.candidate) is not None)
        gain = (candidate - baseline) / len(usable) if usable and not problems else None
        interval = None
        decision: Literal["use_fix", "consider_faas", "inconclusive", "not_evaluable"] = "not_evaluable"
        if gain is not None:
            radius = math.sqrt(2 * math.log(2 / study.alpha) / len(usable))
            interval = (max(-1.0, gain - radius), min(1.0, gain + radius))
            if interval[0] > study.minimum_gain and cand_stops <= base_stops:
                decision = "use_fix"
            elif gain <= 0:
                decision = "consider_faas"
            else:
                decision = "inconclusive"
        recommendation = {
            "use_fix": "The cheap change cleared the predeclared gain bound. Keep it; do not pay for FaaS on this evidence alone.",
            "consider_faas": "No gain was observed in this planned comparison. This does not prove the fix cannot help; collect targeted demos if the task still fails.",
            "inconclusive": "The cheap change may help, but evidence is insufficient. Collect more planned trials or inspect the paired failures.",
            "not_evaluable": "Complete and review every planned matched run before deciding whether to train.",
        }[decision]
        payload = json.dumps({"study": study.model_dump(), "pairs": [pair.model_dump() for pair in pairs],
                              "reset_attested": reset_attested}, sort_keys=True, separators=(",", ":"))
        return RepairReport(
            study_id=study.id, decision=decision, planned_pairs=study.planned_pairs,
            usable_pairs=len(usable), baseline_successes=baseline, candidate_successes=candidate,
            observed_gain=gain, difference_interval=interval,
            baseline_safety_stops=base_stops, candidate_safety_stops=cand_stops,
            problems=sorted(problems), recommendation=recommendation,
            input_sha256=hashlib.sha256(payload.encode()).hexdigest(), pairs=pairs,
        )

    def save_audit(
        self, study: RepairStudy, tasks: TaskStore, episodes: EpisodeStore,
        *, reset_attested: bool,
    ) -> RepairReport:
        if not reset_attested:
            raise ValueError("Confirm scene resets before saving the comparison audit.")
        report = self.analyze(study, tasks, episodes, reset_attested=True)
        with self.db.connect() as connection:
            self._schema(connection)
            connection.execute(
                "INSERT INTO repair_audits VALUES (?, ?, ?, ?)",
                (uuid.uuid4().hex, study.id, report.model_dump_json(), _now()),
            )
        return report

    def report(self, study: RepairStudy, tasks: TaskStore, episodes: EpisodeStore) -> RepairReport:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute(
                "SELECT report_json FROM repair_audits WHERE study_id = ? ORDER BY rowid DESC LIMIT 1",
                (study.id,),
            ).fetchone()
        if row is None:
            return self.analyze(study, tasks, episodes, reset_attested=False)
        saved = RepairReport.model_validate_json(row["report_json"])
        current = self.analyze(study, tasks, episodes, reset_attested=True)
        if current.input_sha256 != saved.input_sha256:
            return current.model_copy(update={
                "decision": "not_evaluable", "observed_gain": None,
                "difference_interval": None,
                "problems": [*current.problems, "Evidence changed since the saved audit; audit again."],
                "recommendation": "Audit the changed evidence before using this repair decision.",
            })
        return saved
