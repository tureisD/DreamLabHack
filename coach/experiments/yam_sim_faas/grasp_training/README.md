# Two-account apple grasp training handoff

The main experiment asks whether a Dream checkpoint can lift the simulated apple after learning from demonstrations with different reach distances and speeds. The earlier base checkpoint approached the apple but closed early. All eight examples from the first batch closed at 7.55 seconds. Each new recording varies the apple position, approach height, approach duration and descent duration, with an open gripper until the grasp.

## Pick the account roles before spending

| PC | Dataset and purpose | Job suffix |
| --- | --- | --- |
| This PC, current Dream user dima24kor | Primary candidate. The varied batch includes the first eight demonstrations and sixteen new ones. | apple-varied24-500 |
| Other PC, second Dream user | Optional control. The original eight fixed-timing demonstrations. It can train alongside the primary job. | apple-control8-500 |

Start from Dream's base model on both accounts. Both runs use 500 steps, a cosine schedule, 50% Dream data, joint targets, and the default learning rate. Results measure the combined effect of adding examples and varying the approach. The design cannot isolate either effect individually.

At the published price of $0.20 per step, each 500-step run needs $100 **available on its own account**. Confirm today's quote in the Fine-tune form and the available balance in Billing. A quoted $100 job on a $99.99 balance cannot start. Queuing holds the price and the SDK documents cancellation as unavailable for priced jobs. Inference is separately billed. If the team has exactly $100 on each account, spending both balances on training can leave no credit to test the checkpoints. Prioritize one varied run on whichever account can cover it and retain inference credit. The second account can run base trials; private fine-tunes require access and inference credit for the caller. Confirm that access before committing both balances. Dream restricts continuation to the checkpoint owner.

## Start on the other PC

1. Use a fresh clone, or pull the named branch in an existing clean checkout. Install Git, uv, and Python 3.11 or 3.12 if needed. Run from PowerShell:

   ~~~powershell
   git clone --branch codex/teach-task-coach --single-branch https://github.com/tureisD/DreamLabHack.git DreamLabHack-training
   cd DreamLabHack-training/coach
   uv sync --locked
   $tool = './experiments/yam_sim_faas/grasp_training/batch.py'
   uv run --locked python $tool verify control
   ~~~

2. Sign into the second account on the Dream platform. Record its Dream username. In a new terminal without an existing DREAM_API_KEY, the next command prompts for a masked key. Substitute the actual username. Keep the credential on that PC. The helper verifies the archive hash, split and SDK report, registers or reuses the YAM configuration, uploads to this account, and polls for processing. Rerunning it after processing reuses the dataset under its content-derived name.

   ~~~powershell
   uv run --locked python $tool prepare control --account YOUR_DREAM_USERNAME
   ~~~

   To prioritize the varied candidate on this PC instead, run both commands with **varied**. Coordinate roles so exactly one PC owns each planned job. The varied archive and its manifest arrive in the second data commit; use git pull --ff-only on this branch if needed.

3. Open the [Dream Datasets page](https://platform.dreamlabs.ai/fine-tuning/datasets) in the same account. Select the exact **processed** dataset printed by the helper. Choose **Fine-tune**, set the job suffix from the table, set **500** steps (the default is 1,000), select **cosine**, **Mix in Dream Labs data**, joint-space training, and a fresh job. Leave learning rate at its default.

4. Check Billing, the displayed total, and existing runs for the suffix. Start the job once when the account owner approves that charge. If submission times out, check the [Runs page](https://platform.dreamlabs.ai/fine-tuning/runs) for the original job before trying again. Record the account name, dataset name and ID, suffix, job ID, actual settings and resulting checkpoint ID. After submission, training runs in Dream's cloud and the PC can be shut down. Keep keys out of chat, screenshots, and Git.

5. Report the completed checkpoint to the other PC. Reserve seeds **901–904** for evaluation. Use the same wrist-visible starting pose, task, and 20-second simulated control budget for each controller. Confirm action playback cadence for each checkpoint first. Review an unassisted lift of at least 8 cm held for two continuous seconds. Retain video and label for each run, including partials. Four matched simulated placements give a descriptive pilot; the real-trial statistical verdict requires separate eligible evidence.

## Instructions for the AI on the other PC

Work on branch **codex/teach-task-coach**. Read this file and verify the assigned archive. Prepare the dataset on the second Dream account using its own local credentials. Report the processed dataset ID and the 500-step price shown in that account. Check the team has budget to evaluate afterwards. Once the account owner authorizes the displayed charge, submit exactly one job with the listed suffix, monitor it, and return the checkpoint ID. If another account will be the sole training account, prioritize the varied batch there. Keep the four held-out scenes out of data collection.

## Reproduce the training data

The committed archives contain only the per-episode LeRobot training data. Each adjacent JSON records the seeds, original recording IDs, replay measurements, frame count, embodiment configuration and archive SHA-256. The build script rejects failed pickups, large replay discrepancies, missing contact, and duplicate eligible seeds. The eight original runs use seeds 41–48. The sixteen varied runs use seeds 101–116. From the coach directory, to recreate the recordings in a fresh folder:

~~~powershell
uv sync --locked --extra sim
$exp = './experiments/yam_sim_faas'
uv run --locked python "$exp/record_yam_demos.py" --output ./raw-apple --seed 41 --episodes 8 --start-pose wrist-visible
uv run --locked python "$exp/record_yam_demos.py" --output ./raw-apple --seed 101 --episodes 16 --start-pose wrist-visible --vary-approach
uv run --locked python "$exp/grasp_training/build_batch.py" varied --raw ./raw-apple --output ./rebuilt-batches
~~~

[Dream SDK fine-tuning reference](https://pypi.org/project/dreamlabs-client/1.1.7/#fine-tuning) · [Dream Billing](https://platform.dreamlabs.ai/billing)
