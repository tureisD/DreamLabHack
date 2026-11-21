"""Prevent a placeholder evaluator from being mistaken for a working method."""

from pathlib import Path

import pytest

from dreamlab.contracts import EvaluationRequest, EvaluationUnavailable
from dreamlab.evaluation.engine import StatisticalEvaluator


def test_scaffold_cannot_issue_a_statistical_verdict():
    fixture = Path(__file__).parents[1] / "fixtures" / "evaluation_request.json"
    request = EvaluationRequest.model_validate_json(fixture.read_text(encoding="utf-8"))
    with pytest.raises(EvaluationUnavailable, match="not implemented"):
        StatisticalEvaluator().evaluate(request)
