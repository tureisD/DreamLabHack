# Teach it a task

A local companion for the [Dream Labs public library](../dream_library/README.md). This first feature is a read-only preflight: it checks the robot station and lists checkpoints visible to the configured Dream account. It does not move the robot, upload data, or submit fine-tuning jobs.

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

## Checks

```bash
uv run pytest
uv run ruff check src tests
cd frontend && npm run build
```
