# Record and review a YAM simulator pilot

Run these commands in PowerShell from the repository root on the `codex/teach-task-coach` branch. Install Git, uv and Node.js first. MuJoCo needs working OpenGL camera rendering even in headless mode.

## Prepare Coach and test the cameras

```powershell
cd coach
uv sync --locked --extra sim
Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location
$env:COACH_ROLLOUTS_DIR = Join-Path $env:LOCALAPPDATA 'TeachTaskCoach\sim-rollouts'
$recorder = '.\experiments\yam_sim_faas\record_dream_model_rollout.py'
uv run --locked --extra sim python $recorder --output "$env:COACH_ROLLOUTS_DIR" --seed 41 --dry-run
```

The dry run records the camera warm-up. It should finish with nine observation frames per camera ready to send and zero executed model actions. If it fails, resolve the local error before using credits.

## Run one model pilot

Enter your Dream API key at the masked prompt. The variable is scoped to this PowerShell process and its children. Use the same shell for these commands.

```powershell
$key = Read-Host 'Dream API key' -AsSecureString
$env:DREAM_API_KEY = [System.Net.NetworkCredential]::new('', $key).Password
Remove-Variable key
uv run --locked --extra sim teach-task-coach preflight
```

Check that the Dream section lists your intended model as servable. The station section can say unavailable on a simulator-only machine. If Dream rejects the key or the model is unavailable, stop here.

```powershell
try {
    uv run --locked --extra sim python $recorder --output "$env:COACH_ROLLOUTS_DIR" --seed 41 --model dreamlabs/dream-1-beta --seconds 60 --max-requests 1
} finally {
    Remove-Item Env:DREAM_API_KEY -ErrorAction SilentlyContinue
}
uv run --locked --extra sim teach-task-coach serve
```

Open **http://127.0.0.1:8765** and select **Runs → Scan rollouts**. Open the **model** recording. Check that it shows at least one executed model action row, play each camera view, then save an operator outcome or leave it unlabelled if the clip is too short to judge. A single response can cover only the start of a pickup. The cap counts calls to the SDK's `get_action`; account charges are determined by Dream. The seconds flag limits the control loop, and an in-flight request can take longer. This command only runs inference.

## Gather varied runs

For free scripted apple pickup demonstrations, reuse the same root:

```powershell
uv run --locked --extra sim python .\experiments\yam_sim_faas\record_yam_demos.py --output "$env:COACH_ROLLOUTS_DIR" --episodes 2 --seed 101
```

This samples the apple's initial X and Y positions within 2.5 cm of the original placement. Seeds 101 and 102 give two reproducible scenes. Omit the seed to choose a fresh starting seed. Repeating a seed repeats the placement and creates a separate run. Run **Scan rollouts** again after collection. Each finished run keeps its videos, state/action rows and an atomic `rollout.json` beside them. The sidecar records simulation provenance and the actual starting position. The scripted pickup check lives in `simulation.script_result`; the operator label is entered separately. Review failures before selecting training examples. An interruption during capture can produce a partial recording, and abrupt process termination can leave an unfinished directory that Coach skips.

Review and label the original 20 Hz recordings. For training, select reviewed scripted successes in a separate source directory before using the 10 Hz conversion in the [experiment notes](README.md). The standalone statistical evaluator requires eligible physical trials for its real-world verdict.
