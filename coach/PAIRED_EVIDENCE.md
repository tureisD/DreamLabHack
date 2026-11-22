# Matched-scene evidence for fine-tuning

The **Statistical evaluation** tab now has two analysis paths. The imported independent-trial engine handles prospectively assigned, human-verified real-world attempts in one scenario. The paired path handles the coach's matched base-versus-fine-tune scenes and the YAM simulator demonstration. These designs have different assumptions and must not share a single interval formula or verdict.

## Try the fine-tuning demonstration

Start the coach locally, open **Statistical evaluation**, and select **Load and analyze our 500-step apple demo**. The tab loads the [committed paired summary](src/teach_task_coach/examples/apple_paired_confirmation.json), calls the same `POST /api/paired-evaluations/analyze` endpoint available for user snapshots, and shows the four scenes, held lift, first gripper-close time, outcome, evidence problems, and snapshot checksum. Download the resulting JSON report for review.

| Predeclared scene | Base held lift | Fine-tune held lift | Base close after warm-up | Fine-tune close after warm-up |
| --- | ---: | ---: | ---: | ---: |
| 905 | 0.6 cm | 16.6 cm | 0.9 s | 11.2 s |
| 906 | <0.1 cm | 15.7 cm | 0.9 s | 10.3 s |
| 907 | <0.1 cm | 15.7 cm | 0.7 s | 11.7 s |
| 908 | <0.1 cm | 14.8 cm | 0.9 s | 10.5 s |

The candidate passed **4/4** and base passed **0/4** under the frozen 8 cm lift held for two seconds. The paired report deliberately says **`descriptive`**, with no confidence interval or deployment decision. Four same-distribution simulator scenes do not establish physical-robot reliability or a precise success probability. This result shows that the unchanged 500-step fine-tune behaved differently from the base and that the evaluation pipeline can measure it correctly. It does not show that the new statistical code improved the model's weights.

The [protocol](experiments/yam_sim_faas/grasp_training/CONFIRMATION_PROTOCOL.md) was committed before the API calls. The [full experiment report](experiments/yam_sim_faas/grasp_training/EXTENDED_500_STEP_EVAL.md) records all eight run IDs and replay checks. The JSON example was rebuilt by [this script](experiments/yam_sim_faas/grasp_training/build_confirmation_evidence.py) from the local score-only rollouts; it keeps their score summaries and IDs, while the full action and video traces remain local. A clone can reproduce the **analysis** of the committed JSON; reproducing the measurements requires those raw rollouts and Dream model access.

## What the paired evaluator checks

For a real coach fine-tune, create the 30-scene comparison in **Evaluate the fine-tune** before running either checkpoint. Enter the name or ID of the person who reviews each completed rollout. After the trials, confirm that the scenes were excluded from training and reset between runs, then select **Analyze and download paired evidence**. This calls `POST /api/evaluations/{id}/paired-snapshot`, followed by `POST /api/paired-evaluations/analyze`. The JSON download preserves the plan and every observed attempt for review in **Statistical evaluation**. The attestations record the operator's claim; the software cannot independently verify training exposure or physical reset. Existing labels without reviewer names, missing timestamps, and unfinished scenes remain visible but make the stricter audit `not_evaluable`.

An input has a frozen plan, its task success and reset rules, checkpoint IDs, collection mode, pair budget, creation time, and every submitted scene pair. Attempts retain their IDs, checkpoint, source, session, timestamp, outcome, training exposure and safety stops. Simulator attempts also need recorded apple height, held lift, replay error under 5 mm, and the planned number of model action rows. A simulator pass/fail label must agree with its frozen held-lift threshold. The API retains incomplete attempts; a missing arm, altered label, insufficient replay evidence, reused session, training-exposed attempt or unmet pair budget produces `not_evaluable` rather than a favorable prefix.

For **prospective physical pairs**, every complete outcome must have a named human reviewer. The evaluator reports the observed average of candidate-minus-base outcomes in each pair. With the exact predeclared pair budget, it uses a two-sided Hoeffding bound on independent pair differences in `[-1, 1]`. Its lower bound must exceed the frozen minimum improvement to say `improved`; an upper bound below zero says `regressed`. An excess of candidate safety stops blocks an improvement verdict. The bound is conservative and does not prove pair independence, correct resets, unbiased scene assignment or reviewer accuracy. Four perfect physical pairs remain `inconclusive` under this rule; a 30-pair all-candidate-only **synthetic test** clears a 15-point margin. That synthetic test is a software check, not measured robot performance.

## How it changes the FaaS loop

1. Freeze scene assignment and success before data collection. Keep the training scenes out of evaluation.
2. Train through Dream FaaS with the reviewed dataset. The evaluation addition makes no training call and does not alter weights.
3. Run base and candidate on the same held-out scenes. Score the actual task outcome, not peak motion or a prematurely stopped trial. Save every attempt and its failure evidence.
4. Review the paired result. If both models fail, inspect cameras, setup and failure stage before deciding what to demonstrate next. If the fine-tune passes in-range scenes, test harder placements and start poses before paying for more similar data.
5. For physical claims, collect enough reviewed prospective pairs to clear the predeclared bound and separately review safety. A descriptive simulator result is a reason to continue testing, not a deployment authorization.

The new code makes a **previously unsupported comparison visible without misusing the independent engine**. It also prevents a bad or incomplete simulator trace from becoming a success claim. It cannot evaluate every robot task automatically: outcomes still need a task-specific success rule and reliable measurement, and observational deployment, clustered sessions, multi-task pooling, and repeated unplanned looks remain unsupported.
