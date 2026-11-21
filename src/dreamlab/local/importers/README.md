# Rollout import boundary (local owner)

Implement a read-only `RolloutImporter` here once real pilot samples are available.
Parse `rollout.json`, `inference.jsonl`, videos and optional traces through
format-specific adapters, retaining raw metadata and file checksums.

Do not assume every embodiment emits every field or that a stopped run succeeded.
Missing optional telemetry is unknown, never zero. Preserve source clock units,
checkpoint ID and episode ID; flag unresolvable action/observation alignment.
Check archive paths, traversal and file sizes before extracting untrusted data.
Deduplicate imports by source identity/content rather than filename alone.

Output local episode records; human annotation and the experiment service build
`contracts.Trial`. The evaluator must never read raw folders itself.

Expected tests: fixtures for valid, duplicate, malformed, truncated and older
rollouts. Raw footage stays outside Git. No importer is implemented yet.
