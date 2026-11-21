"""Exercise the real HTTP boundary without hardware or an inference implementation."""

from pathlib import Path

from fastapi.testclient import TestClient

from dreamlab.contracts import (
    ArmSummary,
    EvaluationReport,
    EvaluationRequest,
    EvaluationUnavailable,
)
from dreamlab.local.api import create_app

FIXTURE = Path(__file__).parents[1] / "fixtures" / "evaluation_request.json"


def request():
    return EvaluationRequest.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_liveness_does_not_claim_hardware_or_evaluator_readiness():
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok", "stage": "scaffold"}
        assert client.get("/api/v1/evaluation/capabilities").json() == {
            "contract_version": 1,
            "evaluator_configured": False,
        }


def test_unconfigured_evaluator_returns_explicit_unavailability():
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/evaluations", json=request().model_dump(mode="json"))
        assert response.status_code == 501
        assert "not configured" in response.json()["detail"]


def test_malformed_request_is_not_forwarded_as_an_experiment():
    with TestClient(create_app()) as client:
        assert client.post("/api/v1/evaluations", json={"trials": []}).status_code == 422


def test_injected_engine_receives_exact_snapshot_and_report_survives_http():
    expected = request()

    class RecordingEvaluator:
        received = None

        def evaluate(self, snapshot):
            self.received = snapshot
            # A protocol test double, explicitly not a statistical implementation.
            return EvaluationReport(
                evaluation_id=snapshot.plan.evaluation_id,
                decision="not_evaluable",
                baseline=ArmSummary(
                    checkpoint_id=snapshot.plan.baseline_checkpoint,
                    attempted=2,
                    successes=1,
                    failures=1,
                    unknown=0,
                    invalid=0,
                ),
                candidate=ArmSummary(
                    checkpoint_id=snapshot.plan.candidate_checkpoint,
                    attempted=2,
                    successes=2,
                    failures=0,
                    unknown=0,
                    invalid=0,
                ),
                method="test-double",
                engine_version="test-only",
                input_sha256="0" * 64,
                trial_ids=tuple(t.trial_id for t in snapshot.trials),
                rationale="Protocol test only; no statistical inference performed.",
            )

    engine = RecordingEvaluator()
    with TestClient(create_app(evaluator=engine)) as client:
        assert client.get("/api/v1/evaluation/capabilities").json()["evaluator_configured"]
        response = client.post("/api/v1/evaluations", json=expected.model_dump(mode="json"))
    assert response.status_code == 200
    assert engine.received == expected
    report = EvaluationReport.model_validate(response.json())
    assert report.decision == "not_evaluable"
    assert report.difference is None
    assert report.trial_ids == tuple(t.trial_id for t in expected.trials)


def test_unimplemented_engine_does_not_produce_fake_results():
    class UnavailableEvaluator:
        def evaluate(self, request):
            raise EvaluationUnavailable("Engine implementation pending")

    with TestClient(create_app(evaluator=UnavailableEvaluator())) as client:
        response = client.post("/api/v1/evaluations", json=request().model_dump(mode="json"))
    assert response.status_code == 501
    assert response.json()["detail"] == "Engine implementation pending"
