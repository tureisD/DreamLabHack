# Data eligibility and retained research

Research retained from 21 November 2026. The evaluation component consumes prepared
trial records, not videos. Preserve these lessons from the retired app research;
video playback, importers and dataset curation are no longer implementation tasks.

## What can be used without hardware

| Input | Appropriate use | What it cannot establish |
| --- | --- | --- |
| Existing synthetic JSON fixture | Contract, reporting and explicit unavailable-engine tests | Adequate sample size or robot improvement |
| Seeded synthetic experiments | Coverage, false-claim behavior, power and sequential replay under specified assumptions | Real deployment performance |
| Independently calculated reference cases | Numerical correctness and boundary handling | Empirical calibration across all settings |
| Public demonstration recordings | Illustrate provenance gaps; possible producer-side examples later | Baseline-versus-candidate improvement without actual checkpoint trials |
| Properly documented saved comparison trials | Potential real analysis after eligibility review | Randomization/holdout validity merely because metadata is present |

For synthetic tests, populate complete fictional metadata deliberately and label
the fixture/study synthetic in its manifest and report presentation. Do not present
fictional checkpoint IDs or dates as real evidence. V1 does not have a general
demonstration type or simulator-oracle label policy; do not force unsuitable inputs
through its required fields.

## Public dataset findings

The earlier audit downloaded 18 files totaling 17,703,671 bytes and parsed tables
with PyArrow 26.0.1 and decoded six videos with PyAV 19.0.2. Those tools and media
are not dependencies of this evaluator. The evidence is a compatibility observation,
not a statistical benchmark.

| Dataset and pinned revision | Observed finding | Relevance to evaluation |
| --- | --- | --- |
| [PushT v2.1](https://huggingface.co/datasets/lerobot/pusht/tree/6e1d9c95aaf8abb19342e723935b6af7c54b5903) | Episode 0 had 161 table rows and decoded frames | Frames are not independent task attempts |
| [PushT v3](https://huggingface.co/datasets/lerobot/pusht/tree/7628202a2180972f291ba1bc6723834921e72c19) | 206 episodes in shared files; every inspected `next.success` value was false | A source flag is not automatically a verified task label |
| [ALOHA cups v2.1](https://huggingface.co/datasets/lerobot/aloha_static_cups_open/tree/fc9f40db2aba836a3005f7908652b85aa2a2c6e1) | Episode 0 had four 400-frame streams and `next.done` | Termination does not establish task success or Dream checkpoint identity |
| [ALOHA simulated insertion](https://huggingface.co/datasets/lerobot/aloha_sim_insertion_human/tree/cc571a3c661df81b566dbfde3d5c1e85fcdf7884) | Public metadata inspected; media not sampled | Simulation/demonstration identity must remain explicit |

Some cards showed older layouts than their current files. Pin source revisions and
retain producer manifests. Do not randomly split demonstrations into invented
baseline/candidate arms, treat file modification time as collection time, assume
zero interventions, or mark machine labels human-verified.

## Dream-specific lessons

The source audit used `dreamlabs-co/dreamlabs` revision
`ba8ad9850dd2e783b3c10fc079b0b5f78d7df441`. Saved rollout completion/stop reason is
not an outcome label. Nominal frame time and monotonic loop time differ; recorded
commands and raw model replies are distinct. A producer must preserve their meaning
before supplying duration, intervention or task-outcome evidence. The evaluator
does not reconstruct these from footage. [Pinned robot documentation](https://github.com/dreamlabs-co/dreamlabs/blob/ba8ad9850dd2e783b3c10fc079b0b5f78d7df441/dream_library/robots/README.md).

## Required evidence discipline

- Freeze the task rule, checkpoints, design, budget, label policy and supported
  analysis plan before collecting/inspecting evidence for a confirmatory claim.
- Preserve all attempts and explicit unknown/invalid categories; record assistance,
  safety events and exclusions without selectively removing inconvenient outcomes.
- Keep source identity/aliases so copied footage cannot become additional trials.
- Record training exposure, session dependence and data origin. Unique IDs do not
  prove independence; human verification does not prove holdout.
- Keep exact input snapshots and hashes. Changes to labels, ordering or methods
  require new artifacts, not edits to old reports.
- If evidence cannot support the requested claim, return a clear limitation or
  `not_evaluable`. Public data and synthetic tests remain useful without inventing
  physical checkpoint improvement.
