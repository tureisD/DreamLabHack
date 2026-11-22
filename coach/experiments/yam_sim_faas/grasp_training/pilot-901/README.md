# Scene 901 apple-grasp pilot · 22 November 2026

The 24-demo checkpoint reached the apple, closed its left gripper and lifted the apple **1.68 cm**. Both fingertips still touched the apple when the recording ended. The success rule requires an unsupported lift of at least **8 cm for two continuous seconds**. The request cap ended this attempt after **14.4 of the planned 20 seconds** of model control. Both attempts are partial and have no human outcome label. A full-budget comparison against the base model is still open. [Checkpoint and training job](../varied-checkpoint.json) · [Frozen initial scene](../held_out/fdcaa8476c5a27b58ca25817607b96bd9426188afae21113590769764284aa57.json)

### Review the recording

Open either the overhead or left wrist MP4 and skip to **13.70 s**. Times below are measured from the start of the video, including the 1.65-second camera warm-up. GitHub’s **Download raw file** button retrieves the original MP4. [Overhead](attempt-2/videos/chunk-000/observation.images.overhead/episode_000000.mp4) · [Left wrist](attempt-2/videos/chunk-000/observation.images.wrist_l/episode_000000.mp4) · [Right wrist](attempt-2/videos/chunk-000/observation.images.wrist_r/episode_000000.mp4)

| Video time | Simulator observation |
|---|---|
| 13.70 s | Both left fingertips first contacted the apple while it still had table support. |
| 14.70 s | Both fingertips remained in contact and the apple was clear of the table. |
| 16.00 s | Final frame. The apple was 1.68 cm above its settled height, still rising and held between both fingertips. |

The contact trace records all 321 frames at 20 Hz. The left fingertip mask is 3 for the final 47 frames, indicating contact on both sides of the gripper. The height column is in metres. [Frame-by-frame contact and height](attempt-2/apple-evidence-v1.csv) · [Commanded actions and observed joints](attempt-2/data/chunk-000/episode_000000.parquet)

### Request accounting and controls

| Run | Dream requests | What happened |
|---|---:|---|
| [First attempt](attempt-1/rollout.json) | 3 | Two cold-start responses, then one valid 48-row reply. The recorder rejected its flat gripper array before moving the arm. The corrected adapter replayed all 48 rows offline. |
| [Replacement attempt](attempt-2/rollout.json) | 6 | Six replies drove 288 control rows. The run ended at the request cap. Its partial status and original evidence are preserved. |
| [Offline preflight](preflight.json) | 0 | Across seeds 901–904, each pair of base and candidate warm-ups produced identical decoded camera images and recorded state/action rows. |
| [Scripted positive control on seed 41](scripted-control/apple-evidence-v1.csv) | 0 | The same scorer measured a 14.5 cm peak lift and a 3.4-second qualifying hold. |

The Coach and simulator test run passed all 93 tests, and the Coach frontend built successfully. The next evaluation needs matched full-budget trials and operator review. Preserve these two shortened attempts when reporting the results. [Evaluation protocol](../README.md#compare-the-results)
