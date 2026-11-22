# Measuring whether the coach helps operators

This is a **prospective operator study template**, not evidence that the coach already saves time or Dream FaaS spend. The committed eight-person example is entirely synthetic. Its made-up 3/4 versus 1/4 validation rates are useful for testing the analysis and display, not for a product claim. Even with those invented numbers, a two-sided Fisher test is not significant.

## Run the synthetic example

From `coach/`:

```sh
uv run --python 3.11 --locked python benchmark/coach_benchmark.py benchmark/plan.synthetic.json benchmark/outcomes.synthetic.json
```

The CLI and the UI's **Coach effect** tab print each arm's validation rate by the fixed horizon, mean restricted time (time to validation, or the entire horizon for an unresolved participant), demo count, FaaS jobs and steps, failed evaluations, operator minutes, any reported FaaS cost, coach-minus-standard differences, a two-sided Fisher p-value, warnings, and a checksum of the supplied snapshot. Both require `data_kind: "synthetic"` or `"observed"` in the frozen plan. The example is visibly labelled synthetic. Analysis makes no Dream API, training, or robot call.

## Real study protocol

1. Choose **one robot and one task**, define a reviewable held-out success criterion, and freeze the same time horizon and available FaaS budget for both groups. Predeclare the primary outcome as the fraction reaching a separately audited improvement by the horizon. Compare restricted time as a secondary measure. Keep the same preflight and safety requirements for both groups.
2. Recruit operators with similar experience, randomize them to ordinary Dream tools or the coach **before** any session, record the assignment and `data_kind: "observed"` in `plan.json`, and timestamp and archive that plan before collecting outcomes. This script checks the claimed timing and balanced roster but cannot verify the actual randomization. Do not change the assignment after observing results.
3. Record every assigned operator, including those who never obtain a validated improvement. Save the independent paired-audit report for each success and enter its SHA-256 in `validation_report_sha256`; its decision must actually be `improved` under the frozen task rule. Record demo, job, paid step, and failed-evaluation counts from logs rather than recollection. Use the actual Dream bill for `faas_cost_usd` or leave it `null`; steps are not a price quote.
4. Keep failures under observation for the full horizon, even if an operator stops early. If follow-up is incomplete, the CLI refuses the study. The time metric counts unresolved operators as the full horizon rather than reporting a misleading median among only those who succeeded.
5. Analyze once after the frozen horizon. Report the raw denominators, differences, p-value, and protocol deviations. A small pilot should guide a larger preplanned study, not be sold as proof of general benefit. Repeat on other tasks and robots rather than pooling heterogeneous sessions into this one-task estimate.

The analyzer cannot authenticate reviewers, costs, randomization or a supplied checksum against the underlying audit report. Keep the immutable plan, raw session logs, Dream job IDs and bills, and paired reports with the result. Do not use this synthetic fixture as evidence of effectiveness.

The **Coach effect** UI also shows local task counts from the coach database: baseline and repair trials, imported and kept demos, submitted FaaS jobs and steps, and validated paired improvements. This reduces recollection for the coach arm, but it omits activity done outside the local app. Submitted steps are not billed cost or completed training, and operator hands-on minutes need a separate session log. Enter those alongside comparable standard-workflow records in the prospective study.
