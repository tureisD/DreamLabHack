# Why Teach it a task makes Dream-1 iteration easier

**Product claim:** Teach it a task helps a robot operator decide what to demonstrate, whether a FaaS job is ready to submit, and whether its checkpoint improves the task consistently enough to deploy. Dream Labs supplies Dream-1, FaaS, and the robot library. The coach adds evidence and decision support around those capabilities. All of these steps are possible manually; the product makes them repeatable and easier to audit.

## The operator's decision loop

| Decision | Evidence the coach collects | Action it supports |
| --- | --- | --- |
| Is this a setup fault or a model limitation? | Station and camera freshness, rollout completion, logs, operator-labelled failure stage | Fix the station or camera before collecting more training data. |
| What should I record? | Baseline failures by tabletop cell, accepted demos by cell, demo quality findings | Record examples at observed failure positions; redo unusable demos. |
| Is this dataset ready for FaaS? | Frozen dataset version, local Dream validation, remote processing state | Submit one reviewed job, or correct the data and retry processing. |
| Did the fine-tune help? | Predeclared matched base/candidate scenes, task-level success labels, incomplete runs, safety stops | Promote, collect different data, run more trials, or leave the current model in place. |

The app supports these decisions with Tasks, Demos, Training, Guide, and Evaluation screens. The apple simulator experiment also uses task-specific command-line recording and scoring scripts. It demonstrates the evaluation method; it is not a general simulator teleoperation product or a one-click path for every robot.

## What the apple experiment taught us

We trained one 500-step checkpoint from 24 scripted YAM simulator demonstrations. The [first held-out test](experiments/yam_sim_faas/grasp_training/HELDOUT_500_STEP_EVAL.md) said **fine-tune 1/4, base 0/4**. A user seeing only that score might pay for another job or discard a useful checkpoint.

The traces exposed two evaluation problems: the nine-request window ended while the fine-tune was still lifting the apple, and one tiny finite gripper overshoot stopped an otherwise usable action chunk. The base model had a different behavior: it generally closed its gripper very early, before reaching the apple. We extended the trial, safely clamped small prediction overshoots, recorded actual apple height, and required an 8 cm lift held for two seconds. We fixed the [fresh comparison protocol](experiments/yam_sim_faas/grasp_training/CONFIRMATION_PROTOCOL.md) before running new scenes. On seeds 905–908, the **same unchanged fine-tune passed 4/4 and the base passed 0/4**. The [full report](experiments/yam_sim_faas/grasp_training/EXTENDED_500_STEP_EVAL.md) gives every run ID, lift measurement, replay check, and limit.

This did **not** improve the model's weights. It prevented a misleading measurement from driving the next decision. The justified next step is to challenge this checkpoint with harder, reserved scenes and real robot trials, not to buy more training on similar apple placements simply because the first score looked poor.

## Where time and money could be saved

- **Before training:** demo review and dataset validation can catch missing video, idle starts, action faults, and poor failure-cell coverage before a paid FaaS submission. This can avoid a job on unsuitable data; we have not measured an avoidance rate.
- **After training:** matched, task-level evaluation can distinguish a model failure from a short trial, incomplete run, camera or station fault, or scoring mistake. The apple experiment found a false negative without purchasing another FaaS job.
- **For the next iteration:** the coverage map and failure-stage labels point at particular missing demonstrations. A new job is warranted when a reproducible failure remains and the new data addresses it. More steps alone are not an automatic recommendation.

For users, the potential savings are operator time, avoidable demo collection, and unnecessary training spend. For Dream Labs, cleaner submitted datasets and fewer confusing outcomes **could** reduce support work and improve continued use of FaaS. Those Dream Labs business effects are hypotheses; we have not measured support cost, retention, total spend, or time saved. A coach that correctly advises *not* to train may reduce short-term job volume while improving user trust.

## The pain points this addresses

The primary fit is **reliability** (repeatable task-level before/after evaluation, model warm-up handling) and **knowing why a run failed** (logs, demo findings, failure-stage labels, timing, safety and completion evidence). Camera checks flag missing, stale, dark, or frozen feeds but cannot prove that the model interpreted the image correctly. The current product does not implement a tested safe response to a mid-task credit limit. Dream Labs' simulator made this hardware-free experiment possible; the coach has not solved general demonstration recording without a robot.

The observed 4/4 versus 0/4 is four paired **simulation** scenes sampled from the training placement range. It is evidence that this checkpoint works on those scenes with the corrected evaluation. It does not establish a precise success rate, out-of-distribution performance, physical robot safety, or a quantified cost reduction.
