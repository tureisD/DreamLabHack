# Evaluation validation suite

These tests validate the evaluator as statistical software, not robot efficacy.
Use Python 3.12 and the locked environment. From repository root:

```sh
uv sync --locked --extra eval --group dev
uv run --locked --extra eval pytest -q
uv run --locked --extra eval ruff check .
uv run --locked --extra eval ruff format --check .
uv run --locked --extra eval python tests/evaluation/operating_characteristics.py
```

- `interval_reference.py` contains independent score/Newcombe/Clopper-Pearson
  reference equations used by black-box tests.
- `test_eligibility.py` tests unknown/invalid/unverified labels, exposure,
  provenance, duplicate episodes/sources, time order, repeated sessions,
  unsupported designs and scenario eligibility.
- `test_fixed_horizon.py` tests effects, intervals, strict margin boundaries,
  zero/all-success edge cases, arm reversal and the exactly enumerated n=2 limit.
- `test_sequential.py` tests the finite declared-look allocation, missed looks,
  chronological replay, first-stop decisions and immutable post-stop estimates.
- `test_planning.py` compares the fixed-horizon power/planner to exhaustive
  finite binomial enumeration and the same public engine decision rule.
- `test_cli.py` exercises Linux publication with the console command and module
  invocation. It covers byte preservation, invalid requests and reports, closed
  stdin, collisions, write/rename failures, cleanup warnings, and refusal to
  publish a bundle whose directory identity cannot be verified.
- `test_provenance.py` uses real editable and wheel distribution metadata layouts.
  After `uv build`, run `uv run --locked --extra eval python tests/evaluation/wheel_smoke.py`
  for a fresh wheel install, lock-byte verification, a `--target` install inside
  another project's `src/`, and platform CLI behavior (Linux round trip, Windows
  fail-closed).
- `operating_characteristics.py` runs a frozen seeded grid of 50,000 IID
  Bernoulli paths per row and checks finite-law probabilities with Monte Carlo
  tolerances. The default run constructs eligible synthetic requests and checks
  889 public-engine reports across simulated paths and decision boundaries. It
  is a required integration gate, marked `statistical`.
- `reference_operating_characteristics.json` and `VALIDATION.md` contain seeds,
  assumptions, reference probabilities, MC standard errors and predeclared
  tolerances. The stored values are synthetic, not field performance.
- `examples/evaluation_report.json` is the deterministic report from the
  four-attempt synthetic fixture. From the repository root on Linux, regenerate
  into a new artifact directory and compare the resulting `report.json`.

```sh
out=$(mktemp -d)
uv run --locked --extra eval dream-eval evaluate \
  --input tests/fixtures/evaluation_request.json --output-dir "$out/fixture"
cmp "$out/fixture/report.json" tests/evaluation/examples/evaluation_report.json
```

The seeded operating-characteristics command is a software validation study.
The `dream-eval evaluate` command evaluates one submitted request and writes its
bundle. See the [standalone workflow](../../docs/evaluation-workflow.md) for the
artifact and diagnostic schemas.
