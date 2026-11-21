"""Transport models, not a statistical validity checker or database schema."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Count = Annotated[int, Field(strict=True, ge=0)]
PositiveCount = Annotated[int, Field(strict=True, gt=0)]
FiniteNonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Outcome = Literal["success", "failure", "unknown", "invalid"]
Decision = Literal["improved", "regressed", "inconclusive", "not_evaluable"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TaskSpec(Record):
    task_id: Identifier
    version: PositiveCount
    instruction: Annotated[str, Field(min_length=1)]
    success_rule: Annotated[str, Field(min_length=1)]
    reset_protocol: Annotated[str, Field(min_length=1)]
    timeout_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class EvaluationPlan(Record):
    schema_version: Literal[1] = 1
    evaluation_id: Identifier
    task: TaskSpec
    baseline_checkpoint: Identifier
    candidate_checkpoint: Identifier
    design: Literal["independent", "paired", "observational"]
    mode: Literal["fixed_horizon", "group_sequential"]
    planned_trials_per_checkpoint: PositiveCount
    scenario_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    alpha: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)] = 0.05
    minimum_improvement: Annotated[float, Field(ge=0, lt=1, allow_inf_nan=False)] = 0.0
    label_policy: Literal["human_verified"] = "human_verified"
    planned_looks: tuple[PositiveCount, ...] = ()
    random_seed: Count
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.baseline_checkpoint == self.candidate_checkpoint:
            raise ValueError("baseline and candidate must be distinct checkpoints")
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("scenario_ids must be unique")
        if self.mode == "fixed_horizon" and self.planned_looks:
            raise ValueError("fixed_horizon has no interim decision looks")
        if self.mode == "group_sequential":
            if (
                not self.planned_looks
                or self.planned_looks[-1] != self.planned_trials_per_checkpoint
            ):
                raise ValueError("sequential looks must end at the planned trial budget")
            if tuple(sorted(set(self.planned_looks))) != self.planned_looks:
                raise ValueError("sequential looks must be strictly increasing")
        return self


class Trial(Record):
    trial_id: Identifier
    episode_id: Identifier
    task_id: Identifier
    task_version: PositiveCount
    checkpoint_id: Identifier
    scenario_id: Identifier
    session_id: Identifier
    pair_id: Identifier | None = None
    collection_mode: Literal["prospective", "deployment", "simulation"]
    training_exposure: Literal["held_out", "used_for_training", "unknown"]
    outcome: Outcome
    label_source: Literal["human", "triage", "vision", "unknown"]
    human_verified: Annotated[bool, Field(strict=True)] = False
    reviewer_id: Identifier | None = None
    exclusion_reason: Annotated[str, Field(min_length=1)] | None = None
    duration_s: FiniteNonnegative
    interventions: Count = 0
    safety_stops: Count = 0
    stop_reason: str | None = None
    source_uri: Annotated[str, Field(min_length=1)]
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.human_verified and not self.reviewer_id:
            raise ValueError("human verification requires reviewer_id")
        if self.outcome == "invalid" and not self.exclusion_reason:
            raise ValueError("invalid trials require an exclusion reason")
        if self.outcome != "invalid" and self.exclusion_reason is not None:
            raise ValueError("only invalid trials may have an exclusion reason")
        return self


class EvaluationRequest(Record):
    plan: EvaluationPlan
    trials: tuple[Trial, ...]

    @model_validator(mode="after")
    def validate_membership(self) -> Self:
        ids = [trial.trial_id for trial in self.trials]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate trial IDs")
        episodes = [trial.episode_id for trial in self.trials]
        if len(set(episodes)) != len(episodes):
            raise ValueError("one recorded episode cannot count as multiple trials")
        checkpoints = {self.plan.baseline_checkpoint, self.plan.candidate_checkpoint}
        for trial in self.trials:
            if (trial.task_id, trial.task_version) != (
                self.plan.task.task_id,
                self.plan.task.version,
            ):
                raise ValueError("trial belongs to a different task version")
            if trial.checkpoint_id not in checkpoints:
                raise ValueError("trial checkpoint does not belong to this comparison")
            if trial.scenario_id not in self.plan.scenario_ids:
                raise ValueError("trial scenario is not in the frozen plan")
        return self


class Interval(Record):
    lower: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
    upper: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
    confidence_level: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.lower > self.upper:
            raise ValueError("interval lower bound exceeds upper bound")
        return self


class ArmSummary(Record):
    checkpoint_id: Identifier
    attempted: Count
    successes: Count
    failures: Count
    unknown: Count
    invalid: Count
    # Null until eligible outcomes and design permit an inferential estimate.
    success_rate: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    success_interval: Interval | None = None

    @model_validator(mode="after")
    def complete_counts(self) -> Self:
        if self.attempted != self.successes + self.failures + self.unknown + self.invalid:
            raise ValueError("outcome counts must account for every attempted trial")
        if self.success_interval and self.success_interval.lower < 0:
            raise ValueError("success probability intervals cannot be negative")
        return self


class EvaluationReport(Record):
    schema_version: Literal[1] = 1
    evaluation_id: Identifier
    decision: Decision
    baseline: ArmSummary
    candidate: ArmSummary
    # Positive always means candidate minus baseline, in probability units.
    difference: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] | None = None
    difference_interval: Interval | None = None
    method: Annotated[str, Field(min_length=1)]
    engine_version: Identifier
    input_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    trial_ids: tuple[Identifier, ...]
    warnings: tuple[str, ...] = ()
    rationale: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_evidence(self) -> Self:
        if self.decision in {"improved", "regressed"} and (
            self.difference is None or self.difference_interval is None
        ):
            raise ValueError("directional verdicts require an effect estimate and interval")
        return self
