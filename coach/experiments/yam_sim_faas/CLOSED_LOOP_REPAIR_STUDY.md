# Measured closed-loop evaluation repair

This is a live Dream API and MuJoCo study of **one decision** in DreamCoach's loop: whether an unchanged apple fine-tune appears to work when a task evaluation runs long enough to observe the required lift. It is not an ordinary-workflow versus coach-workflow operator study.

The [eight-pair protocol](closed_loop_repair_plan.json) was committed as `5a53ee3` before these model calls. The [runner](closed_loop_repair_study.py) was committed as `e6149cf` before execution. The model was the second account's already-completed 500-step checkpoint, `dream-1-ft:f2cc8d90-apple-independent24-500`. No dataset was uploaded and no FaaS job was submitted during this study.

## Result on fresh scenes 913–920

| Evaluation setting | Verified held-lift successes | Productive model action rows |
| --- | ---: | ---: |
| Original nine-request horizon | 7/8 | 3,456 |
| Coach twelve-request horizon | 8/8 | 4,608 |

All sixteen runs completed. Each saved trace passed action replay and the same eight-centimetre lift held for two seconds was scored from recorded simulator height. On seed **916**, the nine-request run held only **6.35 cm**, while the twelve-request run held **10.73 cm**. The extended run's own recorded prefix first crossed the held-lift threshold at **request 10**. The other seven extended traces crossed it by request nine. The [machine-readable paired report](closed_loop_repair_report.json) retains every scene and run ID; full action traces are local under `%LOCALAPPDATA%/TeachTaskCoach/closed-loop-repair-913-920`.

This is a descriptive eight-scene result: **one coach-only success, zero original-only successes**. Independent calls to the same checkpoint can vary, and the two horizons also execute different numbers of action rows. The within-trace prefix on seed 916 confirms that its extra executed rows were needed for that particular successful trajectory. Eight same-distribution simulator scenes do not establish a general success rate or a physical-robot result.

The twelve-request arm consumed 33% more productive action rows per scene. Its total wall time also includes nine Dream pool-warming refusals on the first trial, so the raw wall-time totals are not a clean comparison of operator effort or steady-state latency. There is no observed dollar saving here. The finding is narrower: an evaluation that stops at nine requests can misclassify a working checkpoint and trigger a needless *decision* to collect more data or retrain. Whether users actually make that decision, and its cost, needs an operator study.

## Independent confirmation

After seeing the eight-pair result, we froze a **separate** [20-scene confirmation protocol](horizon_confirmation_plan.json) on fresh seeds 921–940. It records twelve-request trajectories and scores the nine-request prefix from those **same** trajectories. This isolates the effect of the execution horizon within each recorded model run and avoids a second stochastic inference run per scene. Its results must be reported separately from the exploratory eight-pair comparison. The [confirmation runner](horizon_confirmation.py) retains invalid and incomplete attempts.

## Remaining product claim

The [operator benchmark](../../benchmark/README.md) remains prospective and its included example remains synthetic. To claim that DreamCoach saves demonstrations, hands-on time, or FaaS spend, recruit and assign operators before they begin, freeze the same task and budget for both arms, log every session and actual Dream bill, and evaluate each resulting checkpoint on separately held-out scenes. This study does not substitute for those measurements.
