# Independent 24-demo FaaS run

Last checked: 22 November 2026. This is the second account's batch; no examples from the first account's `varied.zip` were included.

| Field | Value |
|---|---|
| Training scenes | Seeds 201–224, wrist-visible start, varied approach |
| Archive | `independent.zip` |
| Archive SHA-256 | `779f088ac959f21dcd4b50d3947912442b7e9ef950efe862d18808bdd2c64212` |
| Local Dream validation | 24 episodes, 3,961 rows, 10 Hz |
| Dream account | `mary.m.koryakina` |
| Processed dataset | `mary.m.koryakina/apple-grasp-independent-779f088ac959` |
| Dataset ID | `ds_dfb867a59247e07d` |
| Job ID | `ftj_94b20f291e71d600` |
| Suffix | `apple-independent24-500` |
| Submitted recipe | 500 steps, constant schedule, base share 0.5, EEF off, default learning rate, start from base |
| Last observed job status | `succeeded` (read-only Dream API check on 22 November 2026) |
| Checkpoint | `dream-1-ft:f2cc8d90-apple-independent24-500` |

The server's completed job record confirmed 500 steps, constant schedule, EEF off, and the published checkpoint. It reported that the job was charged $100. The job should not be duplicated. The [fresh held-out paired evaluation](SECOND_ACCOUNT_500_STEP_EVAL.md) tested this checkpoint against the base model with the coach extension.

The first account's separate 24-demo dataset and job are managed by its owner. Compare both eventual checkpoints on held-out seeds 901–904 with matched settings; neither training batch contains those scenes.
