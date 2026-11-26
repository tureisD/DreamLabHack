"""Import completed one-episode LeRobot teleoperation sessions for a task."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import av
import numpy as np
import pyarrow.parquet as pq
from pydantic import BaseModel

from teach_task_coach.storage import CoachDatabase, default_data_dir


def _content_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.name != "coach-demo.json"):
        if not path.resolve().is_relative_to(folder.resolve()):
            raise DemoError("Demonstration content escapes its session directory.")
        digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


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
    origin: Literal["human", "scripted_reference", "offline_fixture", "unknown"] = "unknown"
    offline_task_id: str | None = None
    source_episode_id: str | None = None
    source_identity: str = ""
    evidence_sha256: str = ""
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


def _camera_review(path: Path, fps: float, frames: int) -> list[DemoFinding]:
    """Flag persistently dark or textureless sampled frames as possible occlusion."""
    try:
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            findings = []
            if stream.average_rate is None or not np.isclose(float(stream.average_rate), fps, rtol=1e-4):
                findings.append(DemoFinding(code="video_fps", severity="error", message=f"{path.parent.name}: video FPS does not match metadata."))
            decoded = 0
            samples = []
            fingerprints = []
            stride = max(1, round(fps))
            for index, frame in enumerate(container.decode(stream)):
                decoded = index + 1
                if decoded > frames:
                    break
                if index >= 300 or index % stride:
                    continue
                gray = frame.to_ndarray(format="gray")
                samples.append((float(np.mean(gray)), float(np.std(gray))))
                fingerprints.append(hashlib.sha256(gray.tobytes()).digest())
    except (OSError, ValueError, av.FFmpegError, IndexError):
        return [DemoFinding(code="video_decode", severity="error", message=f"Could not decode {path.parent.name} video.")]
    if decoded != frames:
        findings.append(DemoFinding(code="video_frames", severity="error", message=f"{path.parent.name}: expected {frames} decodable frames, found {decoded}."))
    if len(samples) >= 3 and sum(mean < 12 or spread < 5 for mean, spread in samples) / len(samples) >= 0.8:
        findings.append(DemoFinding(code="possible_occlusion", severity="review", message=f"{path.parent.name} is dark or nearly textureless in most sampled frames; check camera visibility."))
    if any(len(set(fingerprints[index : index + 4])) == 1 for index in range(max(0, len(fingerprints) - 3))):
        findings.append(DemoFinding(code="frozen_camera", severity="review", message=f"{path.parent.name} repeated the same sampled frame for at least 3 seconds; check the camera feed."))
    return findings


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
    origin: Literal["human", "scripted_reference", "offline_fixture", "unknown"] = "unknown"
    source_episode_id = None
    source_identity = None
    conversion_path = folder / "meta/conversion.json"
    conversion = _object(conversion_path) if conversion_path.is_file() else {}
    marker = conversion.get("origin")
    if marker in ("human", "scripted_reference", "offline_fixture"):
        origin = marker
    scripted_simulator = any(
        path.is_file() and _object(path).get("method") == method
        for path, method in (
            (folder / "click_correction.json", "click_to_correct_simulation"),
            (folder / "scene_task.json", "declarative_scene_task"),
        )
    )
    sidecar = folder / "rollout.json"
    if sidecar.is_file():
        metadata = _object(sidecar)
        simulation = metadata.get("simulation")
        simulation = simulation if isinstance(simulation, dict) else {}
        policy_origin = simulation.get("policy_origin")
        # Offline provenance is absolute: contradictory source labels cannot override it.
        offline_owner = simulation.get("offline_task_id")
        offline_task_id = offline_owner if isinstance(offline_owner, str) else None
        if (
            policy_origin == "offline_fixture"
            or origin == "offline_fixture"
            or (isinstance(offline_owner, str) and policy_origin != "scripted_reference")
        ):
            origin = "offline_fixture"
        elif policy_origin == "human" or (simulation.get("source") == "human" and policy_origin is None):
            origin = "human"
        elif policy_origin == "scripted_reference" or (simulation.get("source") == "scripted" and origin != "offline_fixture"):
            origin = "scripted_reference"
        elif policy_origin is not None:
            origin = "unknown"
        if isinstance(simulation, dict):
            value = simulation.get("source_episode_id")
            if isinstance(value, str) and value:
                source_episode_id = value
            recording_id = metadata.get("recording_id")
            if isinstance(recording_id, str) and recording_id:
                source_identity = f"rollout:{recording_id}"
        if source_identity is None:
            converted_id = conversion.get("source_recording_id")
            if isinstance(converted_id, str) and converted_id:
                source_identity = f"rollout:{converted_id}"
    else:
        # Preserve an explicit conversion provenance marker even when the source
        # rollout sidecar is missing. A copied fixture must never become human by
        # taking the legacy-recorder fallback.
        if origin == "unknown":
            if scripted_simulator:
                origin = "scripted_reference"
            elif not conversion_path.is_file():
                origin = "human"
        receipt_path = folder / "coach-demo.json"
        if receipt_path.is_file():
            receipt = _object(receipt_path)
            candidate = receipt.get("origin")
            if origin != "offline_fixture" and candidate in ("human", "scripted_reference", "offline_fixture"):
                origin = candidate
            source_episode_id = receipt.get("source_episode_id")
            identity = receipt.get("source_identity")
            if isinstance(identity, str) and identity:
                source_identity = identity
    if source_identity is None:
        source_identity = "content:" + _content_hash(folder)
    evidence_sha256 = _content_hash(folder)
    if not np.isfinite(fps) or fps <= 0 or frames <= 0:
        findings.append(DemoFinding(code="empty", severity="error", message="Episode has no usable frames or rate."))
    if not cameras:
        findings.append(DemoFinding(code="no_cameras", severity="error", message="No camera feature is recorded."))
    if _dim(features, "observation.state") is None or _dim(features, "action") is None:
        findings.append(DemoFinding(code="missing_vectors", severity="error", message="State or action vector is missing."))
    for key in cameras:
        videos = [path for path in (folder / "videos").rglob("*.mp4") if key in path.parts]
        if not videos:
            findings.append(DemoFinding(code="missing_video", severity="error", message=f"Camera {key} has no video file."))
        elif len(videos) != 1 or not videos[0].resolve().is_relative_to(folder):
            findings.append(DemoFinding(code="camera_files", severity="error", message=f"Expected one local video for {key}."))
        elif np.isfinite(fps) and fps > 0 and frames > 0:
            findings.extend(_camera_review(videos[0], fps, frames))
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
                if scripted_simulator and actions.shape[1] == 14:
                    # The YAM click teacher holds the unused arm fixed. Its wrist
                    # image can be identical for seconds without a camera fault.
                    for role, arm in (("wrist_r", actions[:, :7]), ("wrist_l", actions[:, 7:])):
                        if np.max(np.abs(np.diff(arm, axis=0))) < 0.001:
                            findings = [finding for finding in findings if not (
                                finding.code == "frozen_camera" and
                                f"observation.images.{role}" in finding.message
                            )]
                movement = np.linalg.norm(np.diff(actions, axis=0), axis=1)
                moving = np.flatnonzero(movement > 0.005)
                stationary_share = float(np.mean(movement <= 0.005))
                if stationary_share > 0.8:
                    findings.append(DemoFinding(code="mostly_stationary", severity="review", message=f"About {stationary_share:.0%} of action intervals are stationary; check whether the episode contains enough task motion."))
                if len(moving) == 0:
                    findings.append(DemoFinding(code="no_motion", severity="error", message="Actions contain no visible movement."))
                elif moving[0] / fps > 2:
                    findings.append(DemoFinding(code="idle_start", severity="review", message=f"About {moving[0] / fps:.1f} s of idle action at the start."))
                if len(movement) > 5:
                    action_feature = features.get("action")
                    names = action_feature.get("names") if isinstance(action_feature, dict) else None
                    if isinstance(names, list) and len(names) == actions.shape[1] and all(isinstance(name, str) for name in names):
                        continuous = [index for index, name in enumerate(names) if "grip" not in name.lower()]
                        motion = np.linalg.norm(np.diff(actions[:, continuous], axis=0), axis=1) if continuous else np.array([])
                    else:
                        motion = movement
                    active = motion[motion > 0.005]
                    typical = float(np.median(active)) if len(active) else 0
                    if typical > 0 and float(np.max(motion)) > 15 * typical:
                        findings.append(DemoFinding(code="abrupt_action", severity="review", message="A commanded action jump is much larger than typical motion; review the video for a jerk."))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            findings.append(DemoFinding(code="unreadable_actions", severity="error", message=f"Could not read actions: {type(exc).__name__}."))

    return Demo(
        id=hashlib.sha256(source_identity.encode("utf-8")).hexdigest()[:20],
        task_id=task_id,
        source_path=str(folder),
        origin=origin,
        offline_task_id=offline_task_id if sidecar.is_file() else None,
        source_episode_id=source_episode_id,
        source_identity=source_identity,
        evidence_sha256=evidence_sha256,
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
            existing = connection.execute("SELECT * FROM demos WHERE id = ?", (demo.id,)).fetchone()
            if existing is None:
                existing = connection.execute("SELECT * FROM demos WHERE source_path = ?", (demo.source_path,)).fetchone()
            identity_match = connection.execute(
                "SELECT id, task_id FROM demos WHERE json_extract(summary_json, '$.source_identity') = ? ORDER BY rowid LIMIT 1",
                (demo.source_identity,),
            ).fetchone()
            if identity_match is not None and (existing is None or identity_match["id"] != existing["id"]):
                if identity_match["task_id"] != demo.task_id:
                    raise DemoError("This recording identity is already assigned to another task.")
                existing = connection.execute("SELECT * FROM demos WHERE id = ?", (identity_match["id"],)).fetchone()
            if existing is not None:
                if existing["task_id"] != demo.task_id:
                    raise DemoError("Demo folder is already assigned to another task.")
                # Re-importing changed bytes in the same session keeps the database
                # row identity, but invalidates the prior Keep and operator note.
                demo.id = existing["id"]
                previous = self._decode(existing)
                # Provenance only becomes more restrictive on re-import. In particular,
                # a missing sidecar must never turn a known fixture into a human demo.
                if previous.origin == "offline_fixture":
                    demo.origin = "offline_fixture"
                if previous.origin == "unknown" and demo.origin == "unknown":
                    demo.origin = "unknown"
                if previous.evidence_sha256 != demo.evidence_sha256 or previous.origin != demo.origin:
                    connection.execute(
                        "UPDATE demos SET summary_json=?, source_path=?, decision='unreviewed', start_cell=NULL, note=NULL WHERE id=?",
                        (demo.model_dump_json(exclude={"decision", "start_cell", "note"}), demo.source_path, demo.id),
                    )
                    return
                connection.execute(
                    "UPDATE demos SET summary_json=? WHERE id=?",
                    (demo.model_dump_json(exclude={"decision", "start_cell", "note"}), demo.id),
                )
                return
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

    def training_eligible(self, task_id: str) -> list[Demo]:
        return [demo for demo in self.list(task_id) if demo.origin in ("human", "scripted_reference") and demo.offline_task_id is None]

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
        summary = json.loads(row["summary_json"])
        if "origin" not in summary:
            # Old indexed sessions need an explicit rescan before they can enter training.
            summary["origin"] = "unknown"
        return Demo.model_validate(
            {
                **summary,
                "decision": row["decision"],
                "start_cell": row["start_cell"],
                "note": row["note"],
            }
        )
