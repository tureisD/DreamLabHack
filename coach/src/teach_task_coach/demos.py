"""Import completed one-episode LeRobot teleoperation sessions for a task."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pyarrow.parquet as pq
from pydantic import BaseModel

from teach_task_coach.storage import CoachDatabase, default_data_dir


class DemoError(ValueError):
    """A recorder session cannot be interpreted as one demonstration."""


class DemoFinding(BaseModel):
    code: str
    severity: Literal["error", "review"]
    message: str


class Demo(BaseModel):
    id: str
    task_id: str
    source_path: str
    task_text: str
    codebase_version: str
    frames: int
    fps: float
    camera_keys: list[str]
    state_dim: int | None
    action_dim: int | None
    findings: list[DemoFinding]
    decision: Literal["unreviewed", "keep", "redo"] = "unreviewed"
    start_cell: int | None = None
    note: str | None = None

    @property
    def valid(self) -> bool:
        return all(finding.severity != "error" for finding in self.findings)


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoError(f"Could not read {path.name}.") from exc
    if not isinstance(value, dict):
        raise DemoError(f"{path.name} must contain an object.")
    return value


def _task_text(folder: Path, version: str) -> str:
    if version.startswith("v2"):
        path = folder / "meta/tasks.jsonl"
        try:
            first = path.read_text(encoding="utf-8").splitlines()[0]
            value = json.loads(first)["task"]
        except (OSError, UnicodeError, ValueError, IndexError, KeyError, TypeError) as exc:
            raise DemoError("Could not read the v2 task index.") from exc
    else:
        path = folder / "meta/tasks.parquet"
        try:
            value = pq.read_table(path, columns=["task"])["task"][0].as_py()
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise DemoError("Could not read the v3 task index.") from exc
    if not isinstance(value, str) or not value.strip():
        raise DemoError("The demonstration has no task text.")
    return value


def _dim(features: dict[str, Any], key: str) -> int | None:
    feature = features.get(key)
    shape = feature.get("shape") if isinstance(feature, dict) else None
    return shape[0] if isinstance(shape, list) and len(shape) == 1 and isinstance(shape[0], int) else None


def read_demo(folder: Path, task_id: str) -> Demo:
    folder = folder.resolve()
    info = _object(folder / "meta/info.json")
    version = str(info.get("codebase_version", ""))
    if not version.startswith(("v2.1", "v3")):
        raise DemoError("Only LeRobot v2.1 or v3 sessions are supported.")
    if info.get("total_episodes") != 1:
        raise DemoError("Recorder must produce one episode per demonstration folder.")
    task_text = _task_text(folder, version)
    features = info.get("features")
    if not isinstance(features, dict):
        raise DemoError("Dataset metadata has no feature map.")
    cameras = sorted(key for key in features if key.startswith("observation.images."))
    try:
        fps = float(info.get("fps", 0))
        frames = int(info.get("total_frames", 0))
    except (TypeError, ValueError) as exc:
        raise DemoError("Episode frame count or rate is invalid.") from exc
    findings: list[DemoFinding] = []
    if fps <= 0 or frames <= 0:
        findings.append(DemoFinding(code="empty", severity="error", message="Episode has no usable frames or rate."))
    if not cameras:
        findings.append(DemoFinding(code="no_cameras", severity="error", message="No camera feature is recorded."))
    if _dim(features, "observation.state") is None or _dim(features, "action") is None:
        findings.append(DemoFinding(code="missing_vectors", severity="error", message="State or action vector is missing."))
    for key in cameras:
        videos = [path for path in (folder / "videos").rglob("*.mp4") if key in path.parts]
        if not videos:
            findings.append(DemoFinding(code="missing_video", severity="error", message=f"Camera {key} has no video file."))
    parquet_files = sorted((folder / "data").rglob("*.parquet"))
    if not parquet_files:
        findings.append(DemoFinding(code="missing_actions", severity="error", message="No action parquet file is present."))
    elif fps > 0:
        try:
            rows = []
            for path in parquet_files:
                rows.extend(pq.read_table(path, columns=["action"])["action"].to_pylist())
            actions = np.asarray(rows, dtype=float)
            if actions.ndim != 2 or actions.shape[0] != frames:
                findings.append(DemoFinding(code="action_rows", severity="error", message="Action rows do not match metadata."))
            elif actions.shape[0] > 1:
                movement = np.linalg.norm(np.diff(actions, axis=0), axis=1)
                moving = np.flatnonzero(movement > 0.005)
                if len(moving) == 0:
                    findings.append(DemoFinding(code="no_motion", severity="error", message="Actions contain no visible movement."))
                elif moving[0] / fps > 2:
                    findings.append(DemoFinding(code="idle_start", severity="review", message=f"About {moving[0] / fps:.1f} s of idle action at the start."))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            findings.append(DemoFinding(code="unreadable_actions", severity="error", message=f"Could not read actions: {type(exc).__name__}."))

    return Demo(
        id=hashlib.sha256(os.fsencode(folder)).hexdigest()[:20],
        task_id=task_id,
        source_path=str(folder),
        task_text=task_text,
        codebase_version=version,
        frames=frames,
        fps=fps,
        camera_keys=cameras,
        state_dim=_dim(features, "observation.state"),
        action_dim=_dim(features, "action"),
        findings=findings,
    )


class DemoScanner:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root or Path(os.getenv("COACH_DEMOS_DIR", str(default_data_dir() / "demos")))
        ).expanduser()

    def scan(self, task_id: str, prompt: str) -> tuple[list[Demo], list[str]]:
        if not self.root.is_dir():
            return [], [f"Demo directory does not exist: {self.root}"]
        demos: list[Demo] = []
        skipped: list[str] = []
        for folder in sorted(self.root.iterdir(), reverse=True):
            if not folder.is_dir() or not (folder / "meta/info.json").is_file():
                continue
            if not folder.resolve().is_relative_to(self.root.resolve()):
                skipped.append(f"{folder.name}: path leaves demo directory")
                continue
            try:
                demo = read_demo(folder, task_id)
            except DemoError as exc:
                skipped.append(f"{folder.name}: {exc}")
                continue
            if demo.task_text != prompt:
                skipped.append(f"{folder.name}: task text does not match this task")
                continue
            demos.append(demo)
        return demos, skipped


class DemoStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.db = CoachDatabase(data_dir)

    def _schema(self, connection: Any) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS demos (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id),
                source_path TEXT NOT NULL UNIQUE,
                summary_json TEXT NOT NULL,
                decision TEXT NOT NULL DEFAULT 'unreviewed',
                start_cell INTEGER,
                note TEXT
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS demos_task_id ON demos(task_id)")

    def upsert(self, demo: Demo) -> None:
        with self.db.connect() as connection:
            self._schema(connection)
            existing = connection.execute("SELECT task_id FROM demos WHERE id = ?", (demo.id,)).fetchone()
            if existing is not None and existing["task_id"] != demo.task_id:
                raise DemoError("Demo folder is already assigned to another task.")
            connection.execute(
                """INSERT INTO demos (id, task_id, source_path, summary_json)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET summary_json=excluded.summary_json""",
                (
                    demo.id,
                    demo.task_id,
                    demo.source_path,
                    demo.model_dump_json(exclude={"decision", "start_cell", "note"}),
                ),
            )

    def list(self, task_id: str) -> list[Demo]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM demos WHERE task_id = ? ORDER BY source_path DESC", (task_id,)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, demo_id: str) -> Demo | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute("SELECT * FROM demos WHERE id = ?", (demo_id,)).fetchone()
        return None if row is None else self._decode(row)

    def decide(self, demo_id: str, decision: str, start_cell: int | None, note: str | None) -> Demo | None:
        with self.db.connect() as connection:
            self._schema(connection)
            cursor = connection.execute(
                "UPDATE demos SET decision = ?, start_cell = ?, note = ? WHERE id = ?",
                (decision, start_cell, note, demo_id),
            )
            changed = cursor.rowcount
        return self.get(demo_id) if changed else None

    @staticmethod
    def _decode(row: Any) -> Demo:
        return Demo.model_validate(
            {
                **json.loads(row["summary_json"]),
                "decision": row["decision"],
                "start_cell": row["start_cell"],
                "note": row["note"],
            }
        )
