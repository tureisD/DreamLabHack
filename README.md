# DreamLabHack — standalone statistical evaluation

**Active branch:** `codex/stat-eval` · **Integration target:** `main`

Evaluate whether a candidate robot checkpoint improves task success over a
baseline using a predeclared experiment plan and a complete snapshot of trial
attempts. The evaluator returns reproducible intervals, raw attempt counts and
a decision. It supports fixed-horizon and finite declared-look group-sequential
comparisons for independent, prospective, human-verified, held-out binary
outcomes in one predeclared scenario. The method and its assumptions are
specified in the [numerical guide](src/dreamlab/evaluation/README.md).

## Quick start

Install Git and uv. uv uses Python 3.12 for this project. The artifact-writing
CLI requires Linux and a filesystem with atomic no-replace rename. On other
platforms, use the Python evaluator below; the CLI refuses to publish artifacts.
From the repository root on Linux:

```sh
uv sync --locked --extra eval --group dev
uv run --locked --extra eval dream-eval evaluate \
  --input tests/fixtures/evaluation_request.json --output-dir example-run
```

Choose a new output directory with an existing parent for each invocation. The
same CLI is available as `python -m dreamlab.evaluation evaluate` in the installed
environment. Use `--input -` to read the request from standard input.

`example-run/` contains the exact submitted bytes (`request.raw.json`), canonical
parsed request (`request.json`), validated `report.json`, readable `summary.txt`
and reproducibility `manifest.json`. The four-trial fixture demonstrates the
software interface using synthetic data. A valid report, including
`not_evaluable`, exits `0`. Execution failures return a nonzero status and save
`diagnostics.json` with the available input snapshots where possible. See the
[standalone workflow](docs/evaluation-workflow.md) for exit codes, safe publication
behavior and artifact details.

## Python interface and decisions

```python
from dreamlab.contracts import EvaluationRequest
from dreamlab.evaluation.engine import StatisticalEvaluator

request = EvaluationRequest.model_validate_json(snapshot_bytes)
report = StatisticalEvaluator().evaluate(request)
```

The effect is candidate minus baseline in probability units. `0.10` represents
ten percentage points. An `improved` verdict requires the difference interval's
lower bound to exceed the plan's practical margin. A `regressed` verdict requires
its upper bound to be below zero. `inconclusive` indicates a supported comparison
that crosses neither boundary. `not_evaluable` indicates unsupported design or
unsuitable evidence. Paired, clustered, observational, simulated and multi-scenario
comparisons are unsupported. V1 cannot determine assignment or reset validity from
identifiers alone. Review the assumptions and warnings before interpreting any result.

## Checks and development

```sh
uv run --locked --extra eval ruff check .
uv run --locked --extra eval ruff format --check .
uv run --locked --extra eval pytest
uv build
uv run --locked --extra eval python tests/evaluation/wheel_smoke.py
```

See the [testing and diagnostics guide](docs/testing-and-diagnostics.md) to
reproduce the synthetic statistical validation and regenerate the example report.
The [documentation index](docs/README.md) links to the versioned contracts,
provenance guidance and branch workflow. The standalone component requires no
robot, database, API credentials or paid training.
