"""Conservative run diagnosis from station evidence and operator outcome labels."""

from collections import Counter
from typing import Literal

from pydantic import BaseModel

from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore


class DiagnosedRun(BaseModel):
    trial_id: str
    episode_id: str
    outcome: Literal["success", "failure", "unlabelled"]
    category: Literal["setup", "data", "unknown"]
    reason: str
    evidence: list[str]


class TaskDiagnosis(BaseModel):
    task_id: str
    runs: list[DiagnosedRun]
    setup_count: int
    data_count: int
    unknown_count: int
    failure_stages: dict[str, int]
    recommendation: str


def diagnose(task_id: str, tasks: TaskStore, episodes: EpisodeStore) -> TaskDiagnosis:
    runs = []
    stages: Counter[str] = Counter()
    for trial in tasks.list_trials(task_id):
        if not trial.episode_id:
            continue
        episode = episodes.get(trial.episode_id)
        if episode is None:
            continue
        outcome: Literal["success", "failure", "unlabelled"] = (
            "unlabelled" if episode.success is None else "success" if episode.success else "failure"
        )
        evidence = [f"rollout status: {episode.status}", f"stop reason: {episode.stop_reason or 'none'}"]
        problems = [finding.message for finding in episode.findings if finding.severity == "problem"]
        if episode.status != "complete" or episode.stop_reason in ("SafetyStop", "ModelReady") or problems:
            category: Literal["setup", "data", "unknown"] = "setup"
            reason = "Station or recording issue needs review before this run informs training."
            evidence.extend(problems)
        elif outcome == "failure":
            category = "data"
            reason = "Operator-confirmed failure without a logged station fault; collect targeted examples."
            if episode.failure_stage:
                stages[episode.failure_stage] += 1
                evidence.append(f"human failure stage: {episode.failure_stage}")
        else:
            category = "unknown"
            reason = "No confirmed task failure to explain from logged signals alone."
        if episode.stalls:
            evidence.append(f"control stalls: {episode.stalls}")
        if episode.clamps:
            evidence.append(f"action clamps: {episode.clamps}")
        runs.append(DiagnosedRun(
            trial_id=trial.id, episode_id=episode.id, outcome=outcome,
            category=category, reason=reason, evidence=evidence,
        ))
    setup = sum(run.category == "setup" for run in runs)
    data = sum(run.category == "data" for run in runs)
    unknown = len(runs) - setup - data
    recommendation = (
        "Review station and recording issues first." if setup else
        "Collect demonstrations at confirmed failure positions." if data else
        "Label baseline outcomes before deciding what to collect."
    )
    return TaskDiagnosis(
        task_id=task_id, runs=runs, setup_count=setup, data_count=data,
        unknown_count=unknown, failure_stages=dict(stages), recommendation=recommendation,
    )
