# Follow-on plan: evaluation B1–B6 and run diagnosis C1–C4

Planning date: 21 November 2026. Branch: **`codex/stat-eval-extensions`**.
Parent: **`codex/stat-eval`**. This work starts after the parent evaluator is
implemented and validated. No feature implementation or billed inference is
authorized by this planning document alone.

## Intended product

Three clearly separated outputs: **offline screening**, **real-trial statistical
comparison**, and **evidence-linked run diagnosis**. A small CLI/report/replay view
connects them. No general local app, database, fleet manager, robot controller or
training orchestrator is needed.

| User requirement | Planned implementation | Acceptance |
| --- | --- | --- |
| B1 STEP real-trial verdict | Adapter around pinned TRI implementation, explicit hypotheses/risk and ordered verified outcomes | Matches upstream behavior; no silent method substitution; full-sequence error checks |
| B2 Critical-interval offline error | Gripper-event windows, common 48-row prediction horizon and documented action/time alignment | Frozen windows shared across checkpoints; healthy/edge fixtures; raw-error ablation retained |
| B3 Initiation probe | Cached predictions on frozen rest-pose observations with predeclared movement threshold | Detect synthetic no-motion output; distinguish predicted motion from actual movement |
| B4 Honest interpretation | Screening and training-monitoring signals separate from real-trial verdict; overall and started-run outcomes | No proxy-to-success conversion; no exclusion of non-starts from overall analysis |
| B5 Robustness | Complete model-call cache, frozen configs/seeds, episode/cluster bootstrap, deterministic replay | Cache-only run makes zero calls; identical numerical/decision artifacts on repeat |
| B6 Live replay | Recompute A/B/base screens from cached outputs, replay recorded trials through STEP | Real recomputation, preserved chronology/stop, explicit provenance and missing-data behavior |
| C1 Signal-based diagnosis | Parse relevant Dream sidecars/trace; versioned divergence/oscillation and observed initiation checks | Evidence for every flag; missing telemetry is unknown; task success requires human confirmation |
| C2 Prompt failure groups | Group by task/prompt version; suggest “fix your setup” or “needs data,” with mixed/unknown cases | No unsupported forced cause; counts include unclassified runs |
| C3 Human validation | At least 50 held-out labeled runs, frozen rubric, per-class metrics and adjudication | Publish agreement/confusion/coverage and uncertainty; no fabricated run labels |
| C4 Handoffs | Reviewed training-eligible successful episodes to A2; human-confirmed attempts to B1 | Holdout firewall, provenance, source identity and no automatic training/upload |

## Read next

- [Research audit](research.md): verified papers, changed claims, exact source revisions and integration traps.
- [B specification](statistical-and-offline.md): STEP, metrics, probes, caching, bootstrap and stage replay.
- [C specification](run-diagnosis.md): signal rules, grouping, human validation, A/B handoffs and the FailBench-based rationale for avoiding an automatic vision judge.
- [Implementation and validation plan](implementation-plan.md): dependencies, schema gates, files and test cases.

## Decisions that must remain visible

The published CI-MSE result is evidence for the research direction, not a measured
result for our cheaper gripper-window variant. STEP does not automatically supply
an anytime effect confidence interval. Logged faults are proposed diagnostic labels,
not verified success/failure. Successful evaluation runs must not silently enter
training and contaminate subsequent claims.

No hardware is available for this hackathon. Public/partner logs can support replay
if their provenance is adequate; synthetic fixtures must remain visibly synthetic.
The 50-run human-validation study and a real-trial verdict are pending until the
required real recordings/outcomes are available. Do not present planned work as
completed evidence or a literature score as our score.
