# DreamLabHack: local and statistical evaluation workspace

Development branch: `codex/local-stat-eval`.

This branch starts with environment setup only. The remote repository was empty
when cloned on 2026-11-21; there was no existing application, dependency manifest,
or test suite to adopt.

## Setup

Use Python 3.12 and uv (or pip inside a Python 3.12 virtual environment).

```powershell
uv venv --python 3.12 .venv
uv pip sync --python .venv/Scripts/python.exe requirements-dev.txt
.venv/Scripts/python.exe -m pytest --version
.venv/Scripts/ruff.exe --version
```

`requirements-dev.in` lists direct development dependencies;
`requirements-dev.txt` pins the resolved environment. To update intentionally:

```powershell
uv pip compile --python .venv/Scripts/python.exe requirements-dev.in -o requirements-dev.txt
```

Raw recordings, local databases, credentials, virtual environments, and generated
artifacts are excluded from Git. Add only intentionally curated fixtures later.

## Scope and integration

The working scope is local run ingestion and evaluation persistence, baseline vs
candidate trial tracking, statistical comparison, and reproducible reports within
the team's broader Teach it a task / Dream-FDE Studio project.

Reference: [team Notion plan](https://app.notion.com/p/DreamLabs-Hack-41ffb173f45e8077a9ddce60400b8388).

The diagrams connect the evaluator to the station adapter, with metadata in
SQLite and recordings/reports on the local filesystem. Module boundaries and
shared record schemas will be aligned with the team's implementation before
application code is added. The statistical method and stopping rules are not
selected by this environment setup.

No robot control, paid training, model promotion, or remote service is started
by these setup commands. No application tests exist yet.

## Joining the team history

This setup starts from an empty remote. If the team independently creates the
main branch, fetch that branch and replay this small setup commit onto it before
continuing, reconciling any dependency/configuration overlap. Do not force-push
or overwrite the team's branch.
