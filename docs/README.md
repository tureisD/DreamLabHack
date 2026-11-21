# Statistical evaluation documentation

**Active branch:** `codex/stat-eval`. **Integration target:** `main`.
The standalone evaluation component replaces the cancelled local-app workstream.

| Read | Purpose |
| --- | --- |
| [Root assignment](../README.md) | Deliverables, setup and current implementation status |
| [Numerical guide](../src/dreamlab/evaluation/README.md) | Eligibility, interval methods, decisions, sequential error control and pitfalls |
| [Contract v1](contracts.md) | Field meanings, counts, provenance and checksum |
| [Standalone workflow](evaluation-workflow.md) | Engine/runner separation, artifacts and integration |
| [Implementation plan](implementation-plan.md) | Ordered tickets and acceptance criteria |
| [Testing and diagnosis](testing-and-diagnostics.md) | Numerical validation, reproducible failures and targeted repair |
| [Data and evidence](data-and-evidence.md) | Hardware-free development, public dataset limitations and retained research |
| [Branch workflow](branching.md) | Updating teammate checkouts and merging directly into main |
| [Test assignment](../tests/evaluation/README.md) | Numerical and simulation test modules |

## Current state

The contracts, synthetic request fixture, dependency lockfile and CI exist.
`StatisticalEvaluator` still raises `EvaluationUnavailable`. The runner and planned
tests are not implemented. Passing scaffold checks does not validate a method.

Existing evaluation commits and model schema are preserved. The obsolete local API,
app launcher, frontend placeholders, app-only tests and dependencies are removed.
Useful provenance, dataset and diagnosis guidance is adapted for file-based
evaluation. No dashboard, video importer, robot adapter, paid training or database
is required for this assignment.
