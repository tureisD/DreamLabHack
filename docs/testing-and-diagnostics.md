# Evaluation testing and diagnostics

From the repository root, use the locked Python 3.12 environment:

```sh
uv sync --locked --extra eval --group dev
uv run --locked --extra eval ruff check .
uv run --locked --extra eval ruff format --check .
uv run --locked --extra eval pytest
uv build
uv run --locked --extra eval python tests/evaluation/wheel_smoke.py
```

Use `uv run --locked --extra eval pytest -m 'not statistical'` for deterministic
checks and `uv run --locked --extra eval pytest -m statistical` for the seeded
operating-characteristics gate. Linux CI runs the full CLI publication tests.
Windows CI runs the portable suite and verifies that publication fails closed.
The fresh-wheel smoke installs into a new environment and a `--target` directory
under an unrelated project, and verifies the shipped lock bytes. The
[validation suite](../tests/evaluation/README.md) lists scenario tests.

## Evaluating one case on Linux

```sh
out=$(mktemp -d)
uv run --locked --extra eval dream-eval evaluate \
  --input tests/fixtures/evaluation_request.json --output-dir "$out/fixture"
cmp "$out/fixture/report.json" tests/evaluation/examples/evaluation_report.json
```

The fixture demonstrates the file round trip with four synthetic attempts. The
new directory keeps the submitted bytes, canonical request, report, summary
and manifest. Compare the input hashes, ordered IDs and raw counts to verify
correspondence. Changing labels or trial order requires a new directory.

The [standalone workflow](evaluation-workflow.md) documents the exact exit codes
and `diagnostics.json` fields. `not_evaluable` is a valid report with exit `0`.
On execution failure, look for `diagnostics.json` and the input snapshots. For a
collision or publication failure, inspect stderr. Existing bundles are preserved.
Reproduce with the captured request and effective settings, identify the failing
boundary, and add an independent reference or regression test before rerunning.
Keep the original failure and its artifacts for comparison.

## Seeded software validation

```sh
out=$(mktemp -d)
uv run --locked --extra eval python tests/evaluation/operating_characteristics.py > "$out/operating-characteristics.json"
```

This validation study runs a prescribed synthetic grid with finite-law references,
fixed seeds, replication counts, tolerances and public evaluator parity. It reports
coverage, false directional findings, power and sequential sample use. The
single-request CLI evaluates a supplied experiment snapshot and does not run the
study or orchestrate experiments. See the [validation protocol and results](../tests/evaluation/VALIDATION.md).

Store study outputs outside tracked source. Keep simulation acceptance criteria
fixed before inspecting results. Investigate unexpected outcomes without editing
trial observations, changing analysis seeds, or relaxing tolerances to obtain a
pass. These software checks require no robot or external service.
