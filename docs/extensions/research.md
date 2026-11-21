# Research audit and implementation implications

Reviewed 21 November 2026. Primary papers and source code were inspected. No STEP
method, model inference, robot trial, or 50-run annotation study was executed here.

## B1: STEP

The RSS 2025 paper is **Is Your Imitation Learning Policy Better than Mine? Policy
Comparison with Near-Optimal Stopping**. It studies sequential binary policy
comparisons; its reported advantage concerns evaluated regimes, not a universal
promise for every experiment below 1,000 trials. [RSS proceedings](https://www.roboticsproceedings.org/rss21/p077.html),
[author project](https://tri-ml.github.io/step/).

Audited TRI repository revision: `3ae1623906f82fe472a352ed4a6b8e4a712f1f3d`;
`setup.py` declares package version 0.0.9. Pin the tested package, core dependency,
policy artifacts and configuration during implementation. The read-only source
audit found these integration issues:

| Finding | Required plan adjustment | Evidence |
| --- | --- | --- |
| Factory selects Lai above default `n_max=500` | Instantiate the chosen STEP class explicitly; report actual method | [auto.py](https://github.com/TRI-ML/sequentialized_barnard_tests/blob/3ae1623906f82fe472a352ed4a6b8e4a712f1f3d/sequentialized_barnard_tests/auto.py) |
| STEP returns a decision with time/state; it has randomized boundaries and policy loading/synthesis | Preserve experiment seed, validate readiness, precompute matching policies; no invented p-value/CI | [step.py](https://github.com/TRI-ML/sequentialized_barnard_tests/blob/3ae1623906f82fe472a352ed4a6b8e4a712f1f3d/sequentialized_barnard_tests/step.py) |
| Mirrored modes distinguish comparison, ranking and ranking without ties; ranking adjusts policy alpha | Freeze semantics; never map every `AcceptNull` to regression or equivalence | [step.py](https://github.com/TRI-ML/sequentialized_barnard_tests/blob/3ae1623906f82fe472a352ed4a6b8e4a712f1f3d/sequentialized_barnard_tests/step.py) |
| License is CC BY-NC 4.0 | Retain attribution/terms; resolve permitted distribution/use before packaging commercially | [LICENSE](https://github.com/TRI-ML/sequentialized_barnard_tests/blob/3ae1623906f82fe472a352ed4a6b8e4a712f1f3d/LICENSE) |
| Normal Windows checkout failed on colons in example result filenames | Use a verified distribution or no-checkout + sparse checkout excluding problematic data paths; test Windows installation | [example data tree](https://github.com/TRI-ML/sequentialized_barnard_tests/tree/3ae1623906f82fe472a352ed4a6b8e4a712f1f3d/data) |

The source inspected for STEP does not expose a practical-improvement-margin
argument in its constructor. Our first adapter should support a zero-margin claim
only, or remain blocked pending a justified extension. A zero-gap test cannot
certify the parent's nonzero `minimum_improvement` by renaming its result.

## B2–B4: offline metrics and initiation

**Does Validation Loss Predict Real-Robot Success?** (Cowling, arXiv:2611.00283v1)
reports 82 checkpoints and 930 bench rollouts on one SO-101 task. Action-error
rankings were misleading across families and uninformative among same-budget
seeds; initiation failures exposed a gap in demonstration-based validation.
These are task-specific findings, not a universal failure frequency. Our cheap
rest-pose prediction probe is a proposed response requiring its own validation.
[Paper](https://arxiv.org/html/2611.00283v1).

**Critical Interval MSE** (Huang et al., arXiv:2606.29898v2) reports Spearman
correlation **-0.61 to -0.87** and regret@1 **42.5 to 0 percentage points** in its
simulation comparison. Full CI-MSE combines annotated intervals and action alignment;
interval filtering alone gives **-0.78** and **25.8 points** in its ablation.
Our gripper-only windows therefore cannot inherit the full method's numbers.
The paper uses different evaluated chunk ranges across settings; **48 rows is
our proposed common-horizon convention**, not its reported universal prescription.
[Paper and ablations](https://arxiv.org/html/2606.29898v2),
[official implementation](https://github.com/CI-MSE/CI-MSE).

The SO-101 study also uses different horizons across some policy families. This
motivates controlling horizon and physical time, but does not validate a specific
48-row threshold. Record representation, units, frequency and prediction alignment.

## C1: actual Dream thresholds

Pinned Dream source: `ba8ad9850dd2e783b3c10fc079b0b5f78d7df441`.
The report flags joint discrepancy above **0.1 rad for at least 0.5 s**.
Oscillation uses **3 cycles/s**, equivalent to approximately **6 direction
reversals/s**, sustained for at least **1 s**, with detrended peak-to-peak swing
above **0.01 rad** and a **0.002 rad/tick** noise threshold. Copying “3 reversals/s”
alone would not match upstream behavior.
[Source constants and detector](https://github.com/dreamlabs-co/dreamlabs/blob/ba8ad9850dd2e783b3c10fc079b0b5f78d7df441/dream_library/robots/src/robots/run_report.py).

Missing logs/counters remain unknown; stop/error/stall/clamp signals do not establish
task success. Keep sidecar origin and source hashes. Current run-report thresholds
are compatibility defaults, not calibrated fault definitions for every robot.

## Claims permitted in a submission

Say “STEP adapter based on the released RSS method” only after integration tests;
say “gripper-event screening inspired by CI-MSE” for our heuristic. Report our
measured accuracy, cost and repeatability separately from paper numbers. Replaying
public real outcomes is not collecting our own hardware evidence. Two identical
cached runs prove reproducibility of that pipeline, not policy reliability.
