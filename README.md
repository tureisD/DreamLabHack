# DreamLabHack

Teach and evaluate Dream-1 robot tasks with DreamCoach, or audit a frozen statistical comparison with the standalone evaluator.

## DreamCoach extension

This fork also includes [DreamCoach](coach/README.md), an experimental companion for teaching Dream-1 a task. It
guides a user from baseline failures through setup checks, demonstration review, Dream FaaS submission, and paired
evaluation of the resulting checkpoint. Robot motion, paid training, and checkpoint promotion remain under operator
control.

### Measured evaluation repair

We tested one completed apple-pickup fine-tune on fresh YAM simulator scenes without changing its weights or starting
another FaaS job. In eight matched scenes, a nine-request evaluation passed **7/8** and a twelve-request evaluation
passed **8/8**. In a separate, frozen twenty-scene confirmation, **14/19** valid trajectories met the two-second lift
rule by request nine and **19/19** did by request twelve; five first succeeded during request 10 or 11. One attempt
was invalid after a Dream episode restart and remains in the record. See the [protocol, run IDs, and reports](coach/experiments/yam_sim_faas/CLOSED_LOOP_REPAIR_STUDY.md), or open **Coach effect** in the app.

This shows why the coach checks execution and evaluation settings before recommending more demonstrations or another
fine-tune. It is a narrow simulator result. The [operator-study benchmark](coach/benchmark/README.md) is still
prospective; we have **not** measured reductions in operator time, demonstration count, or FaaS spend.

For a key-free demonstration, start with the [offline apple pickup walkthrough](coach/README.md#offline-apple-pickup-walkthrough), which uses scripted fixtures and verified saved video.

## Standalone statistical evaluation

Evaluate whether a candidate robot checkpoint improves task success over a
baseline using a predeclared experiment plan and a complete snapshot of trial
attempts. The evaluator returns reproducible intervals, raw attempt counts and
a decision. It supports fixed-horizon and finite declared-look group-sequential
comparisons for independent, prospective, human-verified, held-out binary
outcomes in one predeclared scenario. The method and its assumptions are
specified in the [numerical guide](src/dreamlab/evaluation/README.md).

### Quick start

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

### Python interface and decisions

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

### Checks and development

```sh
uv run --locked --extra eval ruff check src tests
uv run --locked --extra eval ruff format --check src tests
uv run --locked --extra eval pytest
uv build
uv run --locked --extra eval python tests/evaluation/wheel_smoke.py
```

See the [testing and diagnostics guide](docs/testing-and-diagnostics.md) to
reproduce the synthetic statistical validation and regenerate the example report.
The [documentation index](docs/README.md) links to the versioned contracts,
provenance guidance and branch workflow. The standalone component requires no
robot, database, API credentials or paid training.

### Planned extensions

The [extension plan](docs/extensions/README.md) describes follow-on work for
offline screening, cached replay and evidence-linked run diagnosis. See the
[research audit](docs/extensions/research.md) and
[implementation plan](docs/extensions/implementation-plan.md) for supporting
references and validation requirements.

## Dream Labs client

### What is this library for

`dreamlabs` is the Python client for DreamAPI, which hosts **Dream-1**, the Dream Labs robot model. Dream-1 looks at
your robot's cameras and joint positions, reads the task you type, and answers with the next joint targets for the
arms, zero-shot, with no training on your robot.

It comes two ways:

- **`dreamcli`** runs your robot on our control loop: setup, cameras, arms and Live View, with no code to write.
- **`dream.DreamClient`** calls Dream-1 from your own control loop: you send observations, it returns actions.

### Quick Guide

Sign in at [platform.dreamlabs.ai](https://platform.dreamlabs.ai/api-keys) and create an API key. It is shown only
once, so keep it somewhere safe.

#### dreamcli: our control loop

```bash
pip install dreamlabs
dreamcli setup       # arms and cameras
dreamcli robot up    # start the robot
```

Give it a task from [Live View](https://platform.dreamlabs.ai/live). For the full walkthrough, open
[Robot Setup](https://platform.dreamlabs.ai/setup).

#### DreamClient: your own control loop

```bash
pip install dreamlabs-client
export DREAM_API_KEY=dl_live_...
```

```python
import dream

client = dream.DreamClient()
```

To run a model from your loop, see the [documentation](https://platform.dreamlabs.ai/api-documentation).

### Documentation

The [DreamAPI documentation](https://platform.dreamlabs.ai/api-documentation) covers everything beyond the quick
guide: getting started, calling Dream-1 from your own control loop with `dream.DreamClient`, showing your robot in
Live View, bringing a robot of your own, and fine-tuning Dream-1 on recordings of your robot.

## License

Apache License 2.0 (`LICENSE`). Three of the vendored packages, `i2rt`, `pyroki` and `jaxls` under
`dream_library/vendor/`, keep their own MIT licenses, and the robot models and example assets that came from elsewhere
keep theirs, each in a `LICENSE` file in its own folder.
