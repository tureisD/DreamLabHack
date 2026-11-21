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

The evaluator implements fixed-horizon and finite declared-look comparisons.
The standalone CLI publishes input snapshots, a report, a summary and a
reproducibility manifest. The test suite exercises the contract, numerical
methods, seeded operating characteristics and standalone artifact workflow.
