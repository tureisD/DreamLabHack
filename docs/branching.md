# Standalone evaluation branch workflow

## Child branch for later improvements

`codex/stat-eval-extensions` starts from parent commit
`c08056c78896564ce82a3516f4e9b488310d256f`. Its initial PR base is
**`codex/stat-eval`**. Read [the extension plan](extensions/README.md).
Wait for the baseline engine's validated release before implementing extensions.

To create a fresh checkout, clone the repository and use
`git switch --track origin/codex/stat-eval-extensions`. In an existing checkout use
`git fetch origin`, then switch to the existing child branch. Commit or stash work
before synchronizing with `git merge origin/codex/stat-eval`; never force-push either
shared branch. Update child README/contract assumptions after each parent sync.

The intended path is `codex/stat-eval-extensions -> codex/stat-eval -> main`.
If the baseline is merged and the parent branch retired first, merge current main
into this child and open its PR against main instead; document that change. Do not
depend on a deleted parent or rewrite collaborator commits.

The workflow below describes the baseline parent.

Updated 21 November 2026. The local application has been cancelled. The active
feature branch is **`codex/stat-eval`**, merging directly into **`main`**.
The intermediate `codex/local-app` branch is retired. Its history was backed up
before deletion; its application plans are not an active assignment.

## Existing teammate checkout

The evaluation branch name and existing commits are preserved. No history rewrite,
rebase or force-push is required. Commit or stash uncommitted work before updating;
never discard it to follow these instructions.

```shell
git fetch origin --prune
git switch codex/stat-eval
git merge origin/codex/stat-eval
uv sync --locked --extra eval --group dev
uv run --locked --extra eval pytest
```

Restore stashed changes and resolve conflicts if necessary. Numerical implementation
remains in `src/dreamlab/evaluation/` and `tests/evaluation/`. The reorganization
removes obsolete app files and updates documentation/dependencies; it does not
replace statistical methods. Re-sync the environment to remove unused web packages.
For a new clone, follow the root README. Each worktree needs its own environment.

## Keeping up with the larger project

From a clean evaluation checkout:

```shell
git fetch origin
git merge origin/main
```

Resolve `pyproject.toml` before regenerating `uv.lock` with `uv lock`; do not splice
lockfile records manually. Coordinate shared-contract changes and fixtures with
producer/consumer owners. Do not fetch or merge the retired app branch or restore
its UI, database, station-control or importer assignment during conflict resolution.

## Integration into main

1. Push evaluation work without rewriting shared history.
2. Open a PR with **base `main`**, head **`codex/stat-eval`**.
3. Document supported/unsupported designs, input requirements, numerical references,
   simulation evidence, exact commands and any contract changes.
4. Run lint, formatting, tests and package build on Windows/Linux. Verify a fresh
   wheel install, Linux request/report round trip, and Windows fail-closed artifact
   behavior. Method validation remains separate from runner tests.
5. Resolve main's README deliberately: retain a useful project entry point and the
   evaluator's technical guides. No intermediate app README needs preservation.
6. Merge after project review. Consumers can call the protocol or exchange versioned
   JSON files without a web application.

This reorganization does not merge the unfinished engine into main. Main's README
is updated only to point developers to the active assignment.
