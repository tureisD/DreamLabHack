# Pipeline smoke test — 22 November 2026

This run checks the local product path and independently replays the saved completed Dream experiment. It does **not** submit a new paid FaaS job or run a physical robot. No Dream credential was configured on this PC for a live API call.

| Stage | Evidence | Result |
| --- | --- | --- |
| Existing training archives | `batch.py verify independent` and `batch.py verify varied` checked committed SHA-256 manifests and ran Dream's real local dataset validator | **Pass:** independent 24 episodes / 3,961 frames at 10 Hz; varied 24 episodes / 3,871 frames at 10 Hz |
| Failure-conditioned robot-free collection | `tests/test_failure_conditioned_sim.py` created a synthetic failed YAM control trace, selected that failed scene, generated a corrective simulator demo, replayed the exported actions, and checked the three-camera LeRobot episode | **Pass:** one structurally valid, physics-audited demo with source and output hashes. This is a synthetic failure, not a fresh Dream-1 failure. |
| Coach demo → dataset → FaaS orchestration | The same integration test imported and kept that demo, made a Coach dataset version, ran Dream's real local validator, and advanced the worker through upload, processing, 500-step submission, and checkpoint publication | **Pass with a fake Dream gateway:** one upload and one training submission in the test. No remote upload, bill, or new checkpoint was produced. |
| Saved completed checkpoint evaluation | `build_second_account_evidence.py` re-scored all eight locally saved model action traces on frozen seeds 909–912 and passed the paired audit | **Pass:** base 0/4, independent 500-step checkpoint 4/4; zero evidence problems; audit SHA-256 `cce2728a65038d49e671fe1cfb51e2b6f9d51762ee11d8bab3b1a11f58403cd2`. This is descriptive simulator evidence. |
| API and regression tests | Focused FaaS, paired-audit, repair, and workload tests; the integrated failure-conditioned test | **Pass:** 18 focused tests plus 2 simulator tests. |

The saved second-account run record identifies Dream job `ftj_94b20f291e71d600` and checkpoint `dream-1-ft:f2cc8d90-apple-independent24-500`. Those are historical remote results, not outputs of this smoke test. The synthetic collector demo in this test was **not** the dataset that produced that checkpoint. The test therefore verifies the local seams and rechecks real saved output, but does not demonstrate a newly collected failure-conditioned dataset improving Dream-1 end to end.

To close that last gap, configure a Dream credential locally, collect new model failures on fresh training seeds, review and submit their generated dataset, wait for a new FaaS job, and run a predeclared paired evaluation on separate seeds. Measure operator time, demonstrations and actual billing against a standard-workflow group before claiming savings.
