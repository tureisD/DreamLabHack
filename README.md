# DreamLabHack

Shared integration base for the Teach it a task / Dream-FDE Studio project.

## Active development

| Branch | Responsibility | Merge target |
| --- | --- | --- |
| `codex/local-app` | tureisD: local application, rollout import, persistence, UI, and integration | `main` after evaluation integration |
| `codex/stat-eval` | Evaluation teammate: statistical evaluation engine and reports | `codex/local-app` |
| `main` | Final team integration | Future reviewed releases |

Start with the comprehensive README on `codex/local-app`. The evaluator's task,
implementation guidance, and pitfalls are documented in
`src/dreamlab/evaluation/README.md` on `codex/stat-eval`.

This branch deliberately contains only the shared starting environment. The local
application scaffold and evaluation handoff are developed on the branches above.
No complete robot application or statistical evaluator is implemented yet.

The intended merge order is:

```text
codex/stat-eval -> codex/local-app -> main
```

Use pull requests and preserve this common history. Do not merge statistical
work directly into `main` before validating the combined local application.

[Team plan](https://app.notion.com/p/DreamLabs-Hack-41ffb173f45e8077a9ddce60400b8388)
