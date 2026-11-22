# Extension tickets, contracts and validation

Planning only. Implement after the parent engine's numerical validation, runner
and reproducible artifacts are ready. Synchronize the parent into this branch first.

## Dependency order

| Ticket | Scope | Depends on | Exit evidence |
| --- | --- | --- | --- |
| X00 | Verify parent release and agree versioned extension contracts | Completed parent | Core reference tests pass; engine/runner API pinned; no competing baseline implementation |
| X01 | STEP packaging/license/runtime spike, explicit method/mode and policy readiness | X00 | Windows/Linux install; pinned dependency/policy manifests; upstream decisions reproduced |
| X02 | STEP adapter and sequential report | X01, contract review | Orientation, zero margin, terminal replay, unsupported inputs and full-sequence error checks |
| X03 | Complete observation cache and read-only cache replay | X00 | Context-safe keys, corruption/concurrency tests, bounded acquisition plan, zero network replay |
| X04 | Common 48-row scorer and gripper-window masks | X03 | Units/time/representation checks; frozen shared masks; healthy/empty/short-horizon tests |
| X05 | Rest-pose initiation screening | X03 | Valid histories, defined displacement, noise/gripper/representation tests |
| X06 | Episode/cluster bootstrap and screening report | X04–X05 | Paired resampling across models, reproducible draws, explicit low-sample limitations |
| X07 | Dream signal parser and run findings | X00 | Pinned upstream thresholds, trace provenance, missing/partial/duplicated-log tests |
| X08 | Prompt grouping and A2/B1 exports | X07, reviewed schemas | Mixed/unknown handling; human verification and holdout firewall tests |
| X09 | At least 50-run diagnosis validation study | X07–X08, real data/reviewers | Frozen rubric/split, agreement, balanced accuracy where defined, false-success/missed-failure analysis, uncertainty and limitations |
| X10 | Cached A/B/base and STEP replay demo | X02, X06, X08 | Recompute twice identically; no paid calls; authentic chronology/provenance |
| X11 | Integration PR into parent, or main after parent retirement | Relevant gates above | Reviewable results, exact commands, licenses, capabilities and unresolved-data limitations |

X09 is a data dependency, not a reason to fabricate labels or call synthetic
fixtures a real-run study. Work on reproducible software tests can proceed while
waiting for recordings. Do not claim the whole extension is validated until its
required evidence is available.

## Proposed modules; create when implemented

```text
src/dreamlab/evaluation/
  methods/step_adapter.py        wrapper around pinned released STEP
  offline/                      observation alignment, window masks, scoring, probes
  cache/                        complete inference-context keys and response artifacts
  reporting/                    screening, sequential evidence and replay outputs
src/dreamlab/diagnosis/
  parsers.py                    bounded read-only Dream log/trace parsing
  rules.py                      versioned findings and measured initiation
  grouping.py                   task/prompt aggregates and recommendations
  handoff.py                    reviewed A2/B1 manifests with exposure checks
tests/evaluation/               parent tests plus adapter/offline/cache/runner checks
tests/diagnosis/                thresholds, evidence, grouping, exports and study checks
tests/fixtures/                tiny synthetic cases + manifests for external evidence
```

This is organizational guidance, not a request to create empty code modules now.
Keep heavy model inference dependencies optional and outside the pure numerical
engine. A narrow replay report/visualization may be added for B6; a general app
or robot-control UI is outside scope.

## Proposed records and schema review gate

| Record | Essential information |
| --- | --- |
| `ScreeningPlan` | Dataset/episode hashes, split, prompts, immutable checkpoints, action schema, frequency, 48-row horizon, event/normalization config, bootstrap settings |
| `InferenceArtifact` | Full effective input/context fingerprint, checkpoint revision, decoder/sampler config, draw/seed, raw response and action hashes, provider identity |
| `ScreeningReport` | Per-model/per-episode error, paired uncertainty, probe risk, valid/excluded anchors and explicit proxy interpretation |
| `SequentialComparisonPlan` | Hypotheses/mode, actual method, max per arm, alpha, supported margin, order/assignment protocol, seed, policy/dependency hashes |
| `SequentialComparisonReport` | Raw decision, interpretable conclusion, ongoing/terminal status, stop index, input prefix, counts and test evidence; no fabricated interval |
| `RunDiagnosis` | Run identity, source hashes, parser/rule config, observed faults, actual initiation, evidence anchors, hypotheses and unknowns |
| `HumanRunLabel` | Task rule/version, outcome, initiation/fault labels, reviewer, revision, evidence and adjudication |
| `A2Selection` / `B1TrialExport` | Source identities, reviewed labels, exposure/split eligibility, provenance and receiving-schema version |

These records are proposals, not additions to the current v1 Pydantic schema.
The current report requires an interval for a directional verdict and cannot
truthfully encode a bare STEP result. Decide a new version/separate report type
with the parent owner before implementation; keep old request/report fixtures
working. Avoid catching schema errors and silently dropping new fields.

## Required validation matrix

| Area | Meaningful checks |
| --- | --- |
| STEP identity | Explicit STEP class; reject unintended Lai switch; method/dependency/policy hash in output |
| STEP interpretation | Baseline/candidate orientation; mode-specific `AcceptNull`; no invented equivalence/regression; nonzero margin rejected until supported |
| STEP readiness | Missing/mismatched policy, failed synthesis or unavailable package returns execution error rather than a statistical non-decision |
| STEP sequencing | Exact original order; uneven arrivals buffered without invented outcomes; first terminal result preserved; exhausted versus ongoing distinct |
| STEP validity | Independent null/boundary/alternative simulations, complete stopping procedure, RNG procedure and intended multiplicity; compare upstream reference cases |
| Horizon/masks | 48 rows at same physical rate; units/normalization/target alignment; shared masks; no-event/short-episode/short-response cases |
| Probe | Absolute/delta representation, valid history, rest/noise/gripper-only output, positive motion and unknown unsupported inputs |
| Cache | History/prompt/body/decoding changes invalidate key; duplicate requests coalesce; missing/corrupt entry blocks offline replay; no billed retry loop |
| Bootstrap | Episode/cluster resampling, same draws across checkpoints, no frame pseudo-replication, reproducibility and degenerate/small-sample handling |
| Diagnosis | Divergence duration/boundary; cycles versus reversals; swing/noise thresholds; missing channels, irregular timestamps and partial logs |
| Interpretation | Fault is not outcome; predicted initiation is not measured initiation; conditional started-run success cannot replace overall success |
| Diagnostic evidence | Missing/ambiguous signals yield unknown and human review; no automatic success or unvalidated vision-judge fallback |
| Exports | Human review required; all attempts retained; alias deduplication; active holdout never enters A2; later exposure transition auditable |
| Demo | Actual cached recomputation, two identical canonical result hashes, no external calls, correct first stop and visibly authentic/synthetic data origin |

Testing tiers: fast deterministic fixtures on every relevant change; pinned
upstream adapter/packaging checks before release; full seeded statistical studies
for method changes; real human-labeled diagnosis validation when data is available.
Save config, seeds, independent unit counts, uncertainty, exact inputs and expected/
observed results. Keep large recordings, caches, credentials and generated reports
outside tracked source, using checksummed manifests.

## Scope and go/no-go checks before a submission

- Parent baseline remains usable independently; extensions cannot break its public
  contract or silently change previously supported method semantics.
- No package or model is described as validated merely because its import succeeds.
- Paper numbers are cited as literature results; our gripper heuristic and probe
  have their own validation status.
- Part C explains the signal-based choice using FailBench as a September 2026
  arXiv preprint, without a CoRL claim or an unsupported claim that our rules beat
  its VLMs. The 50-run agreement study remains our own required robustness evidence.
- Missing real trials or fewer than 50 suitable labeled runs remain explicit gaps.
- Cache-only demo is ready before stage time; policy synthesis and paid acquisition
  are separate preparatory operations, not surprise background work.
- No training on active held-out runs, no fake sequential confidence animation,
  and no automatic hardware commands or model promotion.
