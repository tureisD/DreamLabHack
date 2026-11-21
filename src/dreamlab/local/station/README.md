# Dream station adapter (local owner)

Start with read-only status retrieval after verifying the actual upstream station
API and a pilot fixture. Configure the station URL explicitly, use timeouts, and
map connection errors to actionable local status. Preserve raw status evidence.

Starting/stopping trials is a later integration, with operator confirmation and
the station retaining control and safety limits. Neither an evaluation report nor
a browser refresh may start hardware or switch checkpoints. Do not implement
teleoperation or fine-tune submission in the evaluation module.

Never call a live station in unit tests. No hardware adapter is implemented yet.
