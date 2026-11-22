# dima24kor archived dataset: local coach pipeline audit

Checked on 22 November 2026 against the committed `varied.zip` and `varied.json` files. This is an offline check of the first account's training archive, not a fresh download from the Dream account or an evaluation of a trained checkpoint.

| Stage | Result |
| --- | --- |
| Archive digest and frozen split | SHA-256 `3374a5388381b2e67d810a6692228370f8ca27124df1ee1342c8a572df4f08af`; seeds 41–48 and 101–116; held-out seeds 901–904 excluded |
| Dream SDK local format validation | Passed: 24 episodes, 3,871 rows, 10 Hz |
| Coach demo import and lint | 24 imported, 24 structurally valid; 24 `frozen_camera` review findings |
| Coach dataset freeze and validation | Passed in a disposable test workspace after marking all 24 demos Keep for the test only; 24 sessions, 24 episodes, 3,871 frames |

The `frozen_camera` warnings are on the right wrist view. In seed 41, sampled frames 1–12 seconds repeat exactly while the other two camera streams change. That may reflect a parked right arm or a stale feed; the recorded video needs human review. No episode was accepted in a persistent coach database.

The first lint run also reported `abrupt_action` on all 24 episodes because the binary gripper close looked large beside small joint steps. The linter now excludes action dimensions named `grip` from the joint jerk check. Rerunning the same archive leaves only the camera review findings.

No remote dataset or job status was queried. This machine has no dima24kor Dream credential configured, and the repo has no first-account job or checkpoint ID. No dataset was uploaded, paid fine-tune submitted, model queried, or robot run started during this audit. The remaining live pipeline requires read-only access to that account's job and checkpoint, then held-out evaluations under the protocol in `README.md`.
