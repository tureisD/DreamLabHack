# Dima 500-step checkpoint: held-out simulator comparison

Run on 22 November 2026 with the dima24kor Dream account. Dream's API confirmed job `ftj_0b80885351caf8f7` succeeded after 500 steps on `dima24kor/apple-grasp-varied-3374a5388381` and published `dream-1-ft:7820aef9-apple-varied24-500`. No further training job was submitted.

The predeclared test seeds were 901–904; none appear in either training archive. Each checkpoint received the same prompt, wrist-visible starting pose, seed-specific apple placement, 20 Hz simulation, and at most nine productive 48-row action chunks. Runs were sequential with checkpoint order rotated by seed. A complete run has 432 executed model action rows plus 33 camera warm-up rows, for 23.25 seconds total.

Success means the unassisted apple rises at least 8 cm above its settled height and remains that high for two continuous seconds. `score_rollouts.py` replays the saved action rows in MuJoCo and rejects a score if the reconstructed joint state differs from the recording by 0.002 or more. All seven complete model runs passed this replay check. Videos and full rollouts are saved locally under `%LOCALAPPDATA%/TeachTaskCoach/sim-rollouts/<run ID>`; they are not in GitHub.

| Seed | Base run | Base peak / held lift | Base | Fine-tune run | Fine-tune peak / held lift | Fine-tune |
| --- | --- | --- | --- | --- | --- | --- |
| 901 | `yam-8df709cf33cf4774bc2edb70e424ba88` | 0.2 / 0.0 cm | Fail | `yam-d76474bd0ac54b15ae0ed435ba69fe34` | 10.3 / 9.4 cm | Pass |
| 902 | `yam-8b3bc313e0e04301b9732c54baac475d` | 0.0 / 0.0 cm | Fail | `yam-afdd7f05745043ef8851b1d03c8ec398` | 6.8 / 5.1 cm | Fail |
| 903 | `yam-50983587c17f4db99ed474ec8ac3c62c` | 0.0 / 0.0 cm | Fail | `yam-83b1524796af4e7991c2718eb179c097` | 4.6 / 1.7 cm | Fail |
| 904 | `yam-6605fc1781a24f75884e01166f9bf9b6` | 0.1 / 0.0 cm | Fail | `yam-76595a0c099c4322b33bc525edf119c9` | Incomplete after 144 action rows | Safety failure |

On seed 904 the fine-tune's fourth response included a left gripper target of 1.052775 at row 38, beyond the normalized 0–1 range and the simulator's 0.05 tolerance. The validator refused that chunk before executing it. The saved rollout is `partial`, and the attempt was not rerun or converted into a success.

**Descriptive result:** fine-tune 1/4, base 0/4. This shows one useful pickup and three fine-tune failures, including the safety stop. Four paired scenes cannot establish a reliable gain or quantify the coach's effect on model quality. The demonstrated pipeline improvement is operational: validated training data, a completed FaaS job, cold-start recovery, matched checkpoint rollouts, exact action replay, and an explicit safety failure rather than a guessed verdict. A larger predeclared evaluation and human review of the videos are needed before promoting the checkpoint.
