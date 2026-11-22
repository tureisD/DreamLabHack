"""Local-only simulator assignment and task-scoped station finding reviews."""

import datetime as dt
import hashlib
import json
import math
import uuid

from pydantic import BaseModel, Field

from teach_task_coach.episodes import EpisodeSummary
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore, TrialStateError


class SimAssignment(BaseModel):
    episode_id: str = Field(min_length=1)
    start_cell: int = Field(ge=0, le=8, strict=True)


class SimLink(SimAssignment):
    task_id: str
    trial_id: str
    status: str


class FindingReview(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class WorkflowFinding(BaseModel):
    id: str
    episode_id: str
    kind: str
    message: str
    reviewed_at: str | None = None
    reason: str | None = None


def sim_eligible(e: EpisodeSummary) -> bool:
    s = e.simulation or {}
    n = s.get("model_action_rows")
    xy = s.get("apple_xy_m")
    return (
        e.collection_mode == "simulation"
        and e.body == "yam"
        and e.recording_key is not None
        and s.get("source") == "model"
        and e.status == "complete"
        and not e.error
        and e.stop_reason not in ("SafetyStop", "ModelReady")
        and type(n) is int
        and 0 < n <= (e.frames or 0)
        and type(s.get("seed")) is int
        and s["seed"] >= 0
        and s.get("start_pose") in ("home", "wrist-visible")
        and isinstance(xy, list)
        and len(xy) == 2
        and all(type(v) in (int, float) and math.isfinite(v) for v in xy)
    )


def issues(e: EpisodeSummary) -> dict[str, str]:
    result = {f.kind: f.message for f in e.findings if f.severity == "problem"}
    if e.stop_reason == "SafetyStop":
        result.setdefault("safety_stop", "The station reported a safety stop.")
    if e.error:
        result.setdefault("recording_error", "The recording reported an error.")
    if e.status != "complete" or e.stop_reason == "ModelReady":
        result.setdefault(
            "not_a_complete_attempt", "The recording is incomplete or only a warm-up."
        )
    return result


def scoreable(e: EpisodeSummary, trial_status: str) -> bool:
    return (
        trial_status == "completed"
        and e.success is not None
        and not issues(e)
        and (
            sim_eligible(e)
            if e.simulation is not None or e.collection_mode == "simulation"
            else True
        )
    )


def link_episode(tasks: TaskStore, task_id: str, data: SimAssignment) -> SimLink:
    with tasks.db.connect() as conn:
        tasks._schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        row = conn.execute("SELECT * FROM episodes WHERE id=?", (data.episode_id,)).fetchone()
        if task is None or row is None:
            raise KeyError("Task or episode not found.")
        e = EpisodeStore._decode(row)
        if (
            not sim_eligible(e)
            or e.task != task["prompt"]
            or e.checkpoint != task["baseline_checkpoint"]
        ):
            raise TrialStateError(
                "A complete, matching YAM model run with recorded actions and scene provenance is required."
            )
        linked = conn.execute(
            "SELECT t.* FROM sim_baselines b JOIN trials t ON t.id=b.trial_id WHERE b.recording_key=?",
            (e.recording_key,),
        ).fetchone()
        if linked is None:
            linked = conn.execute("SELECT * FROM trials WHERE episode_id=?", (e.id,)).fetchone()
        if linked and (
            linked["task_id"] != task_id
            or linked["start_cell"] != data.start_cell
            or linked["purpose"] != "baseline"
        ):
            raise TrialStateError(
                "Recording is already assigned to another task, purpose, or cell."
            )
        if not linked:
            trial_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO trials(id,task_id,start_cell,status,episode_id,created_at,checkpoint,purpose) VALUES(?,?,?,?,?,?,?,?)",
                (
                    trial_id,
                    task_id,
                    data.start_cell,
                    "completed" if e.success is not None else "awaiting_label",
                    e.id,
                    dt.datetime.now(dt.UTC).isoformat(),
                    e.checkpoint,
                    "baseline",
                ),
            )
        else:
            trial_id = linked["id"]
        conn.execute(
            "INSERT OR IGNORE INTO sim_baselines(recording_key,trial_id) VALUES(?,?)",
            (e.recording_key, trial_id),
        )
        return SimLink.model_validate(
            dict(
                conn.execute(
                    "SELECT id AS trial_id,task_id,episode_id,start_cell,status FROM trials WHERE id=?",
                    (trial_id,),
                ).fetchone()
            )
        )


def assignment(tasks: TaskStore, e: EpisodeSummary) -> SimLink | None:
    with tasks.db.connect() as conn:
        tasks._schema(conn)
        row = conn.execute(
            "SELECT t.id AS trial_id,t.task_id,t.episode_id,t.start_cell,t.status FROM trials t JOIN sim_baselines b ON b.trial_id=t.id WHERE b.recording_key=?",
            (e.recording_key,),
        ).fetchone()
        return SimLink.model_validate(dict(row)) if row else None


def findings(task_id: str, tasks: TaskStore, episodes: EpisodeStore) -> list[WorkflowFinding]:
    found = []
    for t in tasks.list_trials(task_id):
        e = episodes.get(t.episode_id) if t.episode_id else None
        if e is None:
            continue
        for kind, message in issues(e).items():
            identity = hashlib.sha256(json.dumps([task_id, e.id, kind]).encode()).hexdigest()
            found.append((identity, task_id, e.id, kind, message))
    with tasks.db.connect() as conn:
        tasks._schema(conn)
        conn.executemany(
            "INSERT OR IGNORE INTO workflow_findings(id,task_id,episode_id,kind,message) VALUES(?,?,?,?,?)",
            found,
        )
        rows = conn.execute(
            "SELECT * FROM workflow_findings WHERE task_id=? ORDER BY rowid", (task_id,)
        )
        return [WorkflowFinding.model_validate(dict(r)) for r in rows]


def acknowledge(
    task_id: str, key: str, review: FindingReview, tasks: TaskStore, episodes: EpisodeStore
) -> WorkflowFinding:
    reason = review.reason.strip()
    if not reason:
        raise ValueError("A review reason is required.")
    findings(task_id, tasks, episodes)
    with tasks.db.connect() as conn:
        conn.execute(
            "UPDATE workflow_findings SET reviewed_at=?,reason=? WHERE task_id=? AND id=? AND reviewed_at IS NULL",
            (dt.datetime.now(dt.UTC).isoformat(), reason, task_id, key),
        )
        row = conn.execute(
            "SELECT * FROM workflow_findings WHERE task_id=? AND id=?", (task_id, key)
        ).fetchone()
        if row is None:
            raise KeyError("Finding not found for this task.")
        return WorkflowFinding.model_validate(dict(row))
