# Corrected 500-step checkpoint simulator evaluation

Run on 22 November 2026 with the same Dream account and checkpoints as [the first comparison](HELDOUT_500_STEP_EVAL.md). No new FaaS job or dataset was submitted. The source of improvement here is the **evaluation and execution pipeline**, not a change to the 500-step checkpoint's weights.

## Why the first result was 1/4 versus 0/4

- The original nine-request cap ended every complete fine-tune run at 23.25 seconds, while the apple was still rising. The first gripper close happened 12.0, 12.75, and 16.35 seconds after warm-up on seeds 901–903; their highest apple position was the final recorded frame. The 24-demo, 500-step checkpoint should therefore be evaluated with a longer, task-level horizon.
- Seed 904 stopped before its fourth response was executed because a predicted normalized gripper value was `1.052775`. The previous validator rejected overshoot greater than `0.05`; the excess over that tolerance was only `0.002775`. Small finite gripper overshoots now clamp to the physical 0–1 range, while gross violations still stop the run.
- The base model did poorly for a different reason. In the longer paired runs, it began closing its gripper only 0.6–1.6 seconds after warm-up, typically before reaching the apple. The fine-tune began closing after roughly 10–12 seconds in the fresh runs.
- The 10 Hz training export versus 20 Hz action playback was investigated but not changed. Slowing playback would further delay a grasp that was already late. The official client uses `action_hz` for the loop's action-row rate; this experiment does not establish a training-rate defect.

The corrected trials use 12 requests of 48 rows at 20 Hz plus 33 warm-up rows: 609 steps, 30.45 seconds. Score-only rollouts keep the full action and joint-state trace and directly record apple height every step. Exact action replay checks the joint trace within 5 mm. Videos remain available in the normal recorder mode.

## Exploratory reruns of the original scenes

These seeds informed the fixes, so the following are descriptive reruns, not confirmation. All four fine-tune runs succeeded and all four base runs failed under the longer budget. Held lift is the best two-second minimum above the settled apple height; success requires at least 8 cm.

| Seed | Base held lift | Fine-tune held lift | Base run | Fine-tune run |
| --- | ---: | ---: | --- | --- |
| 901 | <0.1 cm | 16.7 cm | `yam-616f3ff857314c5bb345779524df1997` | `yam-89080b24a5a24182a5c45ade660ce43c` |
| 902 | <0.1 cm | 10.9 cm | `yam-95432e59f1104ec58310b6c2b02a946d` | `yam-0a95ad9cad0847e598ef9dfa4faf0df9` |
| 903 | <0.1 cm | 10.1 cm | `yam-b6f8e24f033040afbb6691fa95ae52a8` | `yam-ed7070a58a714cbe942737eaaf7ac439` |
| 904 | <0.1 cm | 16.9 cm | `yam-099ee5a4df5d450587ffb9ab847a87ec` | `yam-777b9def7e0d4b8c80b779bcc0517c6b` |

An additional video-backed rerun of 904 (`yam-410c37e438614fc485427c45d1e27ec0`) completed after the gripper fix, but its reconstructed joint trace briefly differed from recording by 3.8 mm and failed the old 2 mm replay limit. It was not substituted for the direct-height score-only run above.

## Fresh predeclared confirmation

The [protocol](CONFIRMATION_PROTOCOL.md) fixed seeds 905–908, model order, horizon, success rule, and treatment of partial runs before these API calls. Each scene was reset identically for both checkpoints. All eight trials completed with 576 model rows; all replay errors were below 0.3 mm.

| Seed | Base held lift | Base | Fine-tune held lift | Fine-tune | Base run | Fine-tune run |
| --- | ---: | --- | ---: | --- | --- | --- |
| 905 | 0.6 cm | Fail | 16.6 cm | Pass | `yam-44fe8c6519ce462db554368b8c2a2cfb` | `yam-14a305b9f558424d8fe01e32358d89c2` |
| 906 | <0.1 cm | Fail | 15.7 cm | Pass | `yam-8e1657a3fa494cba999600ee8ce3b80c` | `yam-ebf154883ef546ca9e26dfb530c56c65` |
| 907 | <0.1 cm | Fail | 15.7 cm | Pass | `yam-3f669cf8fec8436b8c7e248cab7f9c48` | `yam-ef09816c6ff04516aac271be192cdf38` |
| 908 | <0.1 cm | Fail | 14.8 cm | Pass | `yam-230a77db8f254f2cbe4abf5a001f1713` | `yam-c556ca8cfcb2466ea3612f74219090d7` |

**Descriptive result: fine-tune 4/4, base 0/4.** On seed 905, the base briefly peaked at 8.5 cm but dropped the apple; its two-second held lift was only 0.6 cm. This is why scoring peak height alone would mislabel a failure.

The model still needs validation outside the training distribution. Training and these held-out seeds all sample apple placement from the same narrow simulator range, and the checkpoint has not been tested on a physical robot, other objects, altered cameras, or start poses. Four paired scenes do not establish a precise success probability. Before paying for another fine-tune, use the coach to collect failures in harder scenes, label their stage, record targeted human demonstrations, then compare a new checkpoint on newly reserved scenes.

The complete score-only rollouts are local under `%LOCALAPPDATA%/TeachTaskCoach/sim-rollouts/<run ID>` and are not in GitHub. Two attempted calls using the unqualified `dream-1-beta` ID returned `not_entitled` with no model actions; they are excluded from the paired tables. The simulator now maps that common shorthand to `dreamlabs/dream-1-beta`.
