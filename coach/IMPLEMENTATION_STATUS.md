# Dream-FDE Studio plan: implementation status

The source plan is `dream-fde-studio-plan.md` supplied by the user. This file distinguishes implemented code from results that require robot data, Dream credentials, or a license.

| Plan item | Current implementation | Remaining evidence or work |
| --- | --- | --- |
| A1 raw versus commanded actions | Read-only alignment audit from parquet chunk/row columns, raw replies, and inference log; aggregate difference and staleness | Exact observation window sent with each reply is not in the saved rollout, so training pairs are **not** rewritten or uploaded |
| A2 successful data only | FaaS datasets contain operator-kept LeRobot demonstrations; failed rollouts are not added automatically | Human corrections and safe rollout selection need real data |
| A3 idle trimming | Idle lead-in is flagged in demo review | No video/parquet rewrite or A/B job yet |
| A4 quality lint | Dream's local format validator, video darkness/freeze, stationary action share, abrupt actions, missing camera/action checks | Duplicate-content detection, cross-demo outlier analysis and precision-phase measures remain |
| A5 incremental FaaS | Optional 500-step constant-schedule continuation with `resume_from`, matching-setting checks, evaluation gate, and duplicate protection | No real paid continuation has been run here |
| A6–A7 robustness/demo | Deterministic read-only `audit-rollouts` command handles finalized, partial and incomplete folders | Run on a real rollout collection and time the stage demo |
| B real-trial verdict | Predeclared paired held-out trials, bootstrap interval, exact McNemar test, safety gate | STEP code is noncommercial-licensed; commercial permission or a separately licensed implementation is needed before integration |
| B offline screening | Recorded-run initiation check | Exact rest-pose model probe and critical-interval checkpoint metric need queryable observations and checkpoint access |
| C diagnosis | Evidence-linked station/setup versus confirmed task-failure categories and failure-stage counts | Hand-label at least 50 real runs and measure agreement |
| D early warning | Offline overlap score on saved installed chunks, with empirical threshold from at least 10 successful runs | No validated false-alarm rate or live `on_round_trip` alarm; never stops a robot run automatically |

No paid Dream job was queued from the source plan's schedule instructions. The local environment has not provided a reachable robot station or Dream credentials for an end-to-end hardware/API run.
