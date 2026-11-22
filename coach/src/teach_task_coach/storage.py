"""Small durable local store for imported episodes and operator review labels."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from teach_task_coach.episodes import EpisodeSummary


def default_data_dir() -> Path:
    configured = os.getenv("COACH_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "TeachTaskCoach"
    return Path(os.getenv("XDG_DATA_HOME", "~/.local/share")).expanduser() / "teach-task-coach"


class CoachDatabase:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.db_path = self.data_dir / "coach.sqlite3"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL UNIQUE,
                    summary_json TEXT NOT NULL,
                    success INTEGER,
                    failure_stage TEXT,
                    note TEXT,
                    reviewer_id TEXT,
                    interventions INTEGER NOT NULL DEFAULT 0,
                    first_response_s REAL
                )"""
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(episodes)")}
            if "reviewer_id" not in columns:
                connection.execute("ALTER TABLE episodes ADD COLUMN reviewer_id TEXT")
            if "interventions" not in columns:
                connection.execute("ALTER TABLE episodes ADD COLUMN interventions INTEGER NOT NULL DEFAULT 0")
            if "first_response_s" not in columns:
                connection.execute("ALTER TABLE episodes ADD COLUMN first_response_s REAL")
            yield connection
            connection.commit()
        finally:
            connection.close()


class EpisodeStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.db = CoachDatabase(data_dir)
        self.data_dir = self.db.data_dir

    def upsert(self, episode: EpisodeSummary) -> None:
        payload = episode.model_dump(exclude={
            "success", "failure_stage", "note", "reviewer_id", "interventions", "first_response_s",
        })
        with self.db.connect() as connection:
            connection.execute(
                """INSERT INTO episodes (id, source_path, summary_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET summary_json=excluded.summary_json""",
                (episode.id, episode.source_path, json.dumps(payload)),
            )

    def list(self) -> list[EpisodeSummary]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM episodes ORDER BY json_extract(summary_json, '$.started_at_utc') DESC"
            ).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, episode_id: str) -> EpisodeSummary | None:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        return None if row is None else self._decode(row)

    def label(
        self, episode_id: str, success: bool | None, failure_stage: str | None, note: str | None,
        reviewer_id: str | None = None,
        interventions: int = 0,
        first_response_s: float | None = None,
    ) -> EpisodeSummary | None:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """UPDATE episodes SET success = ?, failure_stage = ?, note = ?, reviewer_id = ?,
                   interventions = ?, first_response_s = ? WHERE id = ?""",
                (None if success is None else int(success), failure_stage, note, reviewer_id,
                 interventions, first_response_s, episode_id),
            )
            changed = cursor.rowcount
        return self.get(episode_id) if changed else None

    @staticmethod
    def _decode(row: sqlite3.Row) -> EpisodeSummary:
        return EpisodeSummary.model_validate(
            {
                **json.loads(row["summary_json"]),
                "success": None if row["success"] is None else bool(row["success"]),
                "failure_stage": row["failure_stage"],
                "note": row["note"],
                "reviewer_id": row["reviewer_id"],
                "interventions": row["interventions"],
                "first_response_s": row["first_response_s"],
            }
        )
