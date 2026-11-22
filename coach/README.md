# DreamCoach

A local companion for the [Dream Labs public library](../dream_library/README.md). It checks the robot station, reviews saved rollouts and demonstrations, submits a Dream FaaS job, and guides a paired before/after evaluation. Robot runs and paid fine-tuning require explicit operator actions.

**Start here** opens a conversational AI coach. It introduces the goal, checks Dream access, asks one question at a time about your task and hardware, reads the current local workflow state, and points you to the next action. The evaluation sidebar refreshes the latest saved comparison every five seconds. It shows the active task’s results when available. When it has enough task detail, it proposes a task that you explicitly confirm before saving. It can guide account setup, preflight, baseline trials, demonstrations, FaaS, and held-out evaluation. It does not itself start a robot or paid job. To connect Dream, sign in at the platform's [API keys page](https://platform.dreamlabs.ai/api-keys), create a key, and enter it in the masked field inside the chat. The public Dream library documents this key flow, but provides no OAuth authorization flow or API for our coach to create keys on the user's behalf. The backend validates the key with the Dream SDK and writes it to the SDK credentials file (`DREAM_CREDENTIALS` or `~/.dreamlabs/credentials`), never browser storage or conversation text. A `DREAM_API_KEY` environment variable overrides that file; remove the override and restart before using the connect field. The key file is local plaintext, with owner-only file mode requested when written; protect your OS account and do not commit it.

The coach first introduces itself and waits for **Begin**. After Begin, it checks live Dream API access from the local server. This is separate from a browser login: an incognito browser on the same computer still reaches the same local server and its configured key. The coach never claims to know whether the browser is signed in to Dream's website. When API access is ready, the read-only `/api/account/workspace` route lists the account's datasets, fine-tuning jobs, and models through the public SDK; these summaries help the agent recognize existing jobs. Dream does not expose the private console's browser state or a remote "task" resource through this SDK. The chat panel uses Dream Labs' Walla font and sunrise landscape assets for this local demo; confirm brand asset rights before distributing a public build.

For the bundled YAM apple pickup task, start in chat with **Use the YAM simulator**. DreamCoach can prepare the local environment, import the 24 bundled demos, or run Dream-1 on fresh scenes and record verified corrective demos for failures. **Review demos** opens the camera clips in chat. After review, **Open fine-tuning** validates the dataset and lets you explicitly approve a paid FaaS job. Once the checkpoint is ready, you can compare both models on reserved scenes and view paired counts in the sidebar. The [failure-conditioned collection guide](experiments/yam_sim_faas/FAILURE_CONDITIONED_SIM.md) also lists the terminal commands.

**Build a scene** and **Fruit correction** stay in the conversation panel through task approval, preview, recording, and review of the new demo. **Begin** stops any active simulator run, clears its remembered status, and opens a fresh conversation. Saved demos and evidence stay available for deliberate review.

To reuse a 500-step checkpoint, connect the Dream account with access to it and choose **Apple pickup → Evaluate existing checkpoint**. Select the checkpoint by its training dataset, then click **Run simulator comparison**. DreamCoach runs both models on four fresh paired simulator scenes. This may use inference credits. **Quit run** stops the active rollout and preserves completed evidence. To inspect the saved result with zero Dream calls, open **Statistical audit → Analyze independent 500-step apple demo**.

The chat requires an OpenAI API key, separate from the Dream key. This is an operator setting, absent from the beginner UI. Set `OPENAI_API_KEY` on the coach server or provision the key once through the local `POST /api/assistant/connect` endpoint. On Windows, this endpoint validates the key and stores it encrypted with the current user's DPAPI credential store at `~/.dreamlabs/coach-ai-key.dpapi`, so the coach starts after a server restart. On other systems, use the environment variable. The AI sees your chat messages and a compact account/task/progress snapshot; Dream credentials, rollouts, and videos are excluded. The frontend blocks recognized API keys in ordinary chat. Conversation text is retained in this browser tab's session storage so you can leave for another screen and come back. If the AI key is absent, the chat reports that the server is unconfigured rather than presenting fixed guidance as an agent. The older `/api/assistant/ask` helper remains available for compatibility.

See [why this coach matters](WHY_THIS_COACH.md) for the operator decision loop, the measured apple checkpoint comparison, and the limits of the time and cost claims.

The [repair-first path](REPAIR_FIRST.md) compares a prompt or setup change on matched diagnostic scenes before a paid fine-tune. It recommends keeping the cheap fix only when the frozen gain bound clears and all planned outcomes are reviewed.

The [Statistical audit](STATISTICAL_AUDIT.md) adds the separate evaluator from the team's `codex/stat-eval-implementation` branch for prospective independent real-world trials. It does not replace the paired Evaluation tab or reclassify simulator rollouts as independent robot evidence.

The [matched-scene evidence path](PAIRED_EVIDENCE.md) adds the authoritative paired audit and a one-click replay of the measured 500-step apple comparison. Simulator outcomes remain descriptive; eligible physical pairs use a separate conservative interval. The [coach-effectiveness benchmark](benchmark/README.md) is a prospective study template; its included results are synthetic, not evidence of savings.

The [measured closed-loop repair study](experiments/yam_sim_faas/CLOSED_LOOP_REPAIR_STUDY.md) tests the unchanged checkpoint under the original and corrected evaluation horizons. A fresh same-trajectory confirmation found 14/19 valid scenes passed by request nine and 19/19 by request twelve; one of twenty attempts was invalid and retained. **Coach effect** displays both observed simulator results separately from its synthetic operator study. These measurements establish an evaluation decision problem, not saved operator time, demonstrations, or FaaS dollars.

For the apple experiment, use the [two-account training handoff and verified datasets](experiments/yam_sim_faas/grasp_training/README.md).

For robot-free collection targeted at fresh model failures, use [failure-conditioned YAM demonstrations](experiments/yam_sim_faas/FAILURE_CONDITIONED_SIM.md). Its local collector writes reviewable LeRobot episodes into the coach Demos folder and refuses the reserved evaluation seeds. It has not yet been compared with random collection under equal FaaS budget.

**Explain comparison results** shows each model’s run diagnosis, recorded evidence, and suggested correction. DreamCoach can analyze saved traces locally without starting another model run.

## Offline apple pickup walkthrough

From `coach/`, run the isolated, local-only walkthrough on Linux with EGL available. It creates one fresh workspace, tagged scripted fixtures and a dedicated Offline review page. The server disables Dream, station, training, evaluation and deployment operations; it needs no API key or worker.

```bash
uv sync --locked --group dev --extra sim
(cd frontend && npm ci && npm run build)
MUJOCO_GL=egl uv run --locked --extra sim teach-task-coach offline-demo --directory "$(mktemp -d)/apple" --port 8765
```

Open the local URL printed by the command. Inspect the matched fixture videos, review separate human labels, and examine the scripted reference. All displayed outcomes are fixture-only, not Dream-1 or robot evidence. Do not point the regular `serve` command or live training workflow at the offline workspace.

The standalone statistical evaluator is separate and does not validate the Coach's paired simulator comparisons.

## Run locally

From `coach/`:

```bash
uv sync --group dev
uv run teach-task-coach preflight
uv run teach-task-coach serve
```

For the web UI during development, run in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite. The frontend proxies `/api` to `127.0.0.1:8765`.

For one local web server, run `npm run build` in `frontend/` and open `http://127.0.0.1:8765` after starting `teach-task-coach serve`. The local server starts the dataset and FaaS status worker automatically. Use `teach-task-coach serve --no-worker` if you run `teach-task-coach worker` separately. Only one worker can run against a data directory.

The coach connects to the Dream station at `http://127.0.0.1:8091` by default. Set `COACH_STATION_URL` if the station uses another local address. The Dream client uses its normal `DREAM_API_KEY`, `DREAM_CREDENTIALS`, or `~/.dreamlabs/credentials` configuration; no credential is stored in this repo.

Set `COACH_ROLLOUTS_DIR` to the station's rollout directory if it differs from `~/.dreamlabs/rollouts`. Enable `rollouts: {enabled: true}` in the station configuration to save local episodes. The coach stores tasks, trials, labels, dataset copies, and jobs in its user data directory (`%LOCALAPPDATA%/TeachTaskCoach` on Windows or `~/.local/share/teach-task-coach` on Linux). Set `COACH_DATA_DIR` to use another location. The rollout files themselves are read only.

The **Tasks** screen now creates a task and supervised baseline trials. The operator sets up a marked 3×3 start grid, confirms before robot motion, stops the run, syncs its saved rollout, and labels the result. If recording failed, a stopped trial can be abandoned with a reason. Do not leave a robot run unattended.

The **Demos** screen watches `COACH_DEMOS_DIR` every 15 seconds while open. An external recorder should save each completed demonstration as its own LeRobot v2.1 or v3 session folder, with task text matching the task's robot instruction exactly. The coach checks structural metadata, action rows, missing video files, and idle action at the start; the operator reviews the video, labels its grid cell, and chooses Keep or Redo. Camera occlusion and motion smoothness are not scored yet. The coverage map prioritizes cells where baseline failures are observed and accepted demos are scarce. It is a collection aid, not a guarantee of improvement.

`COACH_DEMOS_DIR` defaults to a `demos` folder under the coach data directory. Stop the Dream station before the external teleop recorder takes control of the same arms. The in-app SO-101 launcher takes the station's `arms.lock` file before starting LeRobot. By default it uses `DREAMCLI_HOME/arms.lock` (or `~/.dreamlabs/arms.lock`); set `COACH_ARMS_LOCK` if the station was started with a different lock path. The operator can stop an active recording from the Demos screen; the lock remains held until LeRobot exits. A failed recording shows the last 4 KB of its own log. On Linux, the recorder child keeps the arm lock even if the coach API exits. On Windows, the coach holds the lock while it runs; after an API crash, check the recorder process and serial ports before starting another recording. A remote station URL is refused by the in-app launcher because a local lock cannot protect remote arms.

The **Training** screen freezes all kept, structurally valid demos into a new dataset version. The worker fetches the registered embodiment, runs Dream's local dataset validator, uploads only after an explicit training submission, waits for processing, submits one FaaS job, and polls for its checkpoint. Dataset names and job suffixes are unique and reused during restart reconciliation. The screen shows the current remote dataset state while processing and Dream's queued or running state after submission. If Dream dataset processing fails before a remote training job exists, use **Retry dataset processing**; it retries the same uploaded dataset without sending the archive again. An unexpected dataset state fails with an explanation rather than polling indefinitely. Training is charged by Dream Labs; the app does not know your account's per-step price. No API key is written to the repository or browser.

For an incremental track, start with 500 steps and a constant learning-rate schedule. After a completed paired evaluation shows a positive but inconclusive gain, Training offers another 500-step job with `resume_from`. The API requires the parent checkpoint to be complete and the schedule, embodiment, `base_share`, and EEF setting to match; it refuses a duplicate continuation. The default 1,000-step cosine pilot cannot be resumed. Every continuation remains a separate explicit paid submission.

The **Evaluation** screen takes a completed fine-tune and freezes 1–512 held-out scene pairs. Tasks start with 30 reserved positions; the manifest extends deterministically when a larger evaluation is planned. A conservative planner estimates the number of pairs that would clear the useful-gain margin **if the assumed gain is observed**; it is not a power guarantee or price quote. Each pair runs baseline and candidate in randomized, approximately balanced order. The operator confirms every Start, resets the scene, and labels each rollout against the task’s success rule, with reviewer name, interventions, and optional first-response time. Incomplete rollouts remain visible and cannot be counted as usable successes.

The paired audit is the **only** promotion verdict. It needs the complete frozen pair budget, reviewed outcomes, held-out and reset attestations, recorded rollout metadata, and no excess candidate safety stops. It uses a conservative two-sided Hoeffding bound on candidate-minus-base pair differences. The report also shows run duration, interventions, and first response as descriptive secondary metrics. The audit saves an evidence snapshot and checksum; changed labels or rollout metadata invalidate the verdict until another audit. Promotion requires an explicit operator action after an improved audit. Automatic promotion is disabled, including for older comparisons that stored that setting. Rollback restores the original checkpoint. Neither action starts robot motion or edits the station’s config file. An inconclusive result is not proof of equality. A comparison with an abandoned run stays in the record and can be restarted.

Task positions are fractions of a marked tabletop, not camera-calibrated robot coordinates. The operator must prepare and reset each scene manually. Older tasks can have their reserved scene manifest extended when a comparison is planned.

If the station saves a `ModelReady` rollout while the model warms, syncing the trial preserves that rollout in its warm-up history and returns the trial to Planned. Start the same trial again once the station is idle; the warm-up does not enter the before/after result.

The public station does not provide teleoperation for every driver, so this coach imports demonstrations from LeRobot. Demo intake samples the first 300 video frames for darkness, low texture, and three seconds of identical frames; it also reviews stationary action share and jumps against typical motion. These are soft findings that need operator judgment. The Dream API and physical station need real credentials and hardware for an end-to-end test; the automated suite uses fakes for those boundaries.

The API binds to `127.0.0.1`. Browser write requests with an Origin outside local HTTP are rejected. Command-line clients without an Origin header can still use the API.

The **Guide** screen derives the next action from labelled baseline runs, station faults, demo decisions, dataset validation, FaaS job status, and evaluation results. It recommends an initial pilot once every observed failure cell has a kept valid demonstration. This is a coverage stopping rule, not an optimal demo count or success prediction. The suggested first FaaS recipe is the documented default and remains editable.

For a hardware-free run, follow the [simulator setup and one-request pilot](experiments/yam_sim_faas/PILOT.md).

The [YAM simulation FaaS experiment](experiments/yam_sim_faas/README.md) began as a format and integration test with reproducible simulated robot recordings, a validated LeRobot dataset, and a base-model rollout. The later [held-out comparison](experiments/yam_sim_faas/grasp_training/EXTENDED_500_STEP_EVAL.md) measured task improvement for the 500-step checkpoint in simulation; it is not physical robot evidence.

The **Demos** screen can launch a single local SO-101 follower/leader recording with `lerobot-record` when LeRobot is installed on the robot computer. Configure the follower and leader serial ports and camera index in that screen. Stop the Dream station process first: the station holds the follower arms even while idle. The recorder saves one 30-second session under `COACH_DEMOS_DIR` with Hub upload disabled; after it exits, the scanner imports the result for review. This launcher has only been tested with a fake process, not physical arms. See [LeRobot's SO-101 recording guide](https://huggingface.co/docs/lerobot/main/en/il_robots) for calibration and wiring.

`teach-task-coach audit-rollout PATH` compares finalized `action` rows with raw chunk replies using the recorded chunk/row indices, reports the differing share, and derives execution staleness from `executed_since_obs`. It is read-only and handles discarded replies. A raw reply does not preserve the exact camera window sent at that inference; this audit does not rewrite or upload training labels.

`teach-task-coach audit-rollouts ROOT` runs the same read-only check across every finalized rollout folder under `ROOT`, reporting processed, partial, and failed counts plus aggregate aligned rows. It notes an `INCOMPLETE.txt` folder without a finalized `rollout.json` and gives repeatable output for unchanged inputs.

The Guide groups labelled baseline runs into station/recording issues and operator-confirmed task failures without logged station faults. It shows human-labelled failure stages and evidence for each category. These are conservative triage suggestions; they do not infer a physical root cause from a video.

For a finalized rollout with `observation.state`, diagnosis also checks whether any state moved more than 0.02 from the first row. A failed run that never moved is marked as an initiation issue. This is a log-based screen, not a query of a checkpoint on new rest-pose observations.

The Guide also scores overlapping saved action chunks offline. It skips discarded replies and uses `executed_since_obs` for alignment. With at least 10 scored successful runs, it shows an empirical 95th-percentile threshold and counts alerts against human outcome labels. This is a screening signal, not an automatically validated false-alarm bound or a live robot stop.

For automated held-out scene placement, set `COACH_SCENE_ADAPTER_URL` to a local fixture service. On `POST /place`, it receives `{task_id, scene_index, start_cell, x_fraction, y_fraction, angle_deg}` and must respond with `{placed: true, detail: "..."}` only after physically placing and checking the object. The coach calls the fixture before each evaluation Start; the Evaluation screen also exposes a separate Place scene button. This repo does not contain a driver for a specific feeder or gantry; the adapter boundary is tested, but physical placement needs that hardware and its controller.

## Checks

```bash
uv run python -m pytest
uv run ruff check src tests
cd frontend && npm run build
```
