# Synthetic statistical validation

## Protocol frozen before execution

This is a software experiment, not evidence about any robot. The input law is
independent Bernoulli sampling with constant known probability in each arm,
complete binary labels, equal arm sizes and a precommitted design. All gains and
margins are absolute probability differences (candidate minus baseline).

- 50,000 independent replications per row; NumPy `Generator(PCG64(seed))`.
  Baseline then candidate draws, in independent binomial blocks; sequential
  counts are cumulative on the *same path*, never fresh draws per look.
- Fixed: two-sided Wilson arm intervals, Newcombe's independent difference
  interval without continuity correction, alpha .05. The event is strictly
  `lower > margin` or `upper < 0` (regression does not use minus the margin).
- Sequential: looks 20, 40, 80, 120 per arm, alpha .05; Clopper-Pearson arm
  intervals at per-arm/per-look alpha `.05/(2*4)`. The difference interval
  subtracts opposite ends. No data-dependent scheduling. Track any false
  directional claim and simultaneous difference coverage over **all four
  potential looks**, including looks after a hypothetical stop. Separately
  report actual first-stop decisions and expected attempts per arm (twice that
  for total attempts); unresolved paths use the maximum budget. A false claim
  means improvement when true gain <= margin or regression when gain >= 0.
- Report the two directional decision probabilities even when neither is power
  (e.g. at equality). For gains above margin power is P(improved); for negative
  gains directional power is P(regressed). Coverage is inclusive of endpoints.
- Numeric parity: same directional outcome, interval endpoint absolute error <=
  2e-12. Public API parity is mandatory for the integrated statistical test:
  supplied deterministic count/path probes and seeded samples of the simulated
  paths must match `StatisticalEvaluator.evaluate`; no fallback/skip on a stub.
  A separately labeled reference-only run is for debugging and is not evidence
  of working integrated inference.

| Case | Baseline | Candidate | Margin | Fixed n/arm | Fixed seed | Sequential seed |
|---|---:|---:|---:|---:|---:|---:|
| Equal | .5 | .5 | 0 | 80 | 5101 | 6101 |
| Margin boundary | .375 | .5 | .125 | 80 | 5102 | 6102 |
| Low equal rate | .0625 | .0625 | 0 | 80 | 5103 | 6103 |
| Large improvement | .375 | .875 | .125 | 80 | 5104 | 6104 |
| Regression | .875 | .375 | .125 | 80 | 5105 | 6105 |
| Modest improvement | .375 | .625 | .125 | 80 | 5106 | 6106 |
| All fail | 0 | 0 | 0 | 80 | 5107 | 6107 |
| All succeed | 1 | 1 | 0 | 80 | 5108 | 6108 |
| Perfect separation | 0 | 1 | .125 | 80 | 5109 | 6109 |
| Tiny equal sample | .5 | .5 | 0 | 1 | 5110 | n/a |

**Prespecified acceptance:** Compare each MC probability with a separate finite
binomial-mass computation of its reference expectation, within
`5*sqrt(q*(1-q)/50000) + 1/50000` for reference probability `q`. Compare mean
sample size with its finite-law expectation within five reference standard
errors plus `120/50000` attempts/arm. Report empirical binomial SEs and sample
mean SEs; an observed zero has zero plug-in SE, not proof of zero risk (for zero
events, one-sided 95% binomial upper limit is `1 - .05**(1/50000)`).
Finite expectations must additionally meet these practical grid checks:

- Fixed difference coverage >= .93; P(any false direction) <= .07. At the
  positive-margin boundary P(false improvement) <= .05. These are approximate
  interval quality screens for the selected grid, not uniform guarantees.
- Sequential simultaneous difference coverage >= .95; any-look false claim
  probability <= .05; actual stopped false probability <= any-look false.
- At the large improvement and regression rows, correct first-decision power
  >= .85 for both designs. At large improvement the sequential mean must be
  below 110 attempts/arm. No minimum power is assumed for the modest effect.
- For the all-fail/all-success rows, coverage = 1, neither direction claimed,
  full sequential budget used; for perfect separation both return improved
  with probability 1. Tiny fixed n=1: no directional claim at equal truth.
- Planner: exhaustive small-grid binomial enumeration using the library's
  Newcombe routine must match within 2e-12; strict equality and input/domain
  boundaries, infeasible budgets and the first qualifying integer (without a
  monotonic-in-n assumption) must be tested.

The protocol above was written before the first simulation. No threshold, seed,
rate or replication count was adjusted after seeing the results.

## Integrated results (synthetic IID model only)

The suite has now been executed against `StatisticalEvaluator.evaluate()`.
All 19 rows met the preregistered grid criteria; the public-method gate checked
**889 synthetic reports** and returned `public-engine-parity`. The exact count-
space references for the selected finite grid agree with the 50,000-path
simulations within the thresholds above. This does not prove universal error
control or engine equivalence for every possible input. In particular, the
fixed Wilson/Newcombe method is approximate, not a method with guaranteed
nominal coverage at every sample size. **Exact enumeration at n=2 and equal
success probabilities gives 12.5% false directional verdicts and 87.5%
coverage**. Such a small-budget fixed comparison should not be used to claim
robot improvement; more generally, evaluate sample-size-specific risk and power
before relying on a design. These are synthetic software operating
characteristics, not robot trials, proof of independence, safety evidence or
deployment advice.

| Case | Mode | Diff. coverage | Any false claim | P(improve) | P(regress) | Mean n/arm |
|---|---|---:|---:|---:|---:|---:|
| Equal | Fixed | .95266 | .04734 | .02332 | .02402 | 80 |
| Equal | Sequential | .99976 | .00024 | .00014 | .00010 | 119.9900 |
| Margin boundary | Fixed | .94956 | .02250 | .02222 | .00028 | 80 |
| Margin boundary | Sequential | .99984 | .00006 | .00006 | 0 | 119.9968 |
| Low equal | Fixed | .96000 | .04000 | .01998 | .02002 | 80 |
| Low equal | Sequential | .99998 | .00002 | 0 | .00002 | 120 |
| Large improvement | Fixed | .94678 | 0 | .99970 | 0 | 80 |
| Large improvement | Sequential | .99974 | 0 | .99324 | 0 | 71.0004 |
| Regression | Fixed | .94632 | 0 | 0 | 1 | 80 |
| Regression | Sequential | .99982 | 0 | 0 | 1 | 44.8752 |
| Modest improvement | Fixed | .94934 | 0 | .34406 | 0 | 80 |
| Modest improvement | Sequential | .99984 | 0 | .02140 | 0 | 119.5532 |
| All fail / all succeed (each) | Fixed | 1 | 0 | 0 | 0 | 80 |
| All fail / all succeed (each) | Sequential | 1 | 0 | 0 | 0 | 120 |
| Perfect separation | Fixed | 1 | 0 | 1 | 0 | 80 |
| Perfect separation | Sequential | 1 | 0 | 1 | 0 | 20 |
| Tiny equal sample | Fixed | 1 | 0 | 0 | 0 | 1 |

Numbers in the table are MC estimates, not exact probabilities. For example,
the positive-margin fixed false improvement estimate .02222 has SE .000659;
the sequential any-look false estimate .00006 has SE .0000346. At the modest
alternative, power SEs are .002125 (fixed) and .000647 (sequential); for large
improvement the sequential mean sample size SE is .1165 attempts/arm. All
seeds, estimates, plug-in SEs, finite-law references, and comparison tolerances,
including first-stop false claims, are in
[`tests/evaluation/reference_operating_characteristics.json`](tests/evaluation/reference_operating_characteristics.json).
The sequential procedure is conservative on this grid: it need not save trials
or be well powered for a modest gain. Fixed and sequential budgets differ here.

## Reproduction and integration gate

Use Python 3.12 and the committed lockfile (SHA-256
`f7cc036f324c1612248abe1e563fe19aed72b9b538c0df3ff8da4f2b0d9831f4`). This run:
Python 3.12.3, NumPy 2.5.5, SciPy 1.18.1, statsmodels 0.15.0. From the repo root:

```sh
uv sync --locked --all-extras --group dev
uv run --locked --all-extras pytest -q tests/evaluation/test_planning.py
uv run --locked --all-extras python tests/evaluation/operating_characteristics.py --reference-only
uv run --locked --all-extras pytest -q -m 'not statistical'
uv run --locked --all-extras ruff check .
uv run --locked --all-extras ruff format --check .
```

After bringing these files together with the actual engine, run **without**
`--reference-only`. The default runner emits JSON with the method/version and
count of audited public reports; do not substitute a reference-only JSON.

```sh
uv run --locked --all-extras pytest -q -m statistical tests/evaluation/test_operating_characteristics.py
uv run --locked --all-extras python tests/evaluation/operating_characteristics.py
```

For efficiency, finite count tables index vectorized draws. A separate
finite-state calculation convolves independent binomial block masses, removing
paths at first stop, first noncoverage, or first false claim in **separate**
recursions. Default parity evaluates valid synthetic contract requests on every
reached look of the first 12 paths per row. It adds all fixed count pairs at
n=1 and 8 and probes adjacent count pairs on both verdict boundaries at each
scheduled sample size. It compares raw counts, rates, arm and difference
bounds, point effect and strict verdict at each reached look. Fixtures carry
explicit synthetic IDs/URIs; `prospective` and verified flags exercise the
eligible path in software only. Simulating every request would require up to
millions of large contract snapshots. This bounded parity gate is not an
exhaustive proof of engine equivalence, validation of every contract rejection,
or a test of how the engine treats submissions after stopping. Counterfactual
post-stop looks contribute to simultaneous validity checks only.

## Using the planner

`fixed_horizon_power` calculates `P(Newcombe lower > minimum_improvement)`
for specified `baseline_rate`, `candidate_rate`, and `trials_per_arm`, even at
a null or boundary. `plan_fixed_horizon` instead takes an **alternative gain**
strictly above the decision margin and an explicit `max_trials_per_arm` (1 to
512). Defaults: independent equal arms, fixed horizon, two-sided alpha .05,
target power .80; there is no default budget or effect. Both utilities assume
complete, human-verifiable IID outcomes, a predeclared single comparison and
constant supplied arm probabilities. They do not estimate baseline uncertainty,
model missingness, support unequal/paired/clustered/sequential designs, or
translate sample counts into operational cost. Plan before seeing outcomes.

```python
from dreamlab.evaluation.methods.planning import plan_fixed_horizon

plan = plan_fixed_horizon(
    baseline_rate=0.375, alternative_gain=0.25, minimum_improvement=0.125, max_trials_per_arm=500
)
```

With baseline .375, assumed gain .25, margin .125 and target power .80, the
smallest qualifying size is 242/arm (484 total), with power .801253. With a
budget of 80/arm, the recommendation is `None`, `feasible` is false, and
`power_at_budget` is .343811. These numbers are conditional on the
assumed rates, not a universal sample-size requirement. Infeasibility means
*no integer within the supplied budget* qualifies; invalid inputs or a budget
above the computational cap of **512 attempts per arm** raise `ValueError`.
For each n, the implementation binary-searches the shared Wilson/Newcombe lower
bound for each baseline count, then sums exact finite-binomial tails in
float64. The searched decision boundary is the same public production
calculation (including outward rounding of collapsed floating-point intervals).
Search checks each n up to the first qualifying integer: discrete power need
not increase monotonically. Across all sizes this requires O(B² log B) arithmetic
in the worst case and O(B) working memory.
