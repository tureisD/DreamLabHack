"""Supervised baseline trials using the existing station API and saved rollouts."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from teach_task_coach.episodes import EpisodeSummary, RolloutScanner
from teach_task_coach.station import StationClient, StationRejected
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore, Trial, TrialStateError


class TrialError(ValueError):
    """The requested trial action cannot safely proceed."""


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def _matches(trial: Trial, episode: EpisodeSummary, prompt: str, checkpoint: str) -> bool:
    if episode.collection_mode == "simulation" or episode.simulation is not None or episode.run_number != trial.station_run:
        return False
    if episode.task != prompt or episode.checkpoint != checkpoint:
        return False
    start = _parse_time(trial.station_started_at)
    saved = _parse_time(episode.started_at_utc)
    return start is not None and saved is not None and start - dt.timedelta(seconds=2) <= saved <= start + dt.timedelta(hours=2)


class TrialRunner:
    def __init__(
        self,
        tasks: TaskStore,
        episodes: EpisodeStore,
        station: StationClient,
        scanner: RolloutScanner,
    ) -> None:
        self.tasks = tasks
        self.episodes = episodes
        self.station = station
        self.scanner = scanner

    def start(self, trial_id: str, before_start: Callable[[Trial], None] | None = None) -> Trial:
        trial = self.tasks.get_trial(trial_id)
        if trial is None:
            raise KeyError(trial_id)
        if trial.status != "planned":
            raise TrialError("Only a planned trial can start.")
        active = self.tasks.active_trial()
        if active is not None:
            raise TrialError(f"Finish or sync active trial {active.id} before starting another.")
        task = self.tasks.get_task(trial.task_id)
        assert task is not None
        if trial.evaluation_id is not None:
            if any(
                item.status == "abandoned"
                for item in self.tasks.list_evaluation_trials(trial.evaluation_id)
            ):
                raise TrialError("Evaluation contains an unusable run; plan a fresh comparison.")
            next_trial = self.tasks.next_evaluation_trial(trial.evaluation_id)
            if next_trial is None or next_trial.id != trial.id:
                raise TrialError("Finish the preceding evaluation trial first.")
        if trial.repair_id is not None:
            if any(item.status == "abandoned" for item in self.tasks.list_repair_trials(trial.repair_id)):
                raise TrialError("Repair comparison has an unusable run; plan a fresh comparison.")
            next_trial = self.tasks.next_repair_trial(trial.repair_id)
            if next_trial is None or next_trial.id != trial.id:
                raise TrialError("Finish the preceding repair trial first.")
        checkpoint = trial.checkpoint or task.baseline_checkpoint
        prompt = trial.prompt_override or task.prompt
        if not self.scanner.root.is_dir():
            raise TrialError("Local rollout directory is missing; enable station rollouts first.")
        station_status = self.station.status()
        if station_status["state"] != "idle":
            raise TrialError(f"Station is {station_status['state']}; wait until it is idle.")
        if not station_status.get("arms") or not all(station_status["arms"].values()):
            raise TrialError("A robot arm is unavailable.")
        cameras = station_status.get("cameras") or {}
        if not cameras or any(age is None or age > 2 for age in cameras.values()):
            raise TrialError("A camera has no recent frame.")

        self.tasks.transition(
            trial_id,
            "planned",
            "starting",
            start_requested_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        )
        if before_start is not None:
            try:
                before_start(trial)
            except (OSError, ValueError) as exc:
                # The station Start has not been sent, so the scene can be prepared again.
                self.tasks.transition(trial_id, "starting", "planned", last_error=str(exc))
                raise
        try:
            started = self.station.post(
                "start", {"prompt": prompt, "checkpoint": checkpoint}
            )
        except StationRejected as exc:
            self.tasks.transition(trial_id, "starting", "planned", last_error=str(exc))
            raise TrialError(str(exc)) from exc
        # A timeout may mean Start was accepted. Leave the trial in 'starting' for operator reconciliation.
        if not isinstance(started.get("run"), int) or not started.get("started_at"):
            raise TrialError("Station accepted Start without a run number or start time; inspect station status.")
        return self.tasks.transition(
            trial_id,
            "starting",
            "running",
            station_run=started["run"],
            station_started_at=started["started_at"],
        )

    def stop(self, trial_id: str) -> Trial:
        trial = self.tasks.get_trial(trial_id)
        if trial is None:
            raise KeyError(trial_id)
        if trial.status != "running":
            raise TrialError("Only a running trial can stop.")
        self.station.post("stop")
        return self.tasks.transition(trial_id, "running", "awaiting_rollout")

    def sync(self, trial_id: str) -> Trial:
        trial = self.tasks.get_trial(trial_id)
        if trial is None:
            raise KeyError(trial_id)
        if trial.status not in ("running", "awaiting_rollout"):
            raise TrialError("Trial is not waiting for a rollout.")
        station_status = self.station.status()
        if station_status["state"] in ("starting", "running", "stopping") and station_status.get("run") == trial.station_run:
            raise TrialError("The station run is still active.")
        if trial.status == "running":
            trial = self.tasks.transition(trial_id, "running", "awaiting_rollout")
        task = self.tasks.get_task(trial.task_id)
        assert task is not None
        found, _ = self.scanner.scan()
        matches = [
            episode
            for episode in found
            if _matches(trial, episode, trial.prompt_override or task.prompt,
                        trial.checkpoint or task.baseline_checkpoint)
        ]
        if not matches:
            return trial
        episode = min(
            matches,
            key=lambda item: _parse_time(item.started_at_utc) or dt.datetime.max.replace(tzinfo=dt.UTC),
        )
        self.episodes.upsert(episode)
        if episode.stop_reason == "ModelReady":
            return self.tasks.record_warmup(trial_id, episode.id)
        if episode.status != "complete":
            return self.tasks.transition(
                trial_id, "awaiting_rollout", "awaiting_rollout",
                last_error="Rollout is incomplete; mark this trial unusable before retrying.",
            )
        return self.tasks.transition(
            trial_id, "awaiting_rollout", "awaiting_label", episode_id=episode.id
        )

    def label(
        self, trial_id: str, success: bool, failure_stage: str | None, note: str | None,
        reviewer_id: str | None = None,
        interventions: int = 0,
        first_response_s: float | None = None,
    ) -> Trial:
        try:
            return self.tasks.complete_review(
                trial_id, success, failure_stage, note, reviewer_id, interventions, first_response_s,
            )
        except TrialStateError as exc:
            raise TrialError(str(exc)) from exc

    def abandon(self, trial_id: str, reason: str) -> Trial:
        trial = self.tasks.get_trial(trial_id)
        if trial is None:
            raise KeyError(trial_id)
        if trial.status not in ("awaiting_rollout", "awaiting_label"):
            raise TrialError("Only a stopped trial with no usable rollout can be abandoned.")
        if trial.status == "awaiting_label":
            episode = self.episodes.get(trial.episode_id) if trial.episode_id else None
            if episode is not None and episode.status == "complete":
                raise TrialError("A complete rollout must be labelled.")
        station_status = self.station.status()
        if station_status["state"] in ("starting", "running", "stopping"):
            raise TrialError("Stop the station run before abandoning this trial.")
        return self.tasks.transition(
            trial_id, trial.status, "abandoned", last_error=reason
        )

    def reconcile_start(self, trial_id: str) -> Trial:
        """Recover an ambiguous Start after an API timeout or app restart; never starts twice."""
        trial = self.tasks.get_trial(trial_id)
        if trial is None:
            raise KeyError(trial_id)
        if trial.status != "starting":
            raise TrialStateError("Trial is not awaiting Start reconciliation.")
        status = self.station.status()
        task = self.tasks.get_task(trial.task_id)
        assert task is not None
        if status.get("prompt") != (trial.prompt_override or task.prompt) or status.get("checkpoint") != (trial.checkpoint or task.baseline_checkpoint):
            raise TrialError("Station prompt or checkpoint does not match this trial; inspect it manually.")
        if not isinstance(status.get("run"), int) or not status.get("started_at"):
            raise TrialError("Station has no identifiable run for this trial.")
        requested = _parse_time(trial.start_requested_at)
        started = _parse_time(status["started_at"])
        if requested is None or started is None or started < requested - dt.timedelta(seconds=2):
            raise TrialError("The station's last run predates this trial; inspect it manually.")
        return self.tasks.transition(
            trial_id,
            "starting",
            "running" if status["state"] in ("starting", "running", "stopping") else "awaiting_rollout",
            station_run=status["run"],
            station_started_at=status["started_at"],
        )
