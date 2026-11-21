# Evaluation testing, diagnosis and repair

This replaces the proposed app testing dashboard with a small reproducible
evaluation validation workflow. It is an implementation specification, not an
already implemented facility. No browser or database is required.

## Checks available now

```shell
uv sync --locked --extra eval --group dev
uv run --locked --extra eval ruff check .
uv run --locked --extra eval ruff format --check .
uv run --locked --extra eval pytest
uv build
```

Today these check structural contracts and explicit engine unavailability only.
When numerical/simulation tests are added, use `pytest -m "not statistical"` for
the fast suite and `pytest -m statistical` for the seeded validation study. CI
still runs the complete suite unless a separately reviewed configuration changes it.

## Planned scenario catalog

| Scenario | Required observation |
| --- | --- |
| Reviewed supported fixed-horizon example | Independent expected rates, intervals and decision; correct input hash |
| Empty/tiny/all-success/all-failure arms | Defined boundary behavior, no NaN/inf or invented precision |
| Practical-margin and zero-bound equality | Strict decision inequalities implemented exactly |
| Swapped baseline/candidate | Correct effect orientation and checkpoint identities |
| Incomplete or over-budget attempts | Explicit eligibility handling; no favorable retrospective subset |
| Unknown/invalid/unverified/contaminated outcomes | Complete raw counts and explicit inference limitations |
| Paired, clustered, observational or simulated data | No silent independent real-world analysis |
| Duplicate attempts or mismatched task/checkpoint | Structural or eligibility rejection at the appropriate boundary |
| Changed label/input order after a saved run | New input hash; old artifacts remain unchanged |
| Wrong provider hash/counts/IDs | Integration rejects mismatched output |
| Unsupported/missing engine | Explicit unavailable/not-evaluable behavior, never a positive fixture report |
| Repeated look and restart | Same first terminal decision under validated sequential replay |
| Output path collision or write failure | No overwritten/half-published report; actionable diagnostics |

For invalid fixtures, the test passes when the expected rejection occurs. Separate
test execution status from the report's scientific decision. `not_evaluable` may
be the correct result; an unrun validation study is never a pass.

## Result artifacts and diagnosis

Each validation run should save scenario/input hash, method/configuration, seed,
expected and observed results, numerical tolerances, package versions, timings
and failure details. Simulation studies additionally record replication counts,
rate/design settings, Monte Carlo uncertainty and acceptance criteria chosen
before results are inspected. Store generated artifacts outside tracked source.

Use stable error categories for malformed input, unsupported design, missing
provenance, incomplete budget, unavailable engine, numerical failure, report
mismatch and output-write failure. Attach the exact field/trial or calculation
involved. Keep unexpected exception details in diagnostic output; do not turn
them into a statistical verdict.

To repair an implementation issue:

1. Reproduce from the saved request, configuration, dependency versions and seed.
2. Identify the first failing boundary: schema -> eligibility -> method -> decision
   -> report -> runner serialization.
3. Add or select an independent reference/edge-case test; fix the code or documented
   configuration. Do not change observations, remove trials, choose a favorable
   seed or relax a tolerance merely to obtain a pass.
4. Rerun the focused test, fast suite and any affected statistical study. Preserve
   the original failure and link it to the new result/artifact directory.

Statistical validation belongs to the actual decision rule, including the practical
margin and probability of any sequential false claim. One passing example, an
ordinary p-value, or the final look alone is insufficient. The detailed method
guide and [test assignment](../tests/evaluation/README.md) define the deeper checks.

## Performance and independence

Target a fast deterministic suite under 30 seconds on the development machine,
then measure and document actual runtime. Larger seeded studies can take longer;
their replication count follows precision requirements, not a desire for a quick
green result. No robot, API account, GPU or 7–8-hour fine-tune is needed for these
tests. They validate software/statistical behavior, not physical robot efficacy.
