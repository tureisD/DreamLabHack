"""Task definitions and supervised baseline trial records."""

from __future__ import annotations

import datetime as dt
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
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS trials_task_id ON trials(task_id);
            """
        )

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
        return task

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

    def create_trial(self, task_id: str, value: TrialInput) -> Trial:
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
            **value.model_dump(),
        )
        with self.db.connect() as connection:
            self._schema(connection)
            if connection.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
                raise KeyError(task_id)
            connection.execute(
                "INSERT INTO trials VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ),
            )
        return trial

    def list_trials(self, task_id: str) -> list[Trial]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM trials WHERE task_id = ? ORDER BY created_at, rowid", (task_id,)
            ).fetchall()
        return [Trial.model_validate(dict(row)) for row in rows]

    def get_trial(self, trial_id: str) -> Trial | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)).fetchone()
        return None if row is None else Trial.model_validate(dict(row))

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
