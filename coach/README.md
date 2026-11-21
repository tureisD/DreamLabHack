# Teach it a task

A local companion for the [Dream Labs public library](../dream_library/README.md). It checks the robot station and lists accessible checkpoints, then imports saved station rollouts for review and operator success labels. It does not yet move the robot, upload data, or submit fine-tuning jobs.

## Run locally

From `coach/`:

```bash
uv sync --group dev
uv run teach-task-coach preflight
uv run teach-task-coach serve
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite. The frontend proxies `/api` to `127.0.0.1:8765`.

The coach connects to the Dream station at `http://127.0.0.1:8091` by default. Set `COACH_STATION_URL` if the station uses another local address. The Dream client uses its normal `DREAM_API_KEY`, `DREAM_CREDENTIALS`, or `~/.dreamlabs/credentials` configuration; no credential is stored in this repo.

Set `COACH_ROLLOUTS_DIR` to the station's rollout directory if it differs from `~/.dreamlabs/rollouts`. Enable `rollouts: {enabled: true}` in the station configuration to save local episodes. The coach stores tasks, trials, and labels in `.coach-data/coach.sqlite3` under its working directory by default; set `COACH_DATA_DIR` to keep that database elsewhere. The rollout files themselves are read only.

The **Tasks** screen now creates a task and supervised baseline trials. The operator sets up a marked 3×3 start grid, confirms before robot motion, stops the run, syncs its saved rollout, and labels the result. If recording failed, a stopped trial can be abandoned with a reason. Do not leave a robot run unattended.

## Checks

```bash
uv run pytest
uv run ruff check src tests
cd frontend && npm run build
```
