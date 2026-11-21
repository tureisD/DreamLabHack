# Contract v1 and integration responsibilities

Canonical definitions: `src/dreamlab/contracts/models.py`. This is a draft v1
boundary agreed through code review, not the Dream Labs upstream schema. Preserve
backward compatibility or increment schema version with agreement between the evaluation owner and consuming project modules.

## Input

`TaskSpec` fixes task identity/version, instruction, observable success, reset
procedure and timeout. `EvaluationPlan` fixes the two checkpoints, scenario IDs,
design, mode, alpha, practical improvement threshold, sample budget, label policy,
randomization seed and creation time. IDs are nonempty strings; timestamps include
timezones. Differences are probability units: `0.10` means 10 percentage points.

`planned_trials_per_checkpoint` counts **attempts**, not successful or conveniently
labeled runs. Replace an invalid trial only under a rule declared before the
experiment; v1 has no replacement rule and therefore does not authorize replacement.
`planned_looks` records attempted counts per checkpoint at which a sequential
method may decide. The numerical guide describes the implemented error control
and its assumptions. [Sequential method](../src/dreamlab/evaluation/README.md#finite-look-sequential-method)

Every `Trial` identifies an episode, task version, checkpoint, scenario, session,
optional matched pair, source URI and timestamp. `collection_mode` distinguishes
prospective real runs, passive deployment and simulation. `training_exposure` is
explicitly held-out, used-for-training or unknown; there is no optimistic default.

Store outcome separately from stop reason. Human verification requires a reviewer;
an invalid attempt requires a nonempty reason. `label_source` records the origin
of the proposed label even when a human later verifies it. Unknown and invalid
are retained in the request and all displayed attempt counts.

An episode ID represents one physical attempt across imports. It must not be
reused to count the same footage twice. Retries are separate attempts with new
IDs, linked through producer-side provenance metadata if needed.

## Responsibilities beyond structural validation

Pydantic rejects unknown fields, malformed IDs, duplicate trials/episodes,
checkpoint/task/scenario mismatches, missing verification/exclusion metadata, and
nonfinite numerical values. It does **not** certify statistical suitability.

The evaluation engine must additionally check:

- Plan fixed before evaluation; comparable task/reset/label protocol and trial order.
- Held-out training exposure and human verification for all inferential outcomes.
- Exact planned budget for fixed-horizon final decisions; explicit partial status.
- Unsupported design/mode; missing pairs; session clustering and repeated dependence.
- Unresolved unknown/invalid outcomes, selective exclusions and unplanned replacements.
- Passive vs prospective vs simulated data; do not pool them into one promotion claim.

Some checks need future contract extensions, such as full randomization manifests,
reset confirmation, rater versions, analysis-method configuration or intervention
acceptance rules. Coordinate additions before supporting those features. Do not
pretend existing fields alone prove randomization or independence.

## Output and reproducibility

`EvaluationReport` includes separate summaries accounting for all attempts, an
optional effect and interval, a decision, method/version, input SHA-256, rationale,
warnings and the underlying trial IDs. `successes`/`failures` are raw submitted
outcome counts; estimated rates/intervals are null if inferential eligibility fails.

`improved` and `regressed` require evidence. `inconclusive` means a supported
comparison did not establish a directional result; `not_evaluable` means the inputs
or design cannot support the intended inference. Do not return NaN, infinity, fake
zero-width intervals or zeros for undefined estimates. A report is not approval
to deploy a model.

The canonical input checksum is SHA-256 over UTF-8 `json.dumps(request.model_dump(
mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)`. Preserve
trial order for sequential replay. The standalone runner saves the submitted
bytes, canonical bytes, report and reproducibility manifest. Include all method
options and seeds in a versioned configuration before adding stochastic algorithms.
Keep results independent of wall-clock time and hidden global RNG state.

Statistical consumers may only import `dreamlab.contracts` and statistical
dependencies. The runner owns file I/O and calls the protocol. Other project
modules may call the same protocol without a web application. Schema changes
require producer/consumer review and fixture updates.
