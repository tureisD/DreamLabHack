# Teach it a task

A local companion for the [Dream Labs public library](../dream_library/README.md). It checks the robot station, reviews saved rollouts and demonstrations, submits a Dream FaaS job, and guides a paired before/after evaluation. Robot runs and paid fine-tuning require explicit operator actions.

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

For one local web server, run `npm run build` in `frontend/` and open `http://127.0.0.1:8765` after starting `teach-task-coach serve`. Once you create a dataset version, start `uv run teach-task-coach worker` in another terminal. Only one worker can run against a data directory.

The coach connects to the Dream station at `http://127.0.0.1:8091` by default. Set `COACH_STATION_URL` if the station uses another local address. The Dream client uses its normal `DREAM_API_KEY`, `DREAM_CREDENTIALS`, or `~/.dreamlabs/credentials` configuration; no credential is stored in this repo.

Set `COACH_ROLLOUTS_DIR` to the station's rollout directory if it differs from `~/.dreamlabs/rollouts`. Enable `rollouts: {enabled: true}` in the station configuration to save local episodes. The coach stores tasks, trials, labels, dataset copies, and jobs in its user data directory (`%LOCALAPPDATA%/TeachTaskCoach` on Windows or `~/.local/share/teach-task-coach` on Linux). Set `COACH_DATA_DIR` to use another location. The rollout files themselves are read only.

The **Tasks** screen now creates a task and supervised baseline trials. The operator sets up a marked 3×3 start grid, confirms before robot motion, stops the run, syncs its saved rollout, and labels the result. If recording failed, a stopped trial can be abandoned with a reason. Do not leave a robot run unattended.

The **Demos** screen watches `COACH_DEMOS_DIR` every 15 seconds while open. An external recorder should save each completed demonstration as its own LeRobot v2.1 or v3 session folder, with task text matching the task's robot instruction exactly. The coach checks structural metadata, action rows, missing video files, and idle action at the start; the operator reviews the video, labels its grid cell, and chooses Keep or Redo. Camera occlusion and motion smoothness are not scored yet. The coverage map prioritizes cells where baseline failures are observed and accepted demos are scarce. It is a collection aid, not a guarantee of improvement.

`COACH_DEMOS_DIR` defaults to a `demos` folder under the coach data directory. Stop the Dream station before the external teleop recorder takes control of the same arms. The station owns an exclusive arm lock while it is running.

The **Training** screen freezes all kept, structurally valid demos into a new dataset version. The worker fetches the registered embodiment, runs Dream's local dataset validator, uploads only after an explicit training submission, waits for processing, submits one FaaS job, and polls for its checkpoint. Dataset names and job suffixes are unique and reused during restart reconciliation. Training is charged by Dream Labs; the app does not know your account's per-step price. No API key is written to the repository or browser.

The **Evaluation** screen takes a completed fine-tune and plans 30 held-out scene pairs. These positions are generated when the task is created, before data collection. Each pair runs the baseline and candidate checkpoints on the same scene in randomized, balanced order; the operator confirms every Start, resets the scene, and labels each rollout against the task's success rule. The report shows success counts, paired gain, a bootstrap interval, an exact paired-test p-value, safety stops, and an improved/inconclusive/worse verdict. An improved verdict requires all 30 usable pairs, a gain above the threshold chosen before the comparison, positive interval, p<0.05, and no excess candidate safety stops. This protocol may be underpowered for modest gains; an inconclusive result is not proof that the model is equal. If auto promotion was selected before evaluation, an improved verdict changes the checkpoint for future coach-managed task runs. Otherwise the operator can promote it after review. Rollback restores the original checkpoint. Neither action starts robot motion or edits the station's config file. A comparison with an abandoned run stays in the record and can be restarted.

Task positions are fractions of a marked tabletop, not camera-calibrated robot coordinates. The operator must prepare and reset each scene manually. Tasks created by older coach versions lack the predeclared evaluation scenes and need to be recreated for this evaluation protocol.

If the station saves a `ModelReady` rollout while the model warms, syncing the trial preserves that rollout in its warm-up history and returns the trial to Planned. Start the same trial again once the station is idle; the warm-up does not enter the before/after result.

The public station does not provide teleoperation for every driver, so this coach currently imports demonstrations from an external LeRobot recorder. Demo intake samples the first 300 video frames for possible darkness or occlusion and compares action jumps against typical motion; both are soft review findings that need operator judgment. Autonomous scene setup and automatic deployment are outside this build. The Dream API and physical station need real credentials and hardware for an end-to-end test; the automated suite uses fakes for those boundaries.

The API binds to `127.0.0.1`. Browser write requests with an Origin outside local HTTP are rejected. Command-line clients without an Origin header can still use the API.

The **Guide** screen derives the next action from labelled baseline runs, station faults, demo decisions, dataset validation, FaaS job status, and evaluation results. It recommends an initial pilot once every observed failure cell has a kept valid demonstration. This is a coverage stopping rule, not an optimal demo count or success prediction. The suggested first FaaS recipe is the documented default and remains editable.

The **Demos** screen can launch a single local SO-101 follower/leader recording with `lerobot-record` when LeRobot is installed on the robot computer. Configure the follower and leader serial ports and camera index in that screen. Stop the Dream station process first: the station holds the follower arms even while idle. The recorder saves one 30-second session under `COACH_DEMOS_DIR` with Hub upload disabled; after it exits, the scanner imports the result for review. This launcher has only been tested with a fake process, not physical arms. See [LeRobot's SO-101 recording guide](https://huggingface.co/docs/lerobot/main/en/il_robots) for calibration and wiring.

For automated held-out scene placement, set `COACH_SCENE_ADAPTER_URL` to a local fixture service. On `POST /place`, it receives `{task_id, scene_index, start_cell, x_fraction, y_fraction, angle_deg}` and must respond with `{placed: true, detail: "..."}` only after physically placing and checking the object. The coach calls the fixture before each evaluation Start; the Evaluation screen also exposes a separate Place scene button. This repo does not contain a driver for a specific feeder or gantry; the adapter boundary is tested, but physical placement needs that hardware and its controller.

## Checks

```bash
uv run python -m pytest
uv run ruff check src tests
cd frontend && npm run build
```
