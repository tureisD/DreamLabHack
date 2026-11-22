"""Paired checkpoint evidence for real trials and descriptive simulator pilots."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PairPlan(FrozenModel):
    evaluation_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    success_rule: str = Field(min_length=1)
    reset_protocol: str = Field(min_length=1)
    assignment_protocol: str = Field(min_length=1)
    protocol_ref: str | None = None
    baseline_checkpoint: str = Field(min_length=1)
    candidate_checkpoint: str = Field(min_length=1)
    collection_mode: Literal["prospective", "simulation"]
    planned_pairs: int = Field(gt=0)
    minimum_improvement: float = Field(default=0.0, ge=0, lt=1, allow_inf_nan=False)
    alpha: float = Field(default=0.05, gt=0, lt=1, allow_inf_nan=False)
    created_at: AwareDatetime
    required_model_rows: int = Field(default=0, ge=0)
    simulator_hold_threshold_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    heldout_attested: bool = False
    resets_attested: bool = False

    @model_validator(mode="after")
    def distinct_checkpoints(self) -> PairPlan:
        if self.baseline_checkpoint == self.candidate_checkpoint:
            raise ValueError("Base and candidate checkpoints must differ.")
        if self.collection_mode == "simulation" and self.simulator_hold_threshold_m is None:
            raise ValueError("Simulator plans need a held-lift threshold.")
        if self.collection_mode == "simulation" and self.required_model_rows == 0:
            raise ValueError("Simulator plans need a complete model-action row budget.")
        return self


class PairAttempt(FrozenModel):
    trial_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    session_id: str = Field(min_length=1)
    recorded_at: AwareDatetime | None = None
    outcome: Literal["success", "failure", "unknown", "invalid"]
    training_exposure: Literal["held_out", "used_for_training", "unknown"]
    human_verified: bool = False
    reviewer_id: str | None = None
    safety_stops: int = Field(default=0, ge=0)
    interventions: int = Field(default=0, ge=0)
    duration_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    first_response_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    model_action_rows: int | None = Field(default=None, ge=0)
    held_lift_m: float | None = Field(default=None, allow_inf_nan=False)
    peak_lift_m: float | None = Field(default=None, allow_inf_nan=False)
    first_close_after_warmup_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    replay_max_state_error_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    height_source: Literal["recorded", "replayed"] | None = None


class MatchedPair(FrozenModel):
    pair_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    baseline: PairAttempt | None = None
    candidate: PairAttempt | None = None

    @model_validator(mode="after")
    def has_an_attempt(self) -> MatchedPair:
        if self.baseline is None and self.candidate is None:
            raise ValueError("A pair must retain at least one attempted trial.")
        return self


class PairedRequest(FrozenModel):
    plan: PairPlan
    pairs: tuple[MatchedPair, ...]

    @model_validator(mode="after")
    def unique_records(self) -> PairedRequest:
        pair_ids = [pair.pair_id for pair in self.pairs]
        trials = [attempt for pair in self.pairs for attempt in (pair.baseline, pair.candidate)
                  if attempt is not None]
        for name, values in (
            ("pair", pair_ids),
            ("trial", [trial.trial_id for trial in trials]),
            ("episode", [trial.episode_id for trial in trials]),
            ("source", [trial.source_uri for trial in trials]),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"Duplicate {name} ID or source in paired evidence.")
        if any((pair.baseline is not None and pair.baseline.checkpoint_id != self.plan.baseline_checkpoint)
               or (pair.candidate is not None and pair.candidate.checkpoint_id != self.plan.candidate_checkpoint)
               for pair in self.pairs):
            raise ValueError("A pair contains a checkpoint outside its assigned role.")
        return self


class PairedReport(FrozenModel):
    evaluation_id: str
    decision: Literal["descriptive", "improved", "regressed", "inconclusive", "not_evaluable"]
    planned_pairs: int
    submitted_pairs: int
    usable_pairs: int
    baseline_attempted: int
    candidate_attempted: int
    baseline_successes: int
    candidate_successes: int
    baseline_only: int
    candidate_only: int
    baseline_safety_stops: int
    candidate_safety_stops: int
    baseline_interventions: int
    candidate_interventions: int
    baseline_mean_duration_s: float | None
    candidate_mean_duration_s: float | None
    baseline_mean_first_response_s: float | None
    candidate_mean_first_response_s: float | None
    observed_difference: float | None
    difference_interval: tuple[float, float] | None
    interval_method: str | None
    input_sha256: str
    problems: tuple[str, ...]
    warnings: tuple[str, ...]
    pairs: tuple[MatchedPair, ...]


def evaluate_paired(request: PairedRequest) -> PairedReport:
    """Preserve all pairs; issue inference only for eligible complete physical trials."""
    plan = request.plan
    problems: set[str] = set()
    attempts = [trial for pair in request.pairs for trial in (pair.baseline, pair.candidate)
                if trial is not None]
    sessions = [trial.session_id for trial in attempts]
    if len(set(sessions)) != len(sessions):
        problems.add("Repeated session IDs may indicate dependent attempts.")
    if len(request.pairs) != plan.planned_pairs:
        problems.add("Submitted pairs do not match the predeclared pair budget.")
    if any(pair.baseline is None or pair.candidate is None for pair in request.pairs):
        problems.add("A matched scene is missing one checkpoint attempt.")
    if any(trial.recorded_at is None for trial in attempts):
        problems.add("An attempt has no recorded start time.")
    if any(trial.recorded_at is not None and trial.recorded_at <= plan.created_at for trial in attempts):
        problems.add("The plan must precede every recorded attempt.")
    if any(trial.training_exposure != "held_out" for trial in attempts):
        problems.add("Every attempt must be held out from training.")
    if any(trial.outcome not in {"success", "failure"} for trial in attempts):
        problems.add("Unknown or invalid attempts cannot be dropped from the comparison.")
    if plan.collection_mode == "prospective":
        if not plan.heldout_attested or not plan.resets_attested:
            problems.add("Training holdout and scene reset attestations are required.")
        if any(not trial.human_verified or not trial.reviewer_id for trial in attempts):
            problems.add("Physical outcomes need a named human reviewer.")
        if any(trial.source_sha256 is None for trial in attempts):
            problems.add("Physical attempts need a digest of their recorded rollout metadata.")
    else:
        for trial in attempts:
            if (trial.height_source != "recorded" or trial.held_lift_m is None or
                trial.replay_max_state_error_m is None or trial.replay_max_state_error_m >= 0.005 or
                trial.model_action_rows is None or trial.model_action_rows < plan.required_model_rows):
                problems.add("A simulator attempt lacks the required recorded-height or replay evidence.")
                continue
            expected = trial.held_lift_m >= plan.simulator_hold_threshold_m
            if trial.outcome in {"success", "failure"} and (trial.outcome == "success") != expected:
                problems.add("A simulator outcome disagrees with the frozen held-lift rule.")
    usable = [pair for pair in request.pairs if pair.baseline is not None and pair.candidate is not None
              and pair.baseline.outcome in {"success", "failure"}
              and pair.candidate.outcome in {"success", "failure"}]
    baseline = sum(pair.baseline is not None and pair.baseline.outcome == "success"
                   for pair in request.pairs)
    candidate = sum(pair.candidate is not None and pair.candidate.outcome == "success"
                    for pair in request.pairs)
    base_only = sum(pair.baseline.outcome == "success" and pair.candidate.outcome == "failure"
                    for pair in usable)
    candidate_only = sum(pair.candidate.outcome == "success" and pair.baseline.outcome == "failure"
                         for pair in usable)
    difference = (candidate_only - base_only) / len(usable) if usable else None
    interval = None
    method = None
    if problems:
        decision = "not_evaluable"
        difference = None
    elif plan.collection_mode == "simulation":
        decision = "descriptive"
    else:
        # Hoeffding's finite-sample bound applies to independent pair differences
        # in [-1, 1]. It is conservative and does not prove the pairs are independent.
        radius = math.sqrt(2 * math.log(2 / plan.alpha) / len(usable))
        interval = (max(-1.0, difference - radius), min(1.0, difference + radius))
        method = "Two-sided Hoeffding bound for independent paired differences"
        if interval[0] > plan.minimum_improvement:
            candidate_stops = sum(trial.safety_stops for pair in request.pairs
                                  if (trial := pair.candidate) is not None)
            baseline_stops = sum(trial.safety_stops for pair in request.pairs
                                 if (trial := pair.baseline) is not None)
            decision = "inconclusive" if candidate_stops > baseline_stops else "improved"
        elif interval[1] < 0:
            decision = "regressed"
        else:
            decision = "inconclusive"
    payload = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    warnings = (
        "Scene assignment, reset compliance, reviewer accuracy, and pair independence need external audit.",
        "A task-success result alone does not establish physical safety or permission to deploy.",
    )
    if plan.collection_mode == "simulation":
        warnings += ("Simulator results are descriptive and cannot establish real-robot performance.",)
    def mean_metric(role: str, field: str) -> float | None:
        values = [value for pair in request.pairs
                  if (trial := getattr(pair, role)) is not None
                  if (value := getattr(trial, field)) is not None]
        return sum(values) / len(values) if values else None

    return PairedReport(
        evaluation_id=plan.evaluation_id, decision=decision,
        planned_pairs=plan.planned_pairs, submitted_pairs=len(request.pairs), usable_pairs=len(usable),
        baseline_attempted=sum(pair.baseline is not None for pair in request.pairs),
        candidate_attempted=sum(pair.candidate is not None for pair in request.pairs),
        baseline_successes=baseline, candidate_successes=candidate,
        baseline_only=base_only, candidate_only=candidate_only,
        baseline_safety_stops=sum(trial.safety_stops for pair in request.pairs
                                  if (trial := pair.baseline) is not None),
        candidate_safety_stops=sum(trial.safety_stops for pair in request.pairs
                                   if (trial := pair.candidate) is not None),
        baseline_interventions=sum(trial.interventions for pair in request.pairs
                                   if (trial := pair.baseline) is not None),
        candidate_interventions=sum(trial.interventions for pair in request.pairs
                                    if (trial := pair.candidate) is not None),
        baseline_mean_duration_s=mean_metric("baseline", "duration_s"),
        candidate_mean_duration_s=mean_metric("candidate", "duration_s"),
        baseline_mean_first_response_s=mean_metric("baseline", "first_response_s"),
        candidate_mean_first_response_s=mean_metric("candidate", "first_response_s"),
        observed_difference=difference, difference_interval=interval, interval_method=method,
        input_sha256=hashlib.sha256(payload).hexdigest(), problems=tuple(sorted(problems)),
        warnings=warnings, pairs=request.pairs,
    )
