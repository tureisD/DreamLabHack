# Independent-trial statistical audit

The **Statistical audit** tab integrates the numerical engine from [`codex/stat-eval-implementation` at `c679621`](https://github.com/tureisD/DreamLabHack/tree/c679621/src/dreamlab/evaluation) into the coach. The imported contracts, fixed-horizon and declared-look methods, eligibility checks, and sample-size planner retain their `dreamlab` package names. The coach exposes them through a local HTTP API and browser screen; it does not import the branch's Linux-only artifact-publishing CLI.

## When to use it

Use it for a predeclared comparison of **independent, prospective, human-verified, held-out binary attempts in one real-world scenario**. Freeze the task instruction, success and reset rules, checkpoint IDs, trial budget, minimum worthwhile improvement, and any interim looks before collecting trials. Record every attempt, including unknown or invalid outcomes. The engine will return `not_evaluable` instead of silently dropping rows or treating an unsupported design as independent data.

The regular **Evaluation** tab remains the coach's matched-scene workflow. It uses paired scene labels and a different paired analysis. The standalone statistical engine **must not** be applied to that paired design or to our apple simulator rollouts; it explicitly rejects both. Its `improved` decision is a statistical statement about the supplied success outcomes under its assumptions, not an instruction to deploy or evidence of safety.

## How to use the new tab

1. In **Plan independent trials**, enter an assumed base success rate, assumed candidate gain, minimum useful gain, and maximum attempts per checkpoint. The planner computes conditional power for the fixed-horizon Newcombe decision and returns the first size meeting 80% power, or says that the budget is insufficient. These are assumptions, not estimates learned from the intended evaluation data. The function is capped at 512 attempts per arm.
2. Prepare a snapshot with `plan` and an ordered `trials` array following the [synthetic JSON example](tests/fixtures/statistical_evaluation_request.json). Each row needs distinct trial and episode IDs, checkpoint, scenario, session, source URI, collection mode, training exposure, outcome, human verification, reviewer, duration, and timestamp. The example is software fixture data, not a robot result.
3. Upload or paste that JSON in **Statistical audit**, then select **Analyze snapshot**. Schema mistakes return a validation error. Supported incomplete or contradictory evidence returns a report marked `not_evaluable` with the raw counts and reasons. An eligible complete snapshot returns effect, interval, decision, method, canonical input checksum, counts, and limits. Download the JSON report for review.

The endpoint is `POST /api/statistical-evaluations/analyze`; planning is `POST /api/statistical-evaluations/plan`. Both calculate locally and make no Dream API, robot, training, or deployment call. The server does not store uploaded snapshots or reports; save the source JSON and downloaded report in your own evaluation record. A JSON file alone does not prove that its assignment, resets, or human labels happened as stated.

## Statistical limits

- Fixed-horizon analysis uses two-sided Wilson intervals for each arm and a Newcombe independent-score interval for candidate minus baseline. A directional improvement requires the interval's lower bound to exceed the frozen minimum improvement. Its finite-sample coverage is approximate and can be poor for tiny samples.
- Group-sequential analysis uses only predeclared, balanced looks and conservative Clopper–Pearson/Bonferroni intervals. It does not authorize repeated unplanned analyses or guarantee fewer trials. The planner covers fixed-horizon comparisons only.
- The engine cannot establish randomization, independence, reset compliance, absence of copied episodes, or reviewer accuracy from IDs and JSON fields. It rejects paired, simulated, deployment, multi-scenario, contaminated, unverified, or incomplete evidence for inference. It does not evaluate safety, intervention burden, cost, or physical robot readiness.

The imported branch passed its 189 non-statistical tests and statistical operating-characteristics test in an isolated checkout on this PC. Its Linux-only CLI publication tests were skipped on Windows. The coach's integration tests cover API parity with the imported engine, rejection of paired and simulated snapshots, duplicate episode IDs, and planning errors.
