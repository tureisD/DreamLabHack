"""Pure evaluation boundary: no local storage or robot-control dependencies."""

from typing import Protocol

from dreamlab.contracts.models import EvaluationReport, EvaluationRequest


class EvaluationUnavailable(RuntimeError):
    """Raised only when an evaluator is absent or not implemented."""


class Evaluator(Protocol):
    """Implement on the statistical branch; inject into the local application."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationReport:
        """Compute a reproducible report from an explicit, immutable input snapshot."""
        ...
