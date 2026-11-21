"""Pure evaluation boundary: no local storage or robot-control dependencies."""

from typing import Protocol

from dreamlab.contracts.models import EvaluationReport, EvaluationRequest


class EvaluationUnavailable(RuntimeError):
    """Raised only when an evaluator is absent or not implemented."""


class Evaluator(Protocol):
    """Implement on the statistical branch; call from independent project consumers."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationReport:
        """Compute a reproducible report from an explicit, immutable input snapshot."""
        ...
