# Scene 901 · 20-second apple pickup

The 24-demo, 500-step checkpoint picked up the apple and kept it up through the final frame. The base model also lifted the apple, peaked at 7.91 cm, and returned it to its settled height before the recording ended. Both models received the instruction “pick up the apple” from the same frozen simulator state. [Watch the synchronized overhead and left-wrist recording](comparison.mp4)

| Measured over 20 seconds of model control | Dream-1 base | 24-demo fine-tune |
|---|---:|---:|
| First fingertip contact after control started | 12.85 s | 11.00 s |
| Frames with both fingertips of one hand on the apple | 55 / 400 | 174 / 400 |
| Peak lift above settled height | 7.91 cm | 9.69 cm |
| Best height sustained in an unsupported two-finger grasp for 2 seconds | 0.65 cm | 8.25 cm |
| Longest continuous unsupported two-finger hold at or above 8 cm | 0.00 s | 2.05 s |
| Pickup under the frozen rule | Fail | Pass |

The recording starts with 1.65 seconds of camera warm-up. In the video, the base reaches its peak at **18.45 s**. The fine-tune completes its first qualifying two-second hold at **21.55 s**, or 19.90 seconds into model control. Coach scores the recorded height and fingertip contact at 20 Hz. A two-second hold requires 41 consecutive samples with both fingertips of the same hand on the apple and no other support. [Base trace](base/apple-evidence-v1.csv) · [Fine-tune trace](candidate/apple-evidence-v1.csv)

## Reproduce the comparison

The candidate ran first, followed by the base. Each recording contains 33 warm-up rows and exactly 400 model rows. Warm-up actions, warm-up joint observations, and the joint observation before the first model action matched exactly. Each checkpoint returned nine action chunks. The candidate also received ten server warm-up refusals before its first chunk. Each set of three original videos decodes to 433 frames per view. [Frozen scene and rule](../held_out/fdcaa8476c5a27b58ca25817607b96bd9426188afae21113590769764284aa57.json) · [Base metadata](base/rollout.json) · [Fine-tune metadata](candidate/rollout.json)

| Checkpoint | Original rollout directory |
|---|---|
| `dreamlabs/dream-1-beta` | `yam-fb1f4aa02bc04815ad401b9cb8a7be30` |
| `dream-1-ft:7820aef9-apple-varied24-500` | `yam-10586318725f4b34bba816d0ff2d34b4` |

Load the snapshot using **Load JSON file** in Coach’s statistical audit to reproduce the paired report without calling Dream. The plan timestamp refers to the commit publishing the frozen scene. The paired audit accepted both recordings and classified the result as descriptive. Outcomes come from simulator measurements and await human review. [Audit input](paired-snapshot.json) · [Audit output](paired-report.json)

Scene 901 had already been piloted and is held out from training. These are two fresh attempts. The earlier 14.4-second recordings ended at a request cap. A separate predeclared evaluation across scenes 905–908 used 28.8 seconds of model control and reported four passes for the fine-tune and zero for the base under its recorded-height rule. The experiments support better simulated apple pickup in these setups. Physical performance remains unmeasured. [Earlier pilot](../pilot-901/README.md) · [Four-scene evaluation](../EXTENDED_500_STEP_EVAL.md)
