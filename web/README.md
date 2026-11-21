# Local frontend boundary (local owner)

Reserved for the React UI from the team plan. No frontend build or Node dependency
manifest exists yet. The runnable scaffold currently exposes FastAPI `/docs`.

Implement task setup, episode review with synchronized evidence, annotation,
evaluation planning and report display against `/api/v1`. Show unavailable and
inconclusive states explicitly. Preserve all attempts, unknown labels and safety
events. Display probability differences as percentage points.

Use generated OpenAPI types when the UI is scaffolded. Keep statistical decisions
on the backend; the frontend renders the report it receives. Bind development
servers to loopback and use an explicit dev proxy instead of permissive CORS.
