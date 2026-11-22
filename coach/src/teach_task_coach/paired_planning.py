"""Conservative fixed-horizon planning for independent matched pair differences."""

import math

from pydantic import BaseModel, Field


class PairedPlanInput(BaseModel):
    expected_gain: float = Field(gt=0, le=1, allow_inf_nan=False)
    minimum_improvement: float = Field(ge=0, lt=1, allow_inf_nan=False)
    max_pairs: int = Field(default=512, ge=1, le=512)
    alpha: float = Field(default=0.05, gt=0, lt=1, allow_inf_nan=False)
    minutes_per_pair: float = Field(default=10, gt=0, allow_inf_nan=False)


class PairedPlanEstimate(BaseModel):
    required_pairs: int | None
    feasible: bool
    recommended_pairs: int | None
    estimated_robot_hours: float | None
    explanation: str


def plan_pairs(value: PairedPlanInput) -> PairedPlanEstimate:
    """Find the pair budget whose bound clears the margin if the assumed gain is observed.

    This is a width calculation, not prospective power; it does not account for
    uncertain true effect, scene dependence, setup time variance, or failures.
    """
    gap = value.expected_gain - value.minimum_improvement
    if gap <= 0:
        return PairedPlanEstimate(
            required_pairs=None, feasible=False, recommended_pairs=None,
            estimated_robot_hours=None,
            explanation="Expected gain must exceed the minimum useful improvement.",
        )
    required = math.floor(2 * math.log(2 / value.alpha) / gap**2) + 1
    feasible = required <= value.max_pairs
    return PairedPlanEstimate(
        required_pairs=required, feasible=feasible,
        recommended_pairs=required if feasible else None,
        estimated_robot_hours=(round(required * value.minutes_per_pair / 60, 2)
                               if feasible else None),
        explanation=(
            "Conservative fixed-horizon bound clears the margin only if the observed gain "
            "matches the assumption or is larger. This is not a power guarantee."
        ),
    )
