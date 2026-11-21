"""Runnable API boundary; persistence/imports and the evaluator are future work."""

from fastapi import FastAPI, HTTPException

from dreamlab.contracts import EvaluationReport, EvaluationRequest, EvaluationUnavailable, Evaluator


def create_app(evaluator: Evaluator | None = None) -> FastAPI:
    app = FastAPI(title="DreamLab local scaffold", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "stage": "scaffold"}

    @app.get("/api/v1/evaluation/capabilities")
    def capabilities() -> dict[str, bool | int]:
        return {"contract_version": 1, "evaluator_configured": evaluator is not None}

    @app.post("/api/v1/evaluations", response_model=EvaluationReport)
    def evaluate(request: EvaluationRequest) -> EvaluationReport:
        if evaluator is None:
            raise HTTPException(status_code=501, detail="Statistical evaluator is not configured")
        try:
            return evaluator.evaluate(request)
        except EvaluationUnavailable as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

    return app
