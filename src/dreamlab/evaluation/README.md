# Statistical evaluation — teammate implementation assignment

On `codex/stat-eval-extensions`, this is the inherited **parent prerequisite**.
The follow-on B/C assignment is in `docs/extensions/README.md`; do not duplicate
the parent's engine implementation or change its methods during this planning step.

**Working branch:** `codex/stat-eval`
**Merge target:** `main`, directly
**Scope:** standalone statistical engine, file-based runner, reports and validation
**Your ownership:** this evaluation package, `tests/evaluation/`, and evaluation documentation; coordinate shared-contract changes with project consumers

This branch is an implementation handoff. `StatisticalEvaluator.evaluate()` is
currently a deliberate unavailable stub. There is **no working statistical engine**
yet. Start with the branch-root README for the deliverables and acceptance criteria;
this file supplies the detailed technical guidance. The local application was
cancelled; this component runs independently and integrates directly into main.
Read `docs/README.md` for the replacement workflow and implementation plan.

## The task

Build a pure, reproducible evaluator that answers: **did this candidate checkpoint
improve this explicitly defined task over the baseline, under the planned test?**

Input is `EvaluationRequest` from `dreamlab.contracts`, containing a frozen plan
and all trial records. Output is `EvaluationReport`, containing counts, estimates,
uncertainty, verdict, limitations and provenance. Preserve evidence even when the
only defensible result is `not_evaluable` or `inconclusive`.

You own validation of statistical eligibility, methods, error control, sample-size
planning utilities, and report construction. You do not own robot control, rollout
parsing, SQLite migrations, raw video judging, the React UI, dataset upload,
fine-tuning, or automatic checkpoint switching. Ask for a contract extension when
necessary rather than depending on an application that no longer exists.
The thin runner owns file I/O and artifact persistence; the engine stays pure.

## Install, run checks, and build

From a fresh clone:

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

Use Python 3.12; uv provisions it. This branch owns its evaluation dependencies;
coordinate manifest/lockfile changes with the broader project before merging.
No robot, Dream API key, paid FaaS job or GPU is needed for evaluation development.
For an evaluation-only environment use `--extra eval` instead of `--all-extras`
and run the complete suite. The obsolete local extra and API have been removed.
No evaluation CLI is implemented yet; develop against the protocol below.

## Existing interface and intended file structure

```python
from dreamlab.contracts import EvaluationReport, EvaluationRequest


class StatisticalEvaluator:
    def evaluate(self, request: EvaluationRequest) -> EvaluationReport: ...
```

The standalone runner and future project consumers call this method directly.
Keep the core engine independent of HTTP, SQLite, filesystem state and network.
A normal request with an unsuitable design should return a `not_evaluable` report;
`EvaluationUnavailable` is reserved for missing/unimplemented functionality.
Unexpected programming errors must not turn into success verdicts.

```text
src/dreamlab/evaluation/
  README.md                 This handoff
  engine.py                 Public protocol implementation (stub today)
  cli.py                    Planned: request JSON -> engine -> saved report/manifest
  methods/
    __init__.py             Namespace exists
    validation.py          Planned: design/label/eligibility checks
    fixed_horizon.py       Planned: independent fixed-sample comparisons
    sequential.py          Planned: declared-look error control
    paired.py              Planned: matched-pair method only when validated
    planning.py            Planned: power/sample-size calculations
  reporting/
    __init__.py             Namespace exists
    report.py              Planned: deterministic EvaluationReport assembly
    render.py              Optional later: plain text/HTML rendering
tests/evaluation/
  README.md                Validation matrix
  test_handoff.py          Only scaffold-unavailability test exists today
```

Files marked **planned** must be implemented; directory names are organizational
boundaries rather than a mandate to add an empty helper for every line above.
Read `docs/contracts.md` and the actual model definitions before writing code.

## Build in this order

### 1. Input validation and honest descriptive summaries

Account for every submitted attempt. Validate exact task version, checkpoint
identity, scenarios, plan timing, label policy, held-out status, data origin,
counts and any required pairing/session structure. Structural Pydantic validation
already catches malformed fields and duplicate IDs; it does not prove that the
underlying physical attempts were independent or randomized.

For v1, require human-verified outcomes for inference. Triage/vision predictions
without verification are not ground truth. Treat `unknown` and `invalid` as
explicit categories. If they prevent a supported analysis, return descriptive
counts and `not_evaluable`, with inferential fields null. Do not quietly drop them
and claim the resulting success rate describes all attempted tasks.

The initial contract has no planned invalid-run replacement policy, automatic
label calibration, cluster model or adaptive assignment manifest. Add these with
the project integration owner before claiming support. Preserve raw outcome counts even when
estimates are withheld. Retain all trial IDs and input provenance.

### 2. Fixed-horizon independent comparison first

Implement one fully specified method before supporting every mode in the Notion.
Initial scope: prospective real trials, two distinct checkpoints, human-verified
binary outcomes, held-out data, no unresolved exclusions, and a justified
independent sampling design. Require the exact planned number of attempts per
checkpoint for a final directional verdict. Before the budget is reached, report
incomplete status and counts, with no promotion claim. Over-budget data requires
explicit handling; do not choose a favorable prefix retrospectively.

The estimand is `candidate success probability - baseline success probability`.
Display both rates and an interval for the **difference**. Comparing whether two
separate intervals overlap is not the effect-size decision rule.

Proposed initial method: explicit Wilson intervals for each arm and an explicit
Newcombe interval for the independent probability difference. statsmodels exposes
these via `proportion_confint(..., method="wilson")` and
`confint_proportions_2indep(candidate_successes, candidate_n, baseline_successes,
baseline_n, method="newcomb", compare="diff", alpha=plan.alpha)`. These are
fixed-sample, assumption-dependent methods; specify them explicitly because
library defaults may change. Verify boundaries and numerical references against
the pinned environment. See the official
[binomial interval API](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html)
and [independent difference API](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.confint_proportions_2indep.html).

Proposed decision policy (document as implementation policy, not a discovered fact):

- `improved`: lower difference bound is **greater than** `minimum_improvement`.
- `regressed`: upper difference bound is **less than** zero.
- `inconclusive`: valid, completed comparison establishes neither condition.
- `not_evaluable`: the design/data cannot support the selected inference.

The improvement threshold is a practical absolute gain in probability units.
Requiring an interval entirely above it is stricter than merely testing any gain.
The regression threshold is zero in this draft, not the negative of that margin.
Do not describe inconclusive as equivalence. Equivalence/noninferiority require
separate predeclared margins, methods and contract support.

### 3. Sequential evaluation with explicit error control

The Notion requests early stopping, but ordinary 95% intervals recomputed after
attempts do not implement a valid sequential stopping procedure. Do not enable
`group_sequential` merely by checking the current fixed-sample interval repeatedly.

A conservative proposed first implementation is a finite, predeclared schedule of
K looks. At each look compute two Clopper-Pearson arm intervals with individual
error allocation `alpha / (2*K)`. Form the difference interval as
`[candidate_lower - baseline_upper, candidate_upper - baseline_lower]`. By a union
bound this proposed construction controls total interval failure across both arms
and all declared looks at alpha, under the arm-wise binomial assumptions. The
arm intervals' confidence levels differ from the overall difference guarantee.
Use the same directional thresholds above. This is conservative; measure its
power and expected trial savings before treating it as the final product method.
The exact arm interval is exposed as `method="beta"` in the binomial API above.

A schedule field only validates when a look is allowed; the method must implement
the error allocation. Decide only when both arms reach a declared look. Preserve
interim history and terminal stopping decisions. Replaying the same ordered data
must recover the same first terminal decision; extra post-stop data cannot rewrite
history. Missing outcomes cannot silently change the sample clock or trigger an
unplanned look. The runner persists immutable look artifacts; agree the replay
contract with tureisD before enabling sequential execution.

An alternative is a justified confidence-sequence method. Choose one approach,
record its assumptions, prove or cite its guarantee, and validate it empirically.
[Howard et al., time-uniform confidence sequences](https://arxiv.org/abs/1810.08240)
is a primary reference for time-uniform inference. Do not mix fixed-sample and
sequential methods under one misleading confidence label.

### 4. Add designs only when their assumptions are supported

- **Paired trials:** require one baseline and one candidate per valid `pair_id`,
  matched setup/reset protocol, and a specified sampling unit. Use a validated
  paired effect interval. An unpaired two-proportion method ignores dependence;
  McNemar's test alone is not an interval for the effect. Until implemented,
  return unsupported/not_evaluable rather than silently falling back.
- **Sessions and clustering:** many repetitions in one scene/session may not be
  independent trials. Preserve session IDs and assess the actual sampling scheme.
  If clustered analysis is needed, coordinate its design and contract. A unique
  session string is not evidence of independence.
- **Passive deployment:** task mix, time, operator and hardware may change between
  checkpoints. Supply descriptive monitoring initially; no causal promotion verdict
  without a justified prospective assignment/comparability design.
- **Simulation:** retain its label and use it for plumbing/regression checks. Do
  not pool simulated outcomes with physical trials or label them deployment proof.

### 5. Reports and planning utilities

Return JSON-safe finite numbers or null. Include method name/version, request
checksum, all trial IDs, raw counts, effect direction, confidence interpretation,
warnings, rationale, and whether the trial budget was met. Preserve probability
units in JSON and format percentage points only for display. Do not attach a
confidence interval to a null estimate or invent a success rate for an empty arm.

Use the canonical checksum recipe in `docs/contracts.md`. Make outputs deterministic
for a fixed snapshot, engine version and configuration. If a bootstrap or other
random procedure is later added, make the seed and simulation configuration
explicit; save the exact input and method version in the runner artifact bundle.

Sample-size utilities should accept baseline rate, minimum relevant gain, alpha,
power, design and budget. Report assumptions and feasibility. The Notion's rough
350–400-trials claim is not a universal constant. The power to detect any positive
gain differs from power to prove a gain larger than a practical margin; plan for
the actual decision rule. Real robot time can make a statistically ambitious
experiment infeasible, and the tool must say so.

## Required tests before merge

The current handoff test must be replaced with meaningful engine tests when the
stub is implemented. Keep shared contract tests passing and add standalone
runner tests when that runner is implemented.

1. Independent numerical reference cases; zero/all successes, tiny samples,
   empty arms, extreme thresholds, reversed checkpoint orientation and equality
   exactly at decision boundaries. Do not validate a function by calling itself.
2. Invalid/unknown/unverified labels, contamination, duplicate imports, missing
   pairs, task/checkpoint mismatch, unplanned looks and over-budget requests.
3. Deterministic JSON/report/checksum round trips and every-attempt accounting.
4. Seeded simulation checks of interval coverage, false-positive probability and
   power over several null/alternative rates and boundary cases. For sequential
   tests, measure the probability of **any** false claim over the full schedule,
   not just the last look. Set acceptance tolerances from Monte Carlo uncertainty
   before inspecting the results; report replication counts and standard errors.
5. Validate the actual margin-based improvement rule, not only an equality-null
   p-value. Keep costly simulations marked `statistical` and publish the command
   and results needed for review. A passing simulation is evidence, not a proof.
6. Standalone JSON input -> real engine -> saved report -> reload test, with no
   robot/network dependency; verify hashes, IDs, counts and package installation.

## Traps to actively avoid

| Trap | Required response |
| --- | --- |
| Treating a stop reason or triage label as verified task success | Preserve provenance; require the supported label policy |
| Filtering failed attempts, interventions or safety stops | Retain counts; apply the frozen success rule and explain exclusions |
| Repeatedly checking ordinary confidence intervals | Use declared-look error control or a valid confidence sequence |
| Pooling paired, clustered or deployment data as IID | Validate design; reject unsupported inference |
| Training on held-out failures, then evaluating on them again | Record contamination and request fresh evaluation evidence |
| Selecting the best of many candidates on one test set | Account for repeated selection/multiplicity or use fresh confirmation data |
| Calling a nonsignificant result 'the same' | Say inconclusive; equivalence needs its own design |
| Zero-width bootstrap interval with all identical outcomes | Use a method with justified boundary behavior; test extremes |
| Claiming statistical improvement means operational acceptability | Keep intervention/safety/cost criteria separate and explicit |
| Assuming sequential stopping always saves time | Measure power and expected sample size under relevant alternatives |
| Coupling numerical methods to a UI, database or file layout | Depend only on shared contracts; keep I/O in the runner |

## Completion and merge

Provide an implemented engine with documented supported modes, assumptions,
limitations, numerical tests, operating-characteristic checks and an example
reproducible report. Unsupported modes must fail honestly. Do not mark paired,
sequential or passive causal inference supported until actually validated.

Commit only owned files unless coordinated. Fetch and merge `origin/main` when
needed; do not rebase or force-push this shared implementation branch. Resolve
dependency declarations before regenerating the lockfile. Open your PR with base
**`main`** and head **`codex/stat-eval`**. Include supported/unsupported designs,
exact test commands, statistical validation artifacts and shared-contract changes.

Validate a fresh install and the standalone input/report flow before integration.
Future project consumers can call the protocol or consume the saved report; no
web application is required. No statistical decision deploys a checkpoint or
starts a robot. See `docs/branching.md` for collaborator migration instructions.
