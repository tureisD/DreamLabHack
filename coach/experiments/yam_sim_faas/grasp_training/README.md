# Apple training on two Dream accounts

**Start here on the second PC.** This PC collects seeds 201–224 while the first PC owns a separate 24-demo dataset from seeds 41–48 and 101–116. Both PCs simulate locally without an API key or robot. The two training datasets stay independent. The first dataset mixes eight fixed-approach and sixteen varied-approach demonstrations; the second contains twenty-four varied-approach demonstrations at distinct seeded positions. Keep the same model and fine-tuning recipe on both accounts so the dataset composition is the main comparison.

## Assignments and budget

| | First PC | Second PC |
|---|---|---|
| Dream account | dima24kor, approximately $150 | Teammate's own username, approximately $160 |
| Training dataset | **varied**, 24 demos, seeds 41–48 and 101–116 | **independent**, 24 demos, seeds 201–224 only |
| Proposed suffix | apple-varied24-500 | apple-independent24-500 |
| One 500-step job at the published rate | $100, about $50 left | $100, about $60 left |
| Current assignment | Training complete. Use the published checkpoint for evaluation. | 24-demo dataset processed; one 500-step job submitted on 22 November 2026 |

## First account checkpoint

Dream published `dream-1-ft:7820aef9-apple-varied24-500` after 500 steps on the varied apple dataset. The model runs on Dream Labs. With a Dream API key that has access, pass this exact ID to the simulator recorder’s `--model` option. The checkpoint record links the hosted model to its training job and dataset manifest. [Checkpoint record](varied-checkpoint.json) · [Simulator recorder instructions](../PILOT.md)

The [held-out simulator comparison](HELDOUT_500_STEP_EVAL.md) records matched base and fine-tune runs on seeds 901–904. `score_rollouts.py` replays saved model actions to check the lift threshold and state agreement; review the videos before interpreting the result as a real task outcome.

The [corrected longer comparison](EXTENDED_500_STEP_EVAL.md) documents the 12-request score-only path and the fresh predeclared seeds 905–908. Run `record_dream_model_rollout.py` with `--score-only` to save actions, joint states, and actual simulated apple height without encoding review videos; use normal recording when human video review is needed. Score with `grasp_training/score_rollouts.py <rollout-folder>`. Do not pool the exploratory reruns of 901–904 with the fresh confirmation set.

On 22 November 2026 Dream confirmed **processed** for the first account's dataset `dima24kor/apple-grasp-varied-3374a5388381`, ID `ds_25be44f202eb5d8c`. It contains 24 episodes and 3,871 rows at 10 Hz. The 16 varied demonstrations closed at 15 distinct times between 5.45 and 8.90 seconds. Across all 24 episodes the gripper was 4.08–6.27 mm from the apple center at first closure. No paid job was submitted by the first PC during preparation. This committed archive is a comparison reference only; it is not part of the second account's training data.

All 24 archived action sequences also passed a separate 10 Hz physics replay. Every sequence held the apple at least 14.1 cm above the table for two continuous seconds and then released it. All 11,613 exported camera frames were checked against the corresponding frames in the original three camera streams. The independent batch builder runs the same exported-action replay on each new episode before packaging it.

Each proposed job starts independently from Dream's base model. Match training settings across accounts. The comparison tests two distinct 24-example collections under the same recipe; it does not isolate one data-collection variable perfectly. Report actual outcomes. The original eight-demo control remains available as a historical reference. If someone already submitted an earlier control experiment, record that job and keep the remaining credits for evaluation before considering another purchase.

The documented price is $0.20/step. Check [Billing](https://platform.dreamlabs.ai/billing) and the current quote for **500 steps** on each account. Submitting holds that job's price on the submitting account. The default 1,000-step job is about $200. Runs with the resulting models also use credits.

The second account's independent archive is committed as `independent.zip` with the matching `independent.json` manifest. It contains only seeds 201–224. Dream marked dataset `mary.m.koryakina/apple-grasp-independent-779f088ac959` (`ds_dfb867a59247e07d`) processed. One 500-step job, `ftj_94b20f291e71d600`, was accepted with suffix `apple-independent24-500`, constant schedule, base share 0.5, and EEF off. It was queued at the last check; see [the run record](SECOND_ACCOUNT_RUN.md) for the verified status and limits.

## Second PC setup and collection

Use a fresh clone or update an existing clean checkout with git pull --ff-only. On Windows, with Git, uv and Python 3.11 or 3.12 available, run:

~~~powershell
git clone --branch codex/teach-task-coach --single-branch https://github.com/tureisD/DreamLabHack.git DreamLabHack-training
cd DreamLabHack-training/coach
uv sync --locked --extra sim
$exp = './experiments/yam_sim_faas'
$g = "$exp/grasp_training"
$raw = Join-Path $env:LOCALAPPDATA 'TeachTaskCoach/sim-rollouts'
$out = Join-Path $env:LOCALAPPDATA 'TeachTaskCoach/apple-independent-v1'
uv run --locked python "$exp/record_yam_demos.py" --output "$raw" --seed 201 --episodes 24 --start-pose wrist-visible --vary-approach
~~~

Start recording as soon as this handoff is available. If interrupted, inspect the finished rollout sidecars and run only missing seeds. Every attempt gets a separate folder. The batch builder rejects duplicate eligible seeds; select one reviewed recording per seed in a separate input folder if needed. Leave held-out seeds 901–904 untouched.

After collection, build and verify only this PC's 24 new episodes:

~~~powershell
uv run --locked python "$g/batch.py" verify varied
uv run --locked python "$g/build_batch.py" independent --raw "$raw" --output "$out"
uv run --locked python "$g/batch.py" verify independent --bundle-dir "$out"
~~~

The builder audits all 24 new episodes. It checks closing distance, contact with both fingers, replay agreement, the lift/hold/release outcome and synchronized 10 Hz videos. It refuses to overwrite an existing archive. The SHA-256, episode IDs and per-scene measurements are in independent.json. Share independent.json and independent.zip on the team's branch if the other PC needs this exact dataset. Neither file contains the first account's training episodes.

## Upload on the correct account

Open a fresh terminal without a preset DREAM_API_KEY if the machine has used another account. The helper prompts for a masked key when no environment key is set. Use the Dream username shown in the platform, which can differ from the GitHub username. Keep credentials local. In the shell configured above:

~~~powershell
# Second PC
uv run --locked python "$g/batch.py" prepare independent --bundle-dir "$out" --account YOUR_DREAM_USERNAME

# First PC only, from coach, with $g set as above
uv run --locked python "$g/batch.py" prepare varied --account dima24kor
~~~

Prepare validates the archive, registers or reuses the matching YAM embodiment, uploads the dataset under its content-derived name, and polls until processed or failed. Rerun the same command to recover the status after a disconnect. If processing fails, retain the dataset ID and error; use the platform's retry operation if it identifies a transient service failure. This command finishes before any paid job submission.

## Start and monitor a paid job

1. On the account that will train, open [Datasets](https://platform.dreamlabs.ai/fine-tuning/datasets). Select the exact **processed** dataset printed by prepare. In [Runs](https://platform.dreamlabs.ai/fine-tuning/runs), check for the planned suffix before submitting.
2. In the Fine-tune form choose **500 steps**, a **constant** learning-rate schedule, **Mix in Dream Labs data** (base share 0.5), joint-space training (EEF off), default learning rate, and the suffix in the assignments table. Start from base. Constant keeps open the documented option to resume within that account.
3. Show the owner the dataset, settings and live price, and get approval for this job. Submit once. A timeout can occur after the platform received a request; check Runs before attempting another submission. Queued priced jobs cannot be cancelled through the SDK.
4. Record the account, dataset name and ID, dataset digest, job ID, settings and resulting checkpoint ID. Training continues on Dream's servers with the PC offline. Each owner can monitor their own job and run their private checkpoint.

**Continuation works on each account independently.** Once a checkpoint finishes all its steps, its owner can submit a further job with resume_from set to that checkpoint ID, using the same embodiment, constant schedule and compatible training settings. Each continuation has a minimum of 500 new steps. At today's documented rate, a further job would require about $100 on that account. With the approximate balances above, the first owner would need about another $50 and the second about another $40 after one job each, before inference spending. Recreating the same dataset and settings on a different account starts a fresh model there. Passing a teammate's checkpoint ID does not transfer its optimizer state or ownership. [Dream SDK fine-tuning reference](https://pypi.org/project/dreamlabs-client/1.1.7/#fine-tuning)

## Compare the results

Run the unmodified base and both independent 24-demo candidates on the same four held-out scenes (901–904). Match prompt, wrist-visible pose, full initial scene, and 20 seconds of simulated control after warm-up. Verify the action playback cadence for each model and record actual action rows, elapsed simulated time and incomplete attempts. Rotate controller order across scenes. Score an unassisted apple lift of at least 8 cm above settled height held for 2 continuous seconds. Keep the video and human outcome for each attempt; report descriptive counts out of four per checkpoint. Pool the **results** across PCs by scene and checkpoint ID. Never include test scenes in training. These are simulation trials; the real-trial statistical verdict has separate evidence requirements.

## Copy this to the second PC's AI

> Use branch codex/teach-task-coach. Read coach/experiments/yam_sim_faas/grasp_training/README.md. You own seeds 201–224. Collect and audit those demos locally, build and verify an independent 24-demo dataset containing only your seeds, and prepare it on my Dream account. Return its processed dataset ID and the 500-step constant-schedule quote. Check for an existing job before submission. Report the checkpoint ID and preserve the held-out scenes.
