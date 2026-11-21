# DreamLabHack

Shared integration base for the Teach it a task / Dream-FDE Studio project.

## Active development

| Branch | Responsibility | Merge target |
| --- | --- | --- |
| `codex/stat-eval` | Standalone statistical evaluation engine, runner, reports and validation | `main` |
| `main` | Final team integration | Future reviewed releases |

The local application workstream has been cancelled. Statistical evaluation is now
standalone and integrates directly into the larger project. Existing evaluation
branch history is preserved; collaborators can update their checkout normally.

Start with the [evaluation assignment](https://github.com/tureisD/DreamLabHack/blob/codex/stat-eval/README.md),
[documentation index](https://github.com/tureisD/DreamLabHack/blob/codex/stat-eval/docs/README.md),
and [numerical implementation guide](https://github.com/tureisD/DreamLabHack/blob/codex/stat-eval/src/dreamlab/evaluation/README.md).
These include setup, input/output contracts, testing, evidence limitations and
instructions for updating an existing teammate checkout.

This branch contains the shared starting environment. The evaluation scaffold and
implementation assignment live on `codex/stat-eval`; its engine and standalone
runner are not implemented at the time of this reorganization. Development and
numerical validation require no hardware, GPU, API key or paid fine-tuning job.

The intended merge order is:

```text
codex/stat-eval -> main
```

Use pull requests and preserve common history. Integrate the evaluator after
reviewing its supported methods, numerical tests, statistical validation evidence
and reproducible standalone request/report workflow. No local application is
required. The unfinished engine has not been merged by this reorganization.

[Team plan](https://app.notion.com/p/DreamLabs-Hack-41ffb173f45e8077a9ddce60400b8388)
