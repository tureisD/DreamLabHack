"""Entry point for the evaluation teammate; intentionally no inference yet."""

from dreamlab.contracts import EvaluationReport, EvaluationRequest, EvaluationUnavailable


class StatisticalEvaluator:
    """Implement the Evaluator protocol according to this directory's README."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationReport:
        raise EvaluationUnavailable(
            "StatisticalEvaluator is a handoff scaffold; inference is not implemented"
        )
