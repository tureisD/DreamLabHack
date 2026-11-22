# Failure-conditioned YAM demonstrations without a robot

This collector is our own loop around the Dream Labs YAM MuJoCo example. It is not a teleoperation game or a copy of another team's recorder. It uses a **model failure as the request for a demonstration**: replay the model's saved actions, identify its failed scene and grasp timing, choose different failure modes and apple positions, then record a corrective physics trajectory for those exact scenes. It exports synchronized 10 Hz LeRobot v2.1 episodes with three cameras and validates them with Dream's dataset validator. It never uses candidate-model evaluation scenes as training data.

The current implementation covers the bundled YAM **apple pickup** task and wrist-visible start pose. The corrective controller is the official YAM example's scripted pickup with our failure-conditioned timing recipe. This is simulator supervision, not human teleoperation or physical robot evidence. A future object/task needs its own reset, success rule, and corrective controller; the selection and provenance pattern can remain the same.

## Collect

From `coach/`, install `uv sync --locked --extra sim`. Select **fresh training candidate seeds** outside 41–48, 101–116, 201–224 and reserved evaluation seeds 901–912. Use new seeds such as 1201–1208. Record the base or current fine-tune on each scene with the existing model recorder. Model inference uses the local Dream credential and may consume account credits; the collector itself does not call Dream or launch FaaS.

```powershell
$raw = Join-Path $env:LOCALAPPDATA 'TeachTaskCoach/fresh-model-failures'
foreach ($seed in 1201..1208) {
  uv run --locked python experiments/yam_sim_faas/record_dream_model_rollout.py --output $raw --model dreamlabs/dream-1-beta --seed $seed --start-pose wrist-visible --max-requests 12 --score-only
}
uv run --locked python experiments/yam_sim_faas/collect_failure_demos.py --model-rollouts $raw --max-demos 8
```

Set `DREAM_API_KEY` or the Dream SDK credentials locally before the first command. Do not put a key in a script or commit it. If a model attempt fails or ends partial, the collector skips it. A 12-request run can be slow; interrupting it does not create a usable completed failure. Use `--output` on the collector to override `COACH_DEMOS_DIR` / the default local coach demos folder.

The collector rejects duplicate eligible scene seeds, mixed checkpoints, test seeds, and seeds used in our existing training batches. It scores model failure from the saved action trace and replayed or directly recorded apple height. It prioritizes distinct failure timing and spatially separated apple positions. It then checks the corrective controller's own task result, contact geometry and state replay, the downsampled action replay, and Dream dataset structure. Only fully checked episodes are moved into the coach demo folder. The JSON manifest records the source rollout path and SHA-256, selected failure kind, seed, recipe, frame count, and replay outcome. Source model runs remain separate from expert training episodes.

Open **Demos** in the coach, scan, inspect each camera, and choose **Keep** or **Redo**. The training worker still requires a separately registered YAM embodiment and an explicit paid job submission. Freeze a fresh evaluation split before a new FaaS job; do not use the failure scenes for the before/after verdict. The existing 901–912 evaluation scenes remain excluded from this collector.

## What this can establish

The local end-to-end test creates a synthetic failed control trace, then verifies one corrective demo and Dream dataset validation. That proves format, replay, and split gates. It does **not** show that active selection needs fewer demonstrations or produces a better checkpoint than random scripted collection. To establish that, fix equal model, FaaS steps, budget, and held-out scenes, compare random versus failure-conditioned training seeds, and record the full result. For the separate claim that the **coach saves operators time or money**, use the prospective randomized study in [`../../benchmark/README.md`](../../benchmark/README.md) and the UI's **Coach effect** tab. Its committed example is synthetic and must not be cited as measured savings.
