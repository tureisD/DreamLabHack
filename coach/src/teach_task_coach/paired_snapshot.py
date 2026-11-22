"""Export the coach's predeclared evaluation trials into auditable paired evidence."""

from __future__ import annotations

import datetime as dt

from teach_task_coach.evaluation import Evaluation
from teach_task_coach.paired_audit import MatchedPair, PairAttempt, PairedRequest, PairPlan
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore, Trial


def _time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def export_paired_snapshot(
    evaluation: Evaluation,
    tasks: TaskStore,
    episodes: EpisodeStore,
    *,
    heldout_attested: bool,
    resets_attested: bool,
) -> PairedRequest:
    """Export observed evidence; attestations must be explicit and are not independently proven."""
    if not heldout_attested or not resets_attested:
        raise ValueError("Confirm both training holdout and scene resets before exporting an audit.")
    task = tasks.get_task(evaluation.task_id)
    if task is None:
        raise ValueError("Evaluation task is missing.")
    trials = tasks.list_evaluation_trials(evaluation.id)
    by_scene: dict[int, dict[str, Trial]] = {}
    for trial in trials:
        if trial.scene_index is None:
            continue
        role = "baseline" if trial.checkpoint == evaluation.baseline_checkpoint else "candidate"
        by_scene.setdefault(trial.scene_index, {})[role] = trial

    def attempt(trial: Trial | None) -> PairAttempt | None:
        if trial is None or trial.episode_id is None:
            return None
        episode = episodes.get(trial.episode_id)
        if episode is None:
            return None
        outcome = (
            "unknown" if trial.status != "completed" or episode.status != "complete"
            or episode.success is None else "success" if episode.success else "failure"
        )
        return PairAttempt(
            trial_id=trial.id,
            episode_id=episode.id,
            checkpoint_id=trial.checkpoint or "",
            source_uri=episode.source_path,
            session_id=f"{trial.station_run}:{trial.station_started_at}" if trial.station_run is not None
            else episode.id,
            recorded_at=_time(episode.started_at_utc),
            outcome=outcome,
            training_exposure="held_out",
            human_verified=bool(episode.reviewer_id),
            reviewer_id=episode.reviewer_id,
            safety_stops=int(episode.stop_reason == "SafetyStop"),
        )

    pairs = tuple(
        MatchedPair(
            pair_id=f"{evaluation.id}:{scene_index}",
            scenario_id=f"scene-{scene_index + 1}",
            baseline=attempt(arms.get("baseline")),
            candidate=attempt(arms.get("candidate")),
        )
        for scene_index, arms in sorted(by_scene.items())
        if any(trial.episode_id for trial in arms.values())
    )
    return PairedRequest(
        plan=PairPlan(
            evaluation_id=evaluation.id,
            task=task.name,
            success_rule=task.success_rule,
            reset_protocol="Operator attested to resetting the marked scene between checkpoint runs.",
            assignment_protocol="Coach-generated 30-scene manifest; balanced shuffled checkpoint order.",
            protocol_ref=f"coach:evaluation:{evaluation.id}",
            baseline_checkpoint=evaluation.baseline_checkpoint,
            candidate_checkpoint=evaluation.candidate_checkpoint,
            collection_mode="prospective",
            planned_pairs=30,
            minimum_improvement=evaluation.minimum_effect,
            created_at=_time(evaluation.created_at),
        ),
        pairs=pairs,
    )
