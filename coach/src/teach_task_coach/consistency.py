"""Offline action-chunk consistency scoring from saved Dream replies."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel


class ConsistencyScore(BaseModel):
    episode_path: str
    comparisons: int
    score: float | None
    peak: float | None
    warning: str | None


class ConsistencyReview(BaseModel):
    task_id: str
    threshold: float | None
    scored_runs: int
    successful_calibration_runs: int
    alerts: int
    labelled_failures_alerted: int
    labelled_successes_alerted: int
    runs: list[ConsistencyScore]


def score_rollout(folder: Path) -> ConsistencyScore:
    files = sorted((folder / "chunks").glob("reply_*.npz"))
    log = folder / "inference.jsonl"
    if not log.is_file() or not files:
        return ConsistencyScore(
            episode_path=str(folder), comparisons=0, score=None, peak=None,
            warning="No saved replies and inference log to compare.",
        )
    events = [
        record for line in log.read_text(encoding="utf-8").splitlines() if line.strip()
        if (record := json.loads(line)).get("kind") == "inference"
    ]
    if len(events) != len(files):
        return ConsistencyScore(
            episode_path=str(folder), comparisons=0, score=None, peak=None,
            warning="Reply and inference event counts differ; chunk alignment is ambiguous.",
        )
    previous: np.ndarray | None = None
    differences = []
    for event, path in zip(events, files, strict=True):
        if event.get("discarded"):
            continue
        try:
            with np.load(path, allow_pickle=False) as reply:
                current = np.concatenate(
                    (reply["q_l_chunk"], reply["q_r_chunk"]), axis=1
                ).astype(float)
        except (OSError, KeyError, ValueError):
            previous = None
            continue
        if previous is not None:
            offset = event.get("executed_since_obs")
            if isinstance(offset, int) and 0 <= offset < len(previous):
                count = min(len(previous) - offset, len(current))
                if count:
                    delta = previous[offset : offset + count] - current[:count]
                    differences.append(float(np.mean(np.linalg.norm(delta, axis=1))))
        previous = current
    return ConsistencyScore(
        episode_path=str(folder), comparisons=len(differences),
        score=float(sum(differences)) if differences else None,
        peak=max(differences) if differences else None,
        warning=None if differences else "Fewer than two aligned installed replies.",
    )


def calibrate_successes(folders: list[Path]) -> float | None:
    scores = [result.score for folder in folders if (result := score_rollout(folder)).score is not None]
    if len(scores) < 10:
        return None
    return float(np.quantile(scores, 0.95))


def review_task(task_id: str, tasks, episodes) -> ConsistencyReview:
    records = []
    for trial in tasks.list_trials(task_id):
        episode = episodes.get(trial.episode_id) if trial.episode_id else None
        if episode is None:
            continue
        records.append((score_rollout(Path(episode.source_path)), episode.success))
    successful = [score.score for score, success in records if success is True and score.score is not None]
    threshold = float(np.quantile(successful, 0.95)) if len(successful) >= 10 else None
    alerted = [(score, success) for score, success in records if threshold is not None and score.score is not None and score.score > threshold]
    return ConsistencyReview(
        task_id=task_id, threshold=threshold, scored_runs=sum(score.score is not None for score, _ in records),
        successful_calibration_runs=len(successful), alerts=len(alerted),
        labelled_failures_alerted=sum(success is False for _, success in alerted),
        labelled_successes_alerted=sum(success is True for _, success in alerted),
        runs=[score for score, _ in records],
    )
