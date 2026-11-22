"""Read Dream station rollout episodes without changing the source files."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from teach_task_coach.pickup_evidence import PickupEvidence, assess_pickup


class EpisodeError(ValueError):
    """A rollout directory is unreadable or does not follow the station format."""


class Finding(BaseModel):
    kind: str
    severity: str
    message: str
    evidence: str


class InferenceEvent(BaseModel):
    kind: str
    time: str | None
    elapsed_s: float | None
    detail: str | None
    reason: str | None
    action: str | None


class EpisodeSummary(BaseModel):
    id: str
    source_path: str
    status: str
    task: str
    checkpoint: str
    simulation: dict[str, Any] | None = None
    collection_mode: str | None = None
    recording_key: str | None = None
    evidence_sha256: str | None = None
    pickup_evidence: PickupEvidence | None = None
    run_number: int | None = None
    body: str | None
    robot_name: str | None
    started_at_utc: str | None
    frames: int | None
    fps: float | None
    duration_s: float | None
    stop_reason: str | None
    error: str | None
    stalls: int | None
    clamps: int | None
    videos: dict[str, str]
    findings: list[Finding]
    events: list[InferenceEvent]
    review_revision: int = 0
    success: bool | None = None
    failure_stage: str | None = None
    note: str | None = None
    reviewer_id: str | None = None
    interventions: int = 0
    first_response_s: float | None = None


def episode_id(path: Path) -> str:
    return hashlib.sha256(os.fsencode(path.resolve())).hexdigest()[:20]


def recording_key(folder: Path, info: dict) -> str | None:
    if info.get('collection_mode') != 'simulation':
        return None
    uid = info.get('recording_id')
    if isinstance(uid, str) and len(uid) == 32 and all(c in '0123456789abcdef' for c in uid):
        return 'yam:' + uid
    # Legacy pilots have no immutable recording ID. Combine capture time and action bytes,
    # never a folder name or seed. Without either component the run stays review-only.
    if not info.get('started_at_utc'):
        return None
    file = folder / 'data/chunk-000/episode_000000.parquet'
    if not file.is_file() or not file.resolve().is_relative_to(folder):
        return None
    h = hashlib.sha256(json.dumps([info['started_at_utc'], info.get('task'), info.get('checkpoint')]).encode())
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return 'legacy-yam:' + h.hexdigest()


def evidence_hash(folder: Path) -> str:
    """Digest immutable rollout artifacts, excluding the editable operator-review label."""
    folder = folder.resolve()
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if path.name == "operator-review.json":
            continue
        if not path.resolve().is_relative_to(folder):
            raise EpisodeError("Episode evidence leaves its recording directory.")
        digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EpisodeError(f"Could not read {path.name}.") from exc
    if not isinstance(value, dict):
        raise EpisodeError(f"{path.name} must contain a JSON object.")
    return value


def _events(path: Path) -> list[InferenceEvent]:
    if not path.is_file():
        return []
    events: list[InferenceEvent] = []
    started: dt.datetime | None = None
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EpisodeError(f"Invalid inference log at line {line_number}.") from exc
                if not isinstance(record, dict):
                    raise EpisodeError(f"Invalid inference log at line {line_number}.")
                timestamp = record.get("t")
                instant = None
                if isinstance(timestamp, str):
                    try:
                        instant = dt.datetime.fromisoformat(timestamp)
                    except ValueError:
                        pass
                if started is None and instant is not None:
                    started = instant
                elapsed = None
                if instant is not None and started is not None:
                    elapsed = max(0.0, (instant - started).total_seconds())
                events.append(
                    InferenceEvent(
                        kind=str(record.get("kind", "unknown")),
                        time=timestamp if isinstance(timestamp, str) else None,
                        elapsed_s=elapsed,
                        detail=record.get("detail"),
                        reason=record.get("reason"),
                        action=record.get("action"),
                    )
                )
    except (OSError, UnicodeError) as exc:
        raise EpisodeError("Could not read inference.jsonl.") from exc
    return events


def read_episode(folder: Path) -> EpisodeSummary:
    """Parse a finished or partial station episode; a still-recording folder is refused."""
    folder = folder.resolve()
    info = _json_object(folder / "rollout.json")
    status = info.get("status")
    if status not in ("complete", "partial", "empty"):
        raise EpisodeError("The rollout has not finished recording.")
    if not isinstance(info.get("task"), str) or not isinstance(info.get("checkpoint"), str):
        raise EpisodeError("The rollout is missing its task or checkpoint.")

    videos = {
        path.parent.name.removeprefix("observation.images."): str(path)
        for path in sorted((folder / "videos" / "chunk-000").glob("observation.images.*/episode_000000.mp4"))
        if path.is_file() and path.resolve().is_relative_to(folder)
    }
    events = _events(folder / "inference.jsonl")
    findings: list[Finding] = []
    if status == "partial":
        findings.append(
            Finding(kind="partial_recording", severity="warning", message="Recording is partial.", evidence="rollout.json:status")
        )
    if info.get("stop_reason") == "SafetyStop":
        findings.append(
            Finding(kind="safety_stop", severity="problem", message="The station stopped for a safety fault.", evidence="rollout.json:stop_reason")
        )
    if info.get("stalls", 0) and info["stalls"] > 0:
        findings.append(
            Finding(kind="stalls", severity="warning", message=f"The control loop stalled for {info['stalls']} ticks.", evidence="rollout.json:stalls")
        )
    if info.get("clamps", 0) and info["clamps"] > 0:
        findings.append(
            Finding(kind="clamps", severity="info", message=f"Action limits clamped {info['clamps']} ticks.", evidence="rollout.json:clamps")
        )
    for index, event in enumerate(events):
        if event.kind == "error" and event.action == "stop":
            findings.append(
                Finding(kind="inference_error", severity="problem", message=event.detail or "Inference stopped the run.", evidence=f"inference.jsonl:{index + 1}")
            )

    return EpisodeSummary(
        id=episode_id(folder),
        source_path=str(folder),
        status=status,
        task=info["task"],
        checkpoint=info["checkpoint"],
        simulation=info.get("simulation") if isinstance(info.get("simulation"), dict) else None,
        pickup_evidence=assess_pickup(folder, info),
        collection_mode=info.get('collection_mode'),
        recording_key=recording_key(folder, info),
        evidence_sha256=evidence_hash(folder),
        run_number=info.get("run"),
        body=info.get("body"),
        robot_name=info.get("robot_name"),
        started_at_utc=info.get("started_at_utc"),
        frames=info.get("frames"),
        fps=info.get("fps"),
        duration_s=info.get("duration_s"),
        stop_reason=info.get("stop_reason"),
        error=info.get("error"),
        stalls=info.get("stalls"),
        clamps=info.get("clamps"),
        videos=videos,
        findings=findings,
        events=events,
    )


class RolloutScanner:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(os.getenv("COACH_ROLLOUTS_DIR", "~/.dreamlabs/rollouts"))).expanduser()

    def scan(self) -> tuple[list[EpisodeSummary], list[str]]:
        if not self.root.is_dir():
            return [], [f"Rollout directory does not exist: {self.root}"]
        episodes: list[EpisodeSummary] = []
        skipped: list[str] = []
        for folder in sorted(self.root.iterdir(), reverse=True):
            if not folder.is_dir() or not (folder / "rollout.json").exists():
                continue
            if not folder.resolve().is_relative_to(self.root.resolve()):
                skipped.append(f"{folder.name}: rollout path leaves configured directory")
                continue
            try:
                episodes.append(read_episode(folder))
            except EpisodeError as exc:
                skipped.append(f"{folder.name}: {exc}")
        return episodes, skipped
