# Workflow services (local owner)

Place task creation, import orchestration, human labeling, frozen evaluation plans,
trial scheduling and evaluation snapshot/export services here. Routes call these
services; services own transactions through repository interfaces.

The local workflow records both checkpoint identity and setup/session/pair IDs,
actual trial order, resets and interventions. Freeze design and trial budget before
the first evaluation run. Request statistical reports through `Evaluator`; do not
calculate confidence intervals or stopping rules in route/UI code.

The first API scaffold calls the pure evaluator synchronously in FastAPI's sync
handler. Move long simulations and bulk evaluation to durable jobs when needed.
Evaluation reports are recommendations, never automatic checkpoint promotion.

No workflow service is implemented yet.
