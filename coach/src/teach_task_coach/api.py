"""HTTP API for the local coach UI."""

from fastapi import FastAPI

from teach_task_coach.preflight import PreflightResult, PreflightService


def create_app(service: PreflightService | None = None) -> FastAPI:
    app = FastAPI(title="Teach it a task", version="0.1.0")
    preflight = service or PreflightService()

    @app.get("/api/preflight", response_model=PreflightResult)
    def get_preflight() -> PreflightResult:
        return preflight.run()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
