# B specification: STEP, screening, probes and replay

All items are planned follow-ons. Complete the parent baseline first. Keep offline
screening results and real-trial inference in distinct report types.

## B1 — integrate released STEP

Use a small adapter in `evaluation/methods/step_adapter.py`; do not reimplement the
optimal-stopping algorithm. Initial hypothesis: baseline `p0`, candidate `p1`, with
the one-sided alternative `p1 > p0`. Set `n_max` as the planned maximum **per arm**.
Instantiate the pinned STEP class explicitly, avoiding the factory's automatic
method switch. Initially support independent binary trials and zero practical
margin only. Handle other requests as unsupported until justified.

Before any outcomes, freeze task rule/version, checkpoint identities, order and
allocation protocol, risk budget, maximum trials, look behavior, seed and exact
policy artifact. A STEP update accepts one new outcome from each arm; it does not
establish a matched-pair statistical design. Do not treat clustered or correlated
matched trials as independent without a validated method.

Human-confirm all input outcomes. Retain unresolved/invalid attempts in accounting
and stop inference if the declared method cannot handle them. Do not silently drop
non-starting runs, interleaved errors, or inconvenient episodes. Preserve recorded
trial order; do not shuffle replay to produce a shorter or more impressive stop.

Preload and validate the decision policy for the exact configuration. Policy
synthesis may be costly and must happen before a stage demo. Missing policy or a
failed synthesis is an execution/readiness error, not a valid inconclusive result.
Only load trusted, hash-verified artifacts; upstream policy serialization must not
be exposed as an arbitrary user-supplied executable format.

Record upstream raw decision, hypothesis, mode, stop index, counts, RNG seed/state,
policy hash and dependency versions. Stop at the first terminal result and preserve
it on restart. Interpret `AcceptNull` according to the selected upstream mode;
it is not automatically proof of equality or regression. A directional regression
claim requires its own supported, error-controlled procedure. Preserve the parent's
fixed-horizon method as a separately named capability rather than silently changing
the meaning of previously generated reports.

### Required contract decision before implementation

Parent v1 requires a difference interval for directional verdicts. STEP provides
a test decision rather than an effect interval. Do not manufacture an interval,
insert a fixed-horizon interval as if it were anytime-valid, or weaken v1 silently.
Agree a versioned sequential report containing `test_evidence`, hypothesis, alpha,
budget, stopping state and optional **separately justified** interval fields.
Also define an explicit ongoing state; exhausted-budget inconclusive and an
unfinished test must be distinguishable. Implement and test schema migration with
the parent owner before exposing a STEP verdict through the shared API.

If a nonzero `minimum_improvement` is requested, refuse the STEP route until a
method/extension addresses that exact margin. Do not subtract a margin from binary
outcomes or treat zero-gap significance as a practical-margin guarantee.

For A, B and base, predeclare a single confirmatory comparison or a comparison
family with justified multiplicity control. Showing three offline scores is not
three validated real-trial comparisons. Choosing the winner from many checkpoints
also requires fresh confirmation or a justified selection-aware design.

## B2 — critical-window action screening

Use the same frozen held-out episodes, observation anchors, action channels and
event mask for every checkpoint. Identify gripper close/open transitions from
**recorded reference signals**, never from each candidate's own predictions.
Specify channel polarity, range, units, hysteresis, debounce and missing-data rules.
Expand events by a short fixed window in physical time, convert using the declared
clock/rate, merge overlaps and clamp to episode bounds. Choose window widths on
development data, then freeze them before comparison.

Call the first implementation **gripper-event critical-window error**. It is a
cheap heuristic inspired by CI-MSE. For insertion, pushing, continuous grasps and
tasks with no transitions, events may miss crucial contact. Empty/unsupported
masks return `not_available`, not zero error; manual annotated masks can be an
explicit separately versioned fallback. Assess mask coverage against human
interval labels before claiming annotation quality.

Require a **48-row horizon** for all compared checkpoints at one agreed output
frequency. Preserve its physical duration and the observation-to-target offset.
Require enough recorded future targets for all 48 rows; use the same valid anchor
intersection across checkpoints and report exclusions. Do not pad a shorter
prediction or silently score fewer rows. If a checkpoint cannot supply this
horizon/rate, mark the comparison unsupported until a validated adapter exists.

Agree action representation before comparison: absolute joints versus deltas,
joint order, angle units, gripper units, normalization and embodiment. Raw predicted
actions must not be confused with ramped/clamped executed commands. If deployment
alignment, temporal ensembling or warping is added, version it and expose an ablation;
do not claim exact paper reproduction for a different scoring procedure.

Proposed initial scalar: squared error on the fixed critical mask, aggregated within
each episode and then equally across episodes. Record per-channel values and the
normalization/weighting chosen on development data. This is our metric definition,
not the paper's aggregation. Show raw full-trajectory error as a diagnostic ablation,
not the checkpoint verdict. Test sensitivity to windows/horizon on development data;
do not select parameters by which checkpoint wins the final comparison.

## B3 — rest-pose initiation probe

Freeze a small probe set covering valid rest states, task prompts and observation
histories. Include the correct state vector, camera history and reset/session
semantics expected by each checkpoint. One isolated frame is not necessarily a
valid input to a temporal policy. Use the same probes and decoding settings across
checkpoints, with explicit repeated draws if stochastic response variability is
being studied.

Convert each predicted chunk to the agreed action representation. For absolute
joint targets, measure predicted displacement from rest; for relative actions,
use the documented accumulation/kinematics. Specify which joints count, duration,
threshold units, and a persistence condition so gripper-only motion or a single
noisy row does not pass as arm initiation. Freeze the threshold using development
examples and do not tune it to the final checkpoint ranking.

Report `predicted initiation risk`, displacement and probe coverage. This catches
some no-motion outputs, but cannot prove the arm will move: drivers, limits,
collisions and closed-loop behavior remain unobserved. In C1, actual initiation
failure uses recorded **measured** motion and is a distinct field.

## B4 — interpretation and outcome accounting

B2/B3 can rank candidates for further testing and inform training checkpoint
selection or early stopping. They do not supply robot success probabilities or
replace B1. Repeatedly selecting checkpoints on these screens uses development
information; preserve fresh confirmatory evidence for the final real comparison.

For verified trials show overall success, initiation rate, and success conditional
on actual initiation, with numerator/denominator and missing-label counts. The
conditional rate is descriptive: excluding non-starts can favor a policy that
rarely moves and creates selection bias. B1's primary outcome remains the frozen
overall task success rule, including non-starts that the rule classifies as failures.
If initiation is unknown, do not infer it from the offline probe or omit that count.
With unresolved outcomes, suppress unsupported success estimates rather than
quietly treating unknowns as failures or successes.

## B5 — caching, seeds and bootstrap

Cache every completed model response. A safe key must cover immutable checkpoint
revision, the **full effective observation/history** hash, prompt, state/body/schema,
preprocessing and normalization versions, action head, inference parameters, seed
or draw index, and relevant session/reset context. A checkpoint name plus a hash
of the newest image is insufficient for a stateful model.

Store raw response, decoded action, request fingerprint, provider/request ID,
timing/cost metadata when supplied, and output hash. Never store API secrets in
artifacts. Publish atomically and deduplicate concurrent identical requests.
On a billed timeout, record an uncertain outcome and reconcile using provider
identity where possible; do not silently retry and incur another charge.

Provide explicit acquisition and cache-only modes. Acquisition has a precomputed
request count/budget and requires deliberate invocation. Stage replay is cache-only:
missing/corrupt entries fail readiness before the demo, and no network fallback is
allowed. No acquisition is performed during this planning task.

Seed offline resampling and choose the STEP experiment seed before outcomes.
STEP may use randomized boundary decisions: reproducibility is not permission to
search seeds for a desired verdict. Validate its error guarantee over independent
experiments, including the intended RNG procedure; do not assume the proof is
conditional on one universally reused seed.

Use an episode-level paired bootstrap for offline checkpoint differences: resample
the same episodes for A/B/base. If sessions are the independent unit, resample
sessions instead. Never count overlapping windows or frames as independent samples.
Freeze replication count, confidence level, seed and interval method. Too few
independent units or degenerate samples require an explicit limitation; no fabricated
zero-width certainty. These bootstrap intervals do **not** provide STEP's sequential
stopping guarantee or prove that the offline proxy predicts physical success.

Two cache-only runs must have identical scores, resampling indices, STEP decision
and stop index. Compare canonical result artifacts after excluding invocation
timestamps/runtime from the deterministic payload. Identical output demonstrates
pipeline repeatability, not repeatability of a stochastic robot in the world.

## B6 — live demo sequence

1. Readiness: verify manifest hashes, complete cache, licenses/attribution, input
   provenance, installed versions and matching precomputed STEP policy.
2. Recompute offline A/B/base scores, intervals and initiation probes from cached
   model responses. Display that no live inference is taking place.
3. Replay frozen, human-confirmed real outcomes in original order. Show cumulative
   attempt counts, outcome counts, selected test and current/terminal state.
4. At the first stop, freeze the decision and show the consumed prefix and any
   additional recorded trials separately. Never optimize the order for a fast stop.
5. Repeat from the same manifest and compare result hashes.

For the requested tightening-bound visualization, add a separately validated
anytime-valid confidence sequence only if its assumptions and coverage are tested.
Otherwise visualize STEP's stopping state and descriptive cumulative rates; do not
label ordinary/bootstrap intervals as STEP bounds. Valid intervals need not tighten
monotonically, so do not animate invented monotone progress.

If own hardware outcomes are unavailable, use clearly attributed public real-trial
logs whose protocol permits the analysis, or a visibly synthetic fixture. The demo
can show the tool running live without claiming that robot trials occurred live or
that a cached offline screen established real-world improvement.
