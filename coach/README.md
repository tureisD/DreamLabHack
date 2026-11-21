# Teach it a task

A local companion for the [Dream Labs public library](../dream_library/README.md). It checks the robot station and lists accessible checkpoints, then imports saved station rollouts for review and operator success labels. It does not yet move the robot, upload data, or submit fine-tuning jobs.

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

## Checks

```bash
uv run pytest
uv run ruff check src tests
cd frontend && npm run build
```
