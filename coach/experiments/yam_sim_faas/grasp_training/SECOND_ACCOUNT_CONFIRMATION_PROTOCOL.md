# Second-account 500-step checkpoint confirmation protocol

Frozen before any Dream inference call on seeds 909–912. Dream's read-only job API reported `ftj_94b20f291e71d600` succeeded after 500 steps and published `dream-1-ft:f2cc8d90-apple-independent24-500` on account `mary.m.koryakina`. The training archive contains only seeds 201–224. No further training or dataset upload is part of this evaluation.

- Scenes: deterministic YAM simulator seeds 909, 910, 911, 912. These have not been used for model selection or training.
- Controllers: `dreamlabs/dream-1-beta` and `dream-1-ft:f2cc8d90-apple-independent24-500`, queried using the second account.
- Prompt and start: `pick up the apple`, `wrist-visible`, identical seeded scene reset for each controller.
- Budget: 12 action requests of up to 48 rows, executed at 20 Hz after 33 warm-up steps. A complete run has 576 model rows and 609 simulator steps (30.45 seconds). Wall-clock ceiling: 600 seconds per run.
- Recording: `--score-only` saves action rows, joint states, and actual apple height. Exact replay must agree with saved states within 5 mm. Retain every partial run and score it as failure; do not substitute a retry.
- Success: apple rises at least 8 cm above settled height and stays there for two continuous seconds. Report held lift, peak lift, first gripper-close time, replay error, and any partial run.
- Order: candidate then base on seeds 909 and 911; base then candidate on 910 and 912.
- Interpretation: report descriptive paired counts only. Four simulator scenes cannot establish real-robot reliability or a statistical improvement verdict. They can test the completed FaaS checkpoint and the coach's simulator evidence path.
