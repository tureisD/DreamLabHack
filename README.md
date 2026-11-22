# DreamCoach

**Find out why Dream-1 failed, what to demonstrate next, and whether a fine-tune helped.**

A failed pickup can mean the gripper closed too early, the camera feed stalled, or the evaluation stopped while the robot was still lifting. Each calls for a different next step. DreamCoach adds a closed loop around Dream Labs' fine-tuning service (FaaS) so you can diagnose the baseline, fix setup issues or collect targeted demos, and compare checkpoints on reserved scenes before paying to train again.

## Try it

| I want to… | Start here |
| --- | --- |
| Try DreamCoach online | [Open the live app](https://dreamcoach-live.onrender.com/), click **Begin**, and connect with your own Dream Labs API key. |
| See a real simulator comparison | [Watch the matched apple pickup and inspect its traces](coach/experiments/yam_sim_faas/grasp_training/full-901/README.md). |
| Review runs without keys or hardware | [Try the isolated offline walkthrough](coach/README.md#offline-apple-pickup-walkthrough) with scripted fixtures. |
| Run DreamCoach on my computer | [Follow the local setup](#run-dreamcoach-locally) and choose a simulator Quick start. |
| Test a checkpoint I already trained | Choose **Apple pickup → Evaluate existing checkpoint**, pick the checkpoint by its training dataset, and start a matched comparison. Dream may charge for inference. |
| Audit independent physical trials | Use the [standalone statistical evaluator](#standalone-statistical-evaluator). |

## How the closed loop works

1. **Define success and run a baseline.** The coach proposes a task instruction and an observable success rule for you to approve. Station preflight checks camera freshness, arm readiness, and logged faults. **Repair first** compares one prompt or setup change on matched diagnostic scenes with the same checkpoint. [Repair-first workflow](coach/REPAIR_FIRST.md)
2. **Record and review demos where the model struggles.** Use baseline failures and accepted-demo coverage to decide what to record. Review camera clips and quality findings, then keep or redo each demo. Simulated demos, imported LeRobot sessions, and supervised local SO-101 recordings feed the same review process. [Demo intake and physical recording](coach/README.md#run-locally)
3. **Validate and train.** DreamCoach builds a dataset from kept demos, runs Dream's validator, asks you to approve the paid submission, and tracks processing, training, and checkpoint readiness. Retry failed processing on the same upload or explicitly continue an eligible constant-schedule job. [Training and continuation rules](coach/README.md#run-locally)
4. **Compare base and fine-tune on held-out scenes.** Both checkpoints get the same starting conditions and success rule. Follow the paired counts in **Evaluation results** and click **Explain comparison results** to see what happened in each scene. Physical promotion requires reviewed outcomes, an evidence audit, and operator approval. [Paired evaluation and promotion](coach/PAIRED_EVIDENCE.md)
5. **Decide what to change.** Repair an invalid run, retest with a fair trial length, or collect examples that target a repeatable failure. Keep the new evaluation scenes out of training.

Simulator setup, scene approval, camera preview, and FaaS approval can stay in the conversation. **Begin** opens a fresh session. **Quit run** stops the current simulator rollout and keeps completed trial evidence.

## Why did the robot fail?

For YAM apple pickup, DreamCoach replays saved actions and checks them against recorded joint states. It uses gripper commands, fingertip contact, distance from the apple, and apple height over time to explain each base and fine-tuned run. The report shows the evidence and suggests what to try next. It can analyze saved traces locally without another Dream inference call.

| What the evidence shows | What to check next |
| --- | --- |
| The gripper never closed, closed too far from the apple, or failed to establish a secure grasp | Check approach and close timing. If it repeats, demonstrate a centered grasp at that start position. |
| The gripper made contact but the apple stayed low or fell | Inspect the lift and hold separately from the grasp. Demonstrate the missing phase if it recurs. |
| The trial ended while the apple was rising or before the hold completed | Retest both checkpoints with the same suitable time budget before deciding to retrain. |
| The service restarted, a safety check stopped the run, or replay could not verify the trace | Inspect the execution issue separately from a completed task failure. |

The apple rule is **an 8 cm lift held continuously for two seconds**. In one saved scene, the base model briefly reached **8.5 cm** but sustained only **0.6 cm** over its best two-second window. Peak height alone would have scored that run incorrectly. Other tasks need their own observable rules. Physical station diagnosis uses logs, camera checks, and operator labels to guide inspection. [Corrected held-out report](coach/experiments/yam_sim_faas/grasp_training/EXTENDED_500_STEP_EVAL.md) · [Diagnosis code](coach/experiments/yam_sim_faas/grasp_training/rollout_diagnosis.py)

## What the apple experiments showed

| Comparison | Result | What we learned |
| --- | --- | --- |
| [Original held-out test](coach/experiments/yam_sim_faas/grasp_training/HELDOUT_500_STEP_EVAL.md) | Base **0/4**, 500-step fine-tune **1/4** | The nine-request cap cut lifts short and a small normalized gripper overshoot triggered a simulator stop. |
| [Fresh scenes after fixing the evaluation](coach/experiments/yam_sim_faas/grasp_training/EXTENDED_500_STEP_EVAL.md) | Base **0/4**, same fine-tune **4/4** | Both models got twelve requests and were scored on sustained height. Small finite gripper overshoots were clamped in the simulator. Unsafe values still stopped the run. |
| [Separately trained 500-step checkpoint](coach/experiments/yam_sim_faas/grasp_training/SECOND_ACCOUNT_500_STEP_EVAL.md) | Base **0/4**, second fine-tune **4/4** | A second dataset and four fresh scenes reproduced useful apple pickup under the corrected rule. |
| [Timing study on an unchanged checkpoint](coach/experiments/yam_sim_faas/CLOSED_LOOP_REPAIR_STUDY.md) | **7/8** at nine requests, **8/8** at twelve. Separate same-trajectory confirmation **14/19** at nine, **19/19** at twelve. | Five valid confirmation trajectories first passed on request ten or eleven. One of twenty attempts restarted and was retained as invalid. |

Training produced the checkpoints. The evaluation fixes exposed behavior the first test missed without requiring another FaaS job. These results describe the tested simulator scenes. Physical reliability, transfer to other tasks, and reductions in operator time, demo count, or spending remain unmeasured. Open **Evaluation results → Explore the saved evidence** for the interactive timing study. The separate operator benchmark is prospective and its example is synthetic. [Operator-study design](coach/benchmark/README.md)

## Collect demonstrations without a robot

| YAM workflow | What you can do |
| --- | --- |
| **Apple pickup** | Import 24 bundled demos or run Dream-1 on fresh training scenes. The failure-conditioned collector records scripted corrections for selected failures and excludes reserved evaluation seeds. [Collection guide](coach/experiments/yam_sim_faas/FAILURE_CONDITIONED_SIM.md) |
| **Fruit correction** | Click an apple or banana for a lift, or click an apple and bowl for placement. Review three synchronized camera views before keeping the result. [Supported fruit tasks](coach/experiments/yam_sim_faas/CLICK_TO_CORRECT.md) |
| **Build a scene** | Choose a red-block or yellow-ball preset, or configure a supported object and target. Preview, record, and review the scene in chat. [Scene builder](coach/experiments/yam_sim_faas/SCENE_TASK_POC.md) |

DreamCoach builds on the Dream Labs YAM MuJoCo example. Local corrections undergo physics and dataset checks before review. Fresh model rollouts and checkpoint comparisons use the Dream API. Whether failure-conditioned collection beats random scripted collection at the same training budget remains unmeasured.

## Run DreamCoach locally

Install Git, uv, Node.js, and npm. Run these commands from the repository root.

```sh
cd coach
uv sync --locked --group dev --extra sim
cd frontend
npm ci
npm run build
cd ..
uv run --locked --extra sim teach-task-coach serve
```

Open [DreamCoach on localhost](http://127.0.0.1:8765), choose a Quick start, or click **Begin**. For live inference and training, create a [Dream Labs API key](https://platform.dreamlabs.ai/api-keys) and enter it in the masked connection field. The coach checks the server's Dream API access and can read datasets, fine-tuning jobs, and available models. Set `OPENAI_API_KEY` on the local server to enable conversational AI. Keep credentials out of chat. [Local configuration](coach/README.md)

For physical runs, connect the Dream station and enable rollout recording. For shared hosting, the Docker deployment supports separate Dream account workspaces and persistent storage. [Robot station setup](dream_library/robots/README.md) · [Hosting guide](coach/HOSTING.md)

## Two evaluation designs

| Evidence | Use |
| --- | --- |
| Both checkpoints attempt each **matched scene** | The coach's paired audit. Simulator results are descriptive. Eligible physical comparisons require a frozen plan, reviewed labels, reset attestations, and safety-stop accounting. [Matched-scene audit](coach/PAIRED_EVIDENCE.md) |
| **Independent**, prospective, held-out physical trials with human-reviewed outcomes in one scenario | The standalone evaluator. Run a fixed horizon or predeclared interim looks and get eligibility checks, effect, interval, and verdict. [Independent-trial methods](src/dreamlab/evaluation/README.md) |

### Standalone statistical evaluator

Run from the repository root on Linux. The example uses synthetic data and requires no credentials.

```sh
uv sync --locked --extra eval --group dev
uv run --locked --extra eval dream-eval evaluate \
  --input tests/fixtures/evaluation_request.json --output-dir example-run
```

Choose a new output directory. The CLI saves submitted and canonical inputs, a JSON report, a summary, and a reproducibility manifest. Publishing artifacts requires Linux and a filesystem with atomic no-replace rename. The Python evaluator also works on other platforms.

```python
from pathlib import Path

from dreamlab.contracts import EvaluationRequest
from dreamlab.evaluation.engine import StatisticalEvaluator

request = EvaluationRequest.model_validate_json(
    Path("tests/fixtures/evaluation_request.json").read_bytes()
)
report = StatisticalEvaluator().evaluate(request)
```

The estimated effect is candidate minus baseline. An `improved` verdict requires the interval's lower bound to clear the predefined minimum gain. Ineligible or incomplete evidence can return `not_evaluable` with counts and reasons. [Evaluator workflow](docs/evaluation-workflow.md) · [Testing and diagnostics](docs/testing-and-diagnostics.md)

## Repository map

| Path | Contents |
| --- | --- |
| [`coach/`](coach/README.md) | FastAPI server, React chat, workflow state, and Dream SDK integration |
| [`coach/experiments/yam_sim_faas/`](coach/experiments/yam_sim_faas/README.md) | Simulator collectors, replay tools, held-out protocols, and results |
| [`src/dreamlab/evaluation/`](src/dreamlab/evaluation/README.md) | Standalone evaluation engine and CLI |
| [`docs/`](docs/README.md) | Evaluation contracts, validation, and research roadmap |
| [`dream_library/`](dream_library/README.md) | Upstream Dream Labs client, robot station, and examples |

Use upstream `dreamcli` for robot setup and Live View, or `dream.DreamClient` to call Dream-1 from your own loop. [Python SDK](dream_library/dream_client/README.md) · [DreamAPI documentation](https://platform.dreamlabs.ai/api-documentation)

## License

[Apache License 2.0](LICENSE). Vendored packages, robot models, and external assets retain their respective licenses. [Third-party notices](dream_library/THIRD-PARTY-LICENSES.md)
