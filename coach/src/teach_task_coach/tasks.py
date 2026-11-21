"""Task definitions and supervised baseline trial records."""

from __future__ import annotations

import datetime as dt
import random
import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from teach_task_coach.storage import CoachDatabase

TrialStatus = Literal[
    "planned", "starting", "running", "awaiting_rollout", "awaiting_label", "completed", "abandoned"
]


class TaskInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=500)
    baseline_checkpoint: str = Field(min_length=1, max_length=200)
    success_rule: str = Field(min_length=1, max_length=1000)


class Task(TaskInput):
    id: str
    created_at: str


class TrialInput(BaseModel):
    start_cell: int = Field(ge=0, le=8)
    setup_note: str | None = Field(default=None, max_length=1000)


class Trial(TrialInput):
    id: str
    task_id: str
    status: TrialStatus
    station_run: int | None
    station_started_at: str | None
    start_requested_at: str | None
    episode_id: str | None
    last_error: str | None
    created_at: str
    checkpoint: str | None = None
    evaluation_id: str | None = None
    scene_index: int | None = None
    sequence_index: int | None = None
    purpose: Literal["baseline", "evaluation", "deployed"] = "baseline"


class HeldoutScene(BaseModel):
    task_id: str
    scene_index: int
    start_cell: int
    x_fraction: float
    y_fraction: float
    angle_deg: int


class TrialStateError(ValueError):
    """A trial transition was refused, usually because its state changed."""


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class TaskStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.db = CoachDatabase(data_dir)

    def _schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                baseline_checkpoint TEXT NOT NULL,
                success_rule TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trials (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id),
                start_cell INTEGER NOT NULL,
                setup_note TEXT,
                status TEXT NOT NULL,
                station_run INTEGER,
                station_started_at TEXT,
                start_requested_at TEXT,
                episode_id TEXT REFERENCES episodes(id),
                last_error TEXT,
                created_at TEXT NOT NULL,
                checkpoint TEXT,
                evaluation_id TEXT,
                scene_index INTEGER,
                sequence_index INTEGER,
                purpose TEXT NOT NULL DEFAULT 'baseline'
            );
            CREATE INDEX IF NOT EXISTS trials_task_id ON trials(task_id);
            CREATE TABLE IF NOT EXISTS heldout_scenes (
                task_id TEXT NOT NULL REFERENCES tasks(id),
                scene_index INTEGER NOT NULL,
                start_cell INTEGER NOT NULL,
                x_fraction REAL NOT NULL,
                y_fraction REAL NOT NULL,
                angle_deg INTEGER NOT NULL,
                PRIMARY KEY(task_id, scene_index)
            );
            CREATE TABLE IF NOT EXISTS trial_warmups (
                trial_id TEXT NOT NULL REFERENCES trials(id),
                episode_id TEXT NOT NULL REFERENCES episodes(id),
                recorded_at TEXT NOT NULL,
                PRIMARY KEY(trial_id, episode_id)
            );
            CREATE TABLE IF NOT EXISTS deployments (
                task_id TEXT PRIMARY KEY REFERENCES tasks(id),
                checkpoint TEXT NOT NULL,
                evaluation_id TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(trials)")}
        for name, sql_type in (
            ("checkpoint", "TEXT"), ("evaluation_id", "TEXT"),
            ("scene_index", "INTEGER"), ("sequence_index", "INTEGER"),
            ("purpose", "TEXT NOT NULL DEFAULT 'baseline'"),
        ):
            if name not in columns:
                connection.execute(f"ALTER TABLE trials ADD COLUMN {name} {sql_type}")

    def create_task(self, value: TaskInput) -> Task:
        task = Task(id=uuid.uuid4().hex, created_at=_utc_now(), **value.model_dump())
        with self.db.connect() as connection:
            self._schema(connection)
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.name,
                    task.prompt,
                    task.baseline_checkpoint,
                    task.success_rule,
                    task.created_at,
                ),
            )
            rng = random.Random(int(task.id[:16], 16))
            for scene_index in range(30):
                cell = scene_index % 9
                column, row = cell % 3, cell // 3
                connection.execute(
                    "INSERT INTO heldout_scenes VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        task.id, scene_index, cell,
                        round((column + 0.2 + rng.random() * 0.6) / 3, 4),
                        round((row + 0.2 + rng.random() * 0.6) / 3, 4),
                        rng.choice((0, 90, 180, 270)),
                    ),
                )
        return task

    def heldout_scenes(self, task_id: str) -> list[HeldoutScene]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM heldout_scenes WHERE task_id = ? ORDER BY scene_index", (task_id,)
            ).fetchall()
        return [HeldoutScene.model_validate(dict(row)) for row in rows]

    def list_tasks(self) -> list[Task]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [Task.model_validate(dict(row)) for row in rows]

    def get_task(self, task_id: str) -> Task | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return None if row is None else Task.model_validate(dict(row))

    def deployed_checkpoint(self, task_id: str) -> str:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute(
                "SELECT checkpoint FROM deployments WHERE task_id = ?", (task_id,)
            ).fetchone()
        return task.baseline_checkpoint if row is None else row["checkpoint"]

    def set_deployment(self, task_id: str, checkpoint: str, evaluation_id: str | None) -> None:
        if self.get_task(task_id) is None:
            raise KeyError(task_id)
        with self.db.connect() as connection:
            self._schema(connection)
            connection.execute(
                """INSERT INTO deployments VALUES (?, ?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET checkpoint=excluded.checkpoint,
                   evaluation_id=excluded.evaluation_id, updated_at=excluded.updated_at""",
                (task_id, checkpoint, evaluation_id, _utc_now()),
            )

    def create_trial(self, task_id: str, value: TrialInput) -> Trial:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        trial = Trial(
            id=uuid.uuid4().hex,
            task_id=task_id,
            status="planned",
            station_run=None,
            station_started_at=None,
            start_requested_at=None,
            episode_id=None,
            last_error=None,
            created_at=_utc_now(),
            checkpoint=task.baseline_checkpoint,
            **value.model_dump(),
        )
        with self.db.connect() as connection:
            self._schema(connection)
            connection.execute(
                """INSERT INTO trials
                   (id, task_id, start_cell, setup_note, status, station_run, station_started_at,
                    start_requested_at, episode_id, last_error, created_at, checkpoint,
                    evaluation_id, scene_index, sequence_index)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trial.id,
                    trial.task_id,
                    trial.start_cell,
                    trial.setup_note,
                    trial.status,
                    trial.station_run,
                    trial.station_started_at,
                    trial.start_requested_at,
                    trial.episode_id,
                    trial.last_error,
                    trial.created_at,
                    trial.checkpoint,
                    None, None, None,
                ),
            )
        return trial

    def create_deployed_trial(self, task_id: str, value: TrialInput) -> Trial:
        trial = self.create_trial(task_id, value)
        checkpoint = self.deployed_checkpoint(task_id)
        with self.db.connect() as connection:
            self._schema(connection)
            connection.execute("UPDATE trials SET checkpoint = ?, purpose = 'deployed' WHERE id = ?", (checkpoint, trial.id))
        result = self.get_trial(trial.id)
        assert result is not None
        return result

    def list_trials(self, task_id: str) -> list[Trial]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM trials WHERE task_id = ? AND purpose = 'baseline' ORDER BY created_at, rowid", (task_id,)
            ).fetchall()
        return [Trial.model_validate(dict(row)) for row in rows]

    def list_deployed_trials(self, task_id: str) -> list[Trial]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM trials WHERE task_id = ? AND purpose = 'deployed' ORDER BY created_at, rowid",
                (task_id,),
            ).fetchall()
        return [Trial.model_validate(dict(row)) for row in rows]

    def list_evaluation_trials(self, evaluation_id: str) -> list[Trial]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM trials WHERE evaluation_id = ? ORDER BY sequence_index", (evaluation_id,)
            ).fetchall()
        return [Trial.model_validate(dict(row)) for row in rows]

    def next_evaluation_trial(self, evaluation_id: str) -> Trial | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute(
                """SELECT * FROM trials WHERE evaluation_id = ?
                   AND status NOT IN ('completed', 'abandoned') ORDER BY sequence_index LIMIT 1""",
                (evaluation_id,),
            ).fetchone()
        return None if row is None else Trial.model_validate(dict(row))

    def get_trial(self, trial_id: str) -> Trial | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)).fetchone()
        return None if row is None else Trial.model_validate(dict(row))

    def warmup_episode_ids(self, trial_id: str) -> list[str]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT episode_id FROM trial_warmups WHERE trial_id = ? ORDER BY recorded_at, rowid",
                (trial_id,),
            ).fetchall()
        return [row["episode_id"] for row in rows]

    def record_warmup(self, trial_id: str, episode_id: str) -> Trial:
        with self.db.connect() as connection:
            self._schema(connection)
            cursor = connection.execute(
                """UPDATE trials SET status = 'planned', station_run = NULL,
                   station_started_at = NULL, start_requested_at = NULL, episode_id = NULL,
                   last_error = 'Model warmed without a task attempt; start this trial again.'
                   WHERE id = ? AND status = 'awaiting_rollout'""",
                (trial_id,),
            )
            if cursor.rowcount != 1:
                raise TrialStateError("Trial is no longer awaiting a rollout.")
            connection.execute(
                "INSERT OR IGNORE INTO trial_warmups VALUES (?, ?, ?)",
                (trial_id, episode_id, _utc_now()),
            )
        result = self.get_trial(trial_id)
        assert result is not None
        return result

    def active_trial(self) -> Trial | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute(
                "SELECT * FROM trials WHERE status IN ('starting', 'running', 'awaiting_rollout') LIMIT 1"
            ).fetchone()
        return None if row is None else Trial.model_validate(dict(row))

    def transition(
        self,
        trial_id: str,
        expected: TrialStatus,
        status: TrialStatus,
        *,
        station_run: int | None = None,
        station_started_at: str | None = None,
        start_requested_at: str | None = None,
        episode_id: str | None = None,
        last_error: str | None = None,
    ) -> Trial:
        with self.db.connect() as connection:
            self._schema(connection)
            cursor = connection.execute(
                """UPDATE trials SET status = ?, station_run = COALESCE(?, station_run),
                   station_started_at = COALESCE(?, station_started_at),
                   start_requested_at = COALESCE(?, start_requested_at),
                   episode_id = COALESCE(?, episode_id), last_error = ?
                   WHERE id = ? AND status = ?""",
                (status, station_run, station_started_at, start_requested_at, episode_id, last_error, trial_id, expected),
            )
            if cursor.rowcount != 1:
                raise TrialStateError(f"Trial must be {expected} for this action.")
        result = self.get_trial(trial_id)
        assert result is not None
        return result
