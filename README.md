# DreamLabHack — standalone statistical evaluation

**Branch:** `codex/stat-eval`
**Merge target:** `main`

Build the statistical engine that answers:

> Did the candidate robot checkpoint improve task success over the baseline,
> and is the evidence strong enough to recommend switching?

This branch is now the primary implementation branch for this component. The local
application has been cancelled; evaluation has no dependency on it. Build a callable
engine and a small file-based runner/report workflow, with statistical tests and
reproducible evidence. No robot, web application, or paid training is required.

Read the [documentation index](docs/README.md) for the standalone architecture,
implementation plan, data limitations, test/diagnosis facility and direct-to-main
integration workflow. The existing numerical assignment below remains in force.

## Current state

The input/output models, dependencies, example input, and test infrastructure exist.
`StatisticalEvaluator.evaluate()` is a stub that raises `EvaluationUnavailable`.
**The statistical engine has not been implemented.** Existing passing scaffold tests
do not demonstrate that any statistical method works.
The standalone runner is also planned, not implemented. The inherited local API,
frontend placeholders and their dependencies have been removed.

## Required deliverables

| Build | Expected behavior |
| --- | --- |
| Input eligibility checks | Check the experiment design, checkpoint identities, trial budget, label verification, held-out status, missing outcomes, and required pairing/session information. |
| Baseline/candidate summaries | Account for every attempt: success, failure, unknown, and invalid. Include sample counts and eligible success rates. |
| Fixed-horizon comparison | Estimate candidate minus baseline success probability, with uncertainty for each rate and for the difference. Implement this first. |
| Verdict logic | Return `improved`, `regressed`, `inconclusive`, or `not_evaluable`, with a plain-language reason. |
| Sequential evaluation | Support early decisions only with a predeclared schedule and valid error control. Reject this mode until implemented and tested. |
| Reproducible reports | Include method/version, input checksum, trial IDs, counts, effect, intervals, warnings, and rationale. |
| Standalone execution | Load a versioned request JSON, call the engine, and save a report plus a reproducibility manifest; keep I/O outside the pure engine. |
| Statistical validation | Add reference-value tests, edge cases, and seeded simulations of coverage, false positives, and power. |

Sample-size/power planning is a follow-on deliverable after the comparison engine
works. Paired and observational designs must be explicitly unsupported until a
suitable method is implemented; never silently analyze them as independent trials.

## Interface to implement

**File:** `src/dreamlab/evaluation/engine.py`

**Method:** `StatisticalEvaluator.evaluate(request: EvaluationRequest) -> EvaluationReport`

Import both types from `dreamlab.contracts`. Read their definitions in
`src/dreamlab/contracts/models.py` and the field semantics in `docs/contracts.md`.

- Input: an immutable experiment plan plus all trial records.
- Output: a JSON-serializable report, reproducible for the same input and configuration.
- Keep the engine independent of databases, web frameworks, robot SDKs, and network calls.
- Return `not_evaluable` for well-formed data that cannot support the requested inference.
- Use null for undefined estimates; never emit NaN, infinity, or invented intervals.

Use `tests/fixtures/evaluation_request.json` to exercise the interface. Its four
synthetic trials are a software example, not evidence of adequate sample size.

## Implementation order and decision policy

1. Validate inputs and produce complete descriptive counts.
2. Implement independent, prospective, human-verified, fixed-horizon comparisons.
   Require the planned attempt budget before a final directional verdict.
3. Add the report and deterministic input checksum.
4. Validate numerical behavior and operating characteristics.
5. Add sequential stopping with explicit error control and tests across all looks.
6. Extend designs or add planning utilities only after their assumptions are documented.

The effect direction is always **candidate minus baseline**, in probability units.
`0.10` means ten percentage points. The proposed decision policy is:

- **Improved:** the difference interval's lower bound exceeds the plan's minimum improvement.
- **Regressed:** its upper bound is below zero.
- **Inconclusive:** a valid completed comparison establishes neither result.
- **Not evaluable:** unsupported design, unsuitable data, or unmet eligibility requirements.

Do not treat inconclusive as equivalence. Do not calculate the difference interval
by checking whether the two individual success-rate intervals overlap.

The [detailed implementation guide](src/dreamlab/evaluation/README.md) specifies
suggested interval methods, a conservative sequential approach, references, and
additional edge cases. Follow it alongside the actual shared contract.

## Files to work in

```text
src/dreamlab/evaluation/
  engine.py                 Public entry point: implement this
  cli.py                    Planned: standalone file-based runner
  methods/                  Validation, intervals, stopping rules, design-specific methods
  reporting/                Deterministic report construction
  README.md                 Detailed implementation guide
tests/evaluation/           Numerical, eligibility, reporting, and simulation tests
```

Coordinate changes to shared contracts, fixtures, dependency declarations, and
`uv.lock`. Keep implementation changes within evaluation-owned paths otherwise.

## Setup, checks, and build

Prerequisites: Git and uv. Python 3.12 is provisioned by uv.

```shell
git clone https://github.com/tureisD/DreamLabHack.git
cd DreamLabHack
git switch --track origin/codex/stat-eval
uv sync --locked --all-extras --group dev
uv run --locked --all-extras pytest tests/contracts tests/evaluation
uv run --locked --all-extras ruff check .
uv run --locked --all-extras ruff format --check .
uv run --locked --all-extras pytest
uv build
```

For an existing checkout use `git switch codex/stat-eval`. No robot, API key,
paid training job, or GPU is needed. Replace `test_handoff.py` with meaningful
engine tests when the stub is implemented; it currently asserts unavailability.

## Traps that must be handled

- A stop reason or an unverified automatic label is not verified task success.
- Unknown/invalid outcomes cannot quietly disappear from the denominator.
- Re-imported footage must not count as additional independent trials.
- Training on evaluation examples contaminates subsequent claims.
- Paired trials, repeated sessions, deployment monitoring, and simulation are
  different designs; do not pool them into an independent real-world comparison.
- Repeatedly checking ordinary 95% intervals is not valid sequential error control.
- Selecting the best checkpoint after many comparisons creates a multiplicity problem.
- Empty samples and all-success/all-failure data need explicit boundary handling.
- Statistical improvement alone does not establish acceptable safety or operating cost.

## What completion means

Submit a working engine, reproducible example report, documented supported modes,
reference tests, and simulation results with seeds, replication counts, and
predeclared tolerances. Test the actual margin-based decision rule and the chance
of any false sequential claim, not just one p-value or the final look.

Open the PR from `codex/stat-eval` directly into **`main`**. State what works,
what remains unsupported, and any contract changes. Keep this evaluator guide and
the documentation under `docs/` when integrating; adapt the main root README to
the broader team's final repository structure. No intermediate app branch exists.
