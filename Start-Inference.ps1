param([string]$PythonExe)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!$PythonExe) { $PythonExe=Join-Path $PSScriptRoot 'runtime/livetalking/Scripts/python.exe' }
& $PythonExe -X utf8 -B scripts/start_studio.py --no-browser
if ($LASTEXITCODE -ne 0) { throw 'Avatar or speech startup failed; inspect project logs.' }
& $PythonExe -X utf8 -B scripts/dsh_control.py status
if ($LASTEXITCODE -ne 0) { throw 'DSH status failed.' }
$InferenceHealth=$null
try { $InferenceHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/dsh/status' -TimeoutSec 5 } catch { }
if (!$InferenceHealth.health.process_alive) {
 & $PythonExe -X utf8 -B scripts/dsh_control.py start
 if ($LASTEXITCODE -ne 0) { throw 'DSH startup failed; inspect project logs.' }
}
Write-Output 'A-device inference started. Open the B-device receiver to prepare local interaction.'
