param(
    [ValidateRange(1, 1000)][int]$MaxRequests = 1,
    [int]$Seed = 41,
    [switch]$ReplaceKey,
    [switch]$ForgetKey
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This launcher uses Windows current-user DPAPI.' }
$coach = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $coach '.venv/Scripts/python.exe'
$vault = Join-Path $env:LOCALAPPDATA 'TeachTaskCoach'
$keyPath = Join-Path $vault 'dream-key.dpapi'
if ($ForgetKey) {
    if (Test-Path -LiteralPath $keyPath) { Remove-Item -LiteralPath $keyPath }
    return
}
$save = $ReplaceKey -or !(Test-Path -LiteralPath $keyPath)
if ($save) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Dream pilot - enter API key'
    $form.ClientSize = New-Object System.Drawing.Size(480,160)
    $form.StartPosition = 'CenterScreen'
    $form.TopMost = $true
    $label = New-Object System.Windows.Forms.Label
    $label.Text = 'Save a Dream API key encrypted for this Windows account and run the pilot.'
    $label.SetBounds(15,15,450,40)
    $field = New-Object System.Windows.Forms.TextBox
    $field.UseSystemPasswordChar = $true
    $field.SetBounds(15,60,448,25)
    $run = New-Object System.Windows.Forms.Button
    $run.Text = 'Save and run'
    $run.SetBounds(250,108,100,32)
    $run.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = 'Cancel'
    $cancel.SetBounds(359,108,100,32)
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.AddRange(@($label,$field,$run,$cancel))
    $form.AcceptButton = $run
    $form.CancelButton = $cancel
    $form.Add_Shown({$form.Activate(); $field.Select()})
    Write-Output 'Waiting for key in local masked dialog.'
    try {
        if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK -or !$field.Text.Trim()) { Write-Output 'Cancelled before inference.'; exit 2 }
        $secret = ConvertTo-SecureString -String $field.Text.Trim() -AsPlainText -Force
        $field.Clear()
    } finally { $form.Dispose() }
} else {
    $secret = ConvertTo-SecureString (Get-Content -LiteralPath $keyPath -Raw).Trim()
}
$previousKey = $env:DREAM_API_KEY
try {
    $env:DREAM_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
    & $python -c "from teach_task_coach.preflight import PreflightService; c, ms=PreflightService()._check_dream(); print(c.message); raise SystemExit(0 if any(m.id=='dreamlabs/dream-1-beta' and m.servable for m in ms) else 3)"
    if ($LASTEXITCODE -ne 0) { throw 'Model preflight failed. Check connectivity or use -ReplaceKey.' }
    if ($save) {
        [IO.Directory]::CreateDirectory($vault) | Out-Null
        $tmp = Join-Path $vault ([guid]::NewGuid().ToString() + '.tmp')
        try {
            [IO.File]::WriteAllText($tmp, (ConvertFrom-SecureString $secret))
            if ([IO.File]::Exists($keyPath)) { [IO.File]::Replace($tmp, $keyPath, $null) }
            else { [IO.File]::Move($tmp, $keyPath) }
        } finally { if ([IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) } }
        Write-Output 'Saved the verified key using Windows current-user protection.'
    }
    $root = if ($env:COACH_ROLLOUTS_DIR) { $env:COACH_ROLLOUTS_DIR } else { Join-Path $vault 'sim-rollouts' }
    & $python (Join-Path $PSScriptRoot 'record_dream_model_rollout.py') --output $root --seed $Seed --seconds 600 --max-requests $MaxRequests
    exit $LASTEXITCODE
} finally {
    $env:DREAM_API_KEY = $previousKey
    $secret.Dispose()
}
