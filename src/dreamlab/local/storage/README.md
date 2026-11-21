# Persistence boundary (local owner)

Implement SQLite repositories and explicit numbered migrations here. Suggested
tables: tasks, task_versions, episodes, label_revisions, evaluation_plans,
evaluation_trials, evaluation_requests, evaluation_reports and background_jobs.
Use immutable plan/report snapshots and append-only label revisions. Store large
recordings separately; persist their paths and checksums, not video blobs.

Use transactions for importing an episode plus its metadata, unique constraints
for idempotency, foreign keys and an explicit schema version. Anticipate SQLite
write contention. Never keep a transaction open while calling hardware/cloud APIs.
Future jobs must survive browser/process restarts and have idempotency keys.

Database rows are local implementation details. Export the shared contract as JSON
for the evaluator. No SQLite repository or migration is implemented yet.
