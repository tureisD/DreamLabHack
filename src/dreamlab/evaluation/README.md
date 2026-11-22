# Statistical evaluation — implemented v1

This package implements a deterministic, side-effect-free evaluator over the
shared v1 input and report contracts. It assesses whether an observed checkpoint
comparison supports a predeclared statistical statement. It neither operates a
robot nor certifies safety, operational quality or permission to deploy.

The [follow-on extension plan](../../../docs/extensions/README.md) covers offline
screening, cached replay and run diagnosis.

## Supported inference, stated narrowly

V1 supports only **prospective, human-verified, held-out, resolved binary
outcomes for independent attempts in one predeclared scenario**. The task,
reset/success rule, checkpoints, sample budget and confidence policy must be
frozen before the trials. Inference requires exact balanced attempt counts. The
contract's plan seed is provenance, not proof that arms were randomized. The v1
contracts also lack an allocation manifest that could verify assignment.
Consequently, this method reports a difference under an independent-binomial
model; **the interval alone does not establish that the checkpoint caused the
difference**. A causal or promotion claim also needs a defensible, documented
assignment protocol and independently verified collection.

Paired, observational/deployment, simulated, repeated-session/clustered and
multi-scenario comparisons return `not_evaluable`; they are not silently
reinterpreted as independent single-scenario evidence. The transport model
checks membership and unique trial/episode IDs. An application must still ensure
that IDs, source URIs, resets and physical collection records actually describe
the stated observations.

The method answers **task-success difference only**. It does not establish that
interventions, safety stops, duration, wear, energy or operating cost are
acceptable. It does not correct for repeated checkpoint selection, adaptively
chosen tasks, rater bias, unmeasured drift, multiple task endpoints, or
contamination not identified in the input. The input schema lacks the
randomization manifest, reset audit and cluster model needed to validate such
claims. Report warnings and limitations to reviewers; do not present a returned
`improved` decision as a deployment command.

## API and execution

```python
from dreamlab.contracts import EvaluationRequest
from dreamlab.evaluation.engine import StatisticalEvaluator

request = EvaluationRequest.model_validate_json(snapshot_json)
report = StatisticalEvaluator().evaluate(request)
```

`StatisticalEvaluator.evaluate` is a pure calculation over the immutable typed
snapshot. It makes no HTTP, database, filesystem, robot, hardware or network
calls. Pydantic owns structural errors (including duplicate submitted trial or
episode IDs and task/checkpoint/scenario membership); structurally malformed
snapshots fail validation before the method. A valid but unsuitable design or
incomplete evidence gets a JSON-safe `not_evaluable` report with every submitted
raw outcome, ID and a canonical SHA-256. The method never silently drops unknown,
invalid, unverified or contaminated pre-decision attempts. Undefined rates and
intervals are null, not zero or fabricated.

On Linux with a supported filesystem, the installed runner reads one contract
request and publishes a new bundle. Other platforms can call the evaluator above
but do not support CLI publication:

```sh
uv run --locked --extra eval dream-eval evaluate --input tests/fixtures/evaluation_request.json --output-dir example-run
uv run --locked --extra eval python -m dreamlab.evaluation evaluate --input - --output-dir stdin-run < request.json
```

Compare `example-run/report.json` byte for byte against the
[checked-in example](../../../tests/evaluation/examples/evaluation_report.json).
Each run retains the exact submitted bytes, canonical request, report, summary
and reproducibility manifest. Failed runs retain available inputs and diagnostics.
See the [standalone workflow](../../../docs/evaluation-workflow.md) for artifact
and exit-code details. The four fixture attempts are synthetic software data.

## Fixed-horizon calculation

For two independent binomial arms of n attempts each, the point effect is
`candidate_successes/n − baseline_successes/n`, in probability units. Each arm
uses a two-sided Wilson score interval; the difference uses Newcombe's
uncorrected independent-score interval (method 10). Wilson endpoints use the
requested alpha, not a hard-coded 95% level. All arm and difference intervals
carry their actual configured confidence level. Floating-point-collapsed bounds
are widened outward to the adjacent representable values instead of being
reported as zero-width, invalid intervals.

The decision policy is strict:

- **improved:** the candidate-minus-baseline difference interval's lower bound
  is greater than the predeclared `minimum_improvement` margin.
- **regressed:** its upper bound is less than zero (not minus the improvement
  margin).
- **inconclusive:** supported complete data cross neither boundary. This is
  not equivalence or evidence the models are the same.
- **not_evaluable:** unsupported design or unsuitable, incomplete or
  contradictory evidence; no inferential estimate is issued.

An exact fixed budget is required: partial data cannot create a directional
verdict; excess fixed-horizon attempts do not authorize retrospective selection
of a favorable prefix. An interval is not itself an exact test or a universal
coverage guarantee. Wilson/Newcombe is an approximate finite-sample procedure
and can under-cover at tiny n: exact enumeration of all equally likely arm
outcomes for n=2, true p=.5 in both arms gives **12.5% false directional
claims** and only **87.5% difference-interval coverage**. A tiny or otherwise
underpowered budget is not made safe by a successful function call. Select and
audit sample size and error performance for the actual use case before relying
on the decision.

## Finite-look sequential method

Group-sequential input is supported only when it specifies a strictly increasing
finite schedule ending exactly at the planned per-arm budget. At every allowed
look, each arm receives a two-sided Clopper–Pearson interval with per-arm error
`alpha / (2K)` where K is the **total number of predeclared looks**. The effect
interval is `[candidate_lower − baseline_upper,
 candidate_upper − baseline_lower]`. By a Bonferroni/union bound, the two-arm
difference intervals cover at all declared looks together with probability at
least `1 − alpha` under the arm-wise binomial model. This is deliberately
conservative, and the arm intervals themselves are at their smaller allocated
confidence, not at 1-alpha. Sequential output states the allocation and
simultaneous interpretation; it must not be called an ordinary repeated 95%
interval.

The immutable, ordered submitted snapshot is replayed from its beginning. A
look requires exactly that many attempts in **both** arms, in order; skipping a
look or passing it in one arm before catching up in the other invalidates
inference. Between-look data do not trigger an analysis. The first terminal
directional decision is retained, even when valid later rows are present; all
post-stop rows remain in raw totals, ordered IDs and input checksum, while the
reported effect and intervals refer to the first-stop prefix. Chronology is
checked across the *entire submitted snapshot*, including post-stop rows: a
backwards or pre-plan timestamp withholds the snapshot's inference while still
preserving counts, identifiers, checksum and declared-look history. This
history-only replay recovers the first decision from a stored ordered request;
it is not durable cross-process state, and does not prove that acquisition
actually stopped at that point.

## Eligibility, audit and reporting

Before inference the implementation checks each pre-decision attempt's task
membership, scenario, collection mode, training exposure, reviewed binary
outcome, source, session identifier, pair identifier and recorded time. All
inferential labels must be human verified with a reviewer; original label source
alone is not ground truth. Stop reason is not substituted for the frozen task
success rule. Both arms must have matching per-scenario counts at each look; v1
then additionally requires a **single scenario** rather than claiming the pooled
interval covers heterogeneous scenarios. A detected repeated session, source,
pair, non-prospective/simulated observation, contaminated or unknown exposure,
unknown/invalid result, unverified label or unbalanced/unsupported scenario mix
blocks inference instead of removing the row.

Repeated episode IDs and repeated submitted trial IDs are rejected structurally.
The evaluator adds conservative *lexical* reuse checks for source URIs and
session IDs. Bare paths preserve literal filename characters, including `?` and
`#`; equivalent percent-encoded local `file:` URI paths are treated as the same
source. The evaluator does not access the filesystem and cannot detect
symlink/hardlink aliases, copied data at distinct URLs,
wrongly unique session IDs, one recording split into multiple URIs, or
re-identified duplicate physical attempts. A unique source or session token is
not evidence of independence.

The stable report contains contract version, evaluation ID, full submitted
trial-ID sequence, all four raw counts for each arm, allowed estimates, explicit
method and engine version, canonical checksum, effect and interval, declared-look
history, a plain-language rationale and use-limit warnings. Fixed-sample versus
sequential confidence interpretations are distinguished. Trial budget, included
decision-time prefix and terminal replay are stated. Canonical request hashing
follows the shared rule: JSON mode, sorted keys, compact separators,
`allow_nan=False`, UTF-8, SHA-256; submitted trial order remains meaningful.

## Sample-size/power planner

`methods/planning.py` evaluates the **actual Newcombe lower-bound decision** for
independent, equal-arm binomial experiments. `fixed_horizon_power` computes the
probability that the lower bound exceeds the predeclared absolute margin at
supplied true arm probabilities. `plan_fixed_horizon` searches the integer
arm-size sequence against an explicit budget and target power. The assumed
alternative gain must be strictly greater than the practical margin even after
floating-point representation. Its deterministic finite-binomial calculation
is not an asymptotic or Monte Carlo approximation, but is conditional on the
supplied probabilities and no missingness, multiplicity or clustering. It
supports no unequal arms or other designs and caps the budget at 512 per arm to
bound computation. Discrete power need not be monotone: the planner checks each
smaller integer before naming the first one that reaches the target.

Synthetic illustration: baseline .375, assumed candidate gain .25, decision
margin .125 and target power .80 give a first qualifying size of **242 trials
per arm** (484 total), conditional power about **.801253**. At 80/arm the power
is about **.343811**, not .80. This is a worked mathematical example—not a
required sample size, estimate from the project or measured robot result.

## Validation commands and output

From repository root (Python 3.12):

```sh
uv sync --locked --extra eval --group dev
uv run --locked --extra eval pytest -q
uv run --locked --extra eval pytest -q -m statistical tests/evaluation/test_operating_characteristics.py
uv run --locked --extra eval python tests/evaluation/operating_characteristics.py
uv run --locked --extra eval ruff check .
uv run --locked --extra eval ruff format --check .
uv build
uv run --locked --extra eval python tests/evaluation/wheel_smoke.py
```

The deterministic software tests use independent score/Newcombe/finite-binomial
reference values and cover interval boundaries, arm reversal, strict margins,
missing or contaminated evidence, source aliases, chronology, checksums,
sequential first stopping, planner parity and standalone CLI round trips.
Integration tests also exercise diagnostics, report correspondence, destination
collisions and atomic publication.

The seeded operating-characteristics validation is documented in
[`tests/evaluation/VALIDATION.md`](../../../tests/evaluation/VALIDATION.md).
It uses a frozen grid with 50,000 Bernoulli replications per row, independent
finite-law exact references, Monte Carlo standard errors and tolerances fixed
before execution. It reports coverage, false directional decisions, directional
power, any-false-claim probability over all looks and expected sample use. An
integration gate checks the actual public engine on 889 synthetic reports and
count/path/boundary probes. The chosen grid passed. This is evidence against
selected numerical/operating errors, not a proof for every rate, threshold or
real-world design. The sequential approach was intentionally conservative: at
the prespecified modest alternative .375 versus .625 with margin .125, its grid
power was only about **2.14%** and its expected sample was almost the full
120/arm. Power and cost must be assessed before use; stopping early is not a
guaranteed efficiency gain.

## Ownership and unsupported scope

Owned code is confined to `src/dreamlab/evaluation/`, evaluation-owned tests and
these evaluation-branch documents. The evaluator uses shared contracts and the
already-declared statistical dependencies; no contract or lockfile change was
needed. Do not import local storage, UI or robot operations. Any expansion to
paired/clustered/multi-scenario/observational evidence, replacement policy,
randomization verification, rater or reset audit, safety composite, noninferiority,
equivalence, selection/multiplicity correction or a different sequential
method requires explicit statistical design, any needed shared-contract change,
independent references and new operating-characteristic validation first.
