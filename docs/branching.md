# Branch and worktree workflow

The intended merge order is `codex/stat-eval` -> `codex/local-app` -> `main`.
All branches descend from the same shared base. Never force-push the shared team
branches. Do not merge an unfinished engine merely to make an API return HTTP 200.

## Start the evaluation assignment

```shell
git clone https://github.com/tureisD/DreamLabHack.git
cd DreamLabHack
git switch --track origin/codex/stat-eval
uv sync --locked --all-extras --group dev
```

Read the root README, `docs/contracts.md`, and
`src/dreamlab/evaluation/README.md`. Implement only the owned evaluation paths;
coordinate contract/dependency changes with the local owner.

## Parallel directories on one computer

If your checkout already has the local branch checked out:

```shell
git fetch origin
git worktree add ../DreamLabHack-stat-eval codex/stat-eval
```

If that branch is not yet local, use `git worktree add -b codex/stat-eval
../DreamLabHack-stat-eval origin/codex/stat-eval` instead. Do not run both commands.
Each worktree has its own `.venv` and ignored local artifacts. Never reuse a venv
across worktrees: editable installs point at a particular directory.

## Keep evaluation synchronized

From the stat-eval checkout with committed changes:

```shell
git fetch origin
git merge origin/codex/local-app
uv sync --locked --all-extras --group dev
uv run --locked --all-extras pytest
```

Resolve interfaces with both owners. If dependency declarations conflict, resolve
`pyproject.toml` first, regenerate `uv.lock` using `uv lock`, then sync/test. Do not
copy one side of a lockfile and assume it represents the combined manifest.

## Finish evaluation, then integrate the application

1. Push evaluation commits to `codex/stat-eval`.
2. Open a PR with **base `codex/local-app`**, head `codex/stat-eval`.
3. Verify contract compatibility, numerical reference results, statistical error
   checks, fixture report reproducibility, all-input accounting, and no hardware
   side effects. Document unsupported modes instead of silently falling back.
4. Merge after review. Update the local composition factory to inject the real
   evaluator and test persistence/UI against its reports; merging files alone is
   not a complete integration.
5. Open the combined local application PR with **base `main`**, head
   `codex/local-app`. Coordinate with the larger team's other modules at this step.

The setup task only creates and publishes the branches. It does not merge feature
work, change branch protection rules, create required checks, or assign reviewers.
GitHub Actions supplies checks; enforcement remains a team repository setting.
