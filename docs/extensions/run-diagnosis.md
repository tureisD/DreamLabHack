# C specification: small run diagnosis and handoffs

Scope: read-only analysis of existing logs and traces, evidence-linked labels,
prompt grouping and versioned exports. This is a small package/CLI extension,
not the cancelled local application. No robot control, upload or training occurs.

Product goal: supplement “did it improve?” with inspectable evidence about failures
and a useful next action. The primary robustness deliverable is the human-label
study in C3.

## Why logged signals instead of a vision judge

Use recorded signals as the initial diagnostic evidence and require human-confirmed
task outcomes. [FailBench](https://arxiv.org/abs/2609.03611v1) reports limitations of
VLM success judging across sources, particularly contact-rich tasks and ambiguous
evidence; see the [verified research summary](research.md#failbench-rationale-for-signal-based-diagnosis).
Describe it as a **September 2026 arXiv preprint**, not a confirmed CoRL paper.

This motivates our design; it does not establish that our telemetry rules outperform
VLMs. Logs can expose controller behavior while missing a dropped object or failed
contact. Missing evidence therefore produces `unknown` and human review, never
an assumed success or an automatic VLM fallback. A future vision assistant could
propose labels only after separate validation and would not verify its own output.

Suggested judge-facing explanation:

> We start with logged signals because they give reproducible evidence for specific
> controller and execution faults. FailBench shows why a visual judge alone is an
> unreliable source of task-success labels. We still require a person to confirm
> outcomes, and we plan to measure diagnostic agreement on at least 50 labeled runs.

Update this explanation with measured results only after C3 is complete.
Do not compare our small diagnostic study directly with
FailBench's benchmark score as if the tasks, labels and sampling were identical.

## C1 — labels from recorded signals

Separate three records: **observed event**, **diagnostic hypothesis**, and
**human-confirmed task outcome**. A stopped run, controller error, stall or clamp
does not alone prove task success/failure. Findings can coexist with either outcome.

| Input | Planned extraction | Required interpretation |
| --- | --- | --- |
| `rollout.json` | `stop_reason`, `stalls`, `clamps`, `error`, checkpoint/prompt and recorder status | Preserve raw values; missing final counters on partial runs are unknown, not zero |
| `inference.jsonl` | Errors, stalls, discarded chunks and available timing | Deduplicate mirrored/duplicated events using source identity; discarded chunks are not executed commands |
| Trace CSV | Commanded versus measured joints, timing, divergence and oscillation | Match the correct run; use named channels/units and measured loop time |
| Recorded initial motion | Actual departure from defined rest pose within allowed initiation time | Use measured state; no inference from commanded actions or the B3 prediction probe |
| Optional camera evidence | Explicit logged camera errors or existing upstream report findings | Without camera evidence, do not diagnose a camera fault by elimination |

Every finding records run/episode ID, source artifact hash, parser/rule version,
field or row/time range, observed measurement, threshold/configuration, evidence
availability and severity. Keep multiple fault labels and an `unknown` result.
Handle partial JSONL, missing trace columns and unfinished recordings explicitly.
Parsing cannot mutate/recover original recordings in place.

### Matching the pinned robot report

Use a tested wrapper or equivalent detector validated against the pinned upstream
fixtures. Avoid importing hardware drivers merely to read a CSV. Full semantics:

- Divergence: absolute commanded-minus-measured error **greater than 0.1 rad**,
  lasting **at least 0.5 s**; respect upstream contiguous-span/time behavior.
- Oscillation: **at least 3 cycles/s** (approximately **6 reversals/s**), sustained
  **at least 1 s**; detrended swing **greater than 0.01 rad** about a one-second
  average; ignore per-tick steps of magnitude **at most 0.002 rad**.
- Irregular sample gaps, missing values and insufficient duration must produce
  explicit applicability limitations rather than a confident negative finding.

These are compatibility defaults from [the pinned source](research.md), not
universal safety limits. Version any embodiment-specific adjustment. Do not
automatically change gains, move joints, restart a driver or reset a station.

### Initiation failure from real traces

Define rest reference, counted joints, displacement threshold, required persistence
and deadline before reviewing final data. Gripper-only motion and telemetry noise
must not count as arm movement unless the task explicitly defines them that way.
Missing measured state yields `initiation_unknown`. A late start remains separate
from never starting. Human confirmation determines the task outcome under its
frozen rule; the diagnostic label is retained independently.

## C2 — group failures by prompt and suggest a next step

Group by task ID/version, prompt identity and relevant embodiment/checkpoint/session
context. Preserve exact prompt text/hash; any normalization must not merge distinct
tasks or hide changes in instructions. Report total attempts, reviewed outcomes,
multi-label findings and unknown evidence per group.

Use these recommendation categories:

| Category | Evidence supporting a suggestion | Output |
| --- | --- | --- |
| Fix your setup | Explicit camera/driver errors, trace anomalies or timing faults | Inspect the linked camera, driver or network evidence; list plausible causes without claiming certainty |
| Needs data | Human-confirmed repeated task failures in a scenario, with adequate setup evidence | Send the failure pattern and examples to Part A for review |
| Mixed | Setup evidence and task-performance problems coexist | Address documented setup issues, then reassess the residual task pattern |
| Unknown | Missing signals, ambiguous labels or insufficient examples | Request specified missing evidence/human review |

Absence of an observed setup error does not prove that more training data will help.
Network latency, calibration, policy limitations and task ambiguity may overlap.
“Needs data” remains a hypothesis, not a causal diagnosis or a promise of improvement.
Include a human override and its reason in the audit trail.

## C3 — validation against at least 50 human-labeled runs

The validation set needs **50 or more real recorded runs** with adequate evidence,
not 50 frames or 50 synthetic perturbations of one run. No such labeled set is
available yet. Public or partner recordings may be used with attribution and
appropriate access, but report their origin and applicability to Dream explicitly.

1. Write a labeling rubric for success, actual initiation, each observable fault,
   ambiguous evidence and proposed setup/data categories. Separate visible faults
   from speculative root causes.
2. Tune thresholds/parser behavior on separate development examples. Freeze them
   before the validation labels/results are inspected. If there are only 50 runs,
   do not tune on those runs and then call the same set held-out validation.
3. Freeze a validation manifest spanning available prompts, outcomes and fault
   types; document natural sampling versus enriched fault sampling. Split by run
   and, where necessary, session to prevent adjacent clips leaking across splits.
4. Have reviewers label without seeing automatic predictions; ideally two reviewers
   independently label all runs and then adjudicate disagreements. If only one is
   available, disclose that limitation rather than invent inter-rater agreement.
5. Report sample counts, label prevalence, raw agreement, confusion matrices,
   balanced accuracy for binary labels where both classes are present, per-class
   precision/recall, macro-F1 where defined, unknown/abstention coverage and reviewer
   disagreement. Explicitly report false-success predictions and missed failures,
   including ambiguous/contact-heavy cases when available. Use suitable
   run/session-level uncertainty intervals.
6. Show representative false positives/negatives and evidence. Classes absent from
   the set are unvalidated; 50 easy successes cannot establish fault-detection recall.

For multi-label faults evaluate each label separately; do not force them into one
mutually exclusive confusion matrix. Report success-label agreement separately
from diagnostic agreement and recommendation usefulness. A high percentage alone
can reflect a dominant class. Freeze numerical acceptance thresholds after the
rubric/class coverage is specified and before testing; do not choose them after
seeing favorable results. Fifty runs is an initial robustness study, not proof of
generalization across robots.

Synthetic signal fixtures are still required for parser/threshold tests. They
cannot substitute for this human-validation study. If data is unavailable, publish
the completed software checks and mark real-run validation pending.

## C4 — A2 and B1 handoffs

Part A refers to the broader project's data/training module, not the model labeled
“A” in the demo. Define two separate exports:

**To A2:** a review manifest of human-confirmed successful episodes that are
training-eligible, with task version, source hashes, labels/reviewers, diagnostics,
selection rationale and training/holdout status. The receiving module performs
its own training-format and quality validation. Success alone is not training
suitability, and this component does not copy/upload data automatically.

**To B1:** verified task outcomes for **all planned attempts**, with checkpoint,
task, scenario, session, order, actual initiation flag, intervention/safety evidence,
reviewer and source identity. Diagnostic hypotheses do not become human verification.
Preserve unknown/invalid attempts for explicit eligibility handling.

Maintain a split/exposure ledger across both exports. Active held-out evaluation
episodes are never automatically exported for training. If an experiment is retired
and its data later used for training, record that transition and require fresh
held-out evidence for subsequent confirmatory claims. Reimported/copied footage
must retain one attempt identity. This prevents the diagnosis loop from quietly
contaminating the statistical verdict.
