param([Parameter(Mandatory=$true)][string]$PythonExe)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$ReceiverRuntime=Join-Path $PSScriptRoot 'runtime/receiver'
$ReceiverPython=Join-Path $ReceiverRuntime 'Scripts/python.exe'
$env:PIP_CACHE_DIR=Join-Path $PSScriptRoot 'cache/receiver/pip'
$env:TEMP=Join-Path $PSScriptRoot 'cache/receiver/tmp'
$env:TMP=$env:TEMP
New-Item -ItemType Directory -Path $env:TEMP,$env:PIP_CACHE_DIR -Force | Out-Null
if (!(Test-Path -LiteralPath $ReceiverPython)) {
 & $PythonExe -m venv $ReceiverRuntime
 if ($LASTEXITCODE -ne 0) { throw 'Native receiver environment creation failed.' }
}
& $ReceiverPython -m pip install -r configs/requirements-receiver.txt
if ($LASTEXITCODE -ne 0) { throw 'Receiver dependencies failed to install.' }
Write-Output 'B-device receiver installed. Use Start-Receiver.ps1 -Upstream http://A_DEVICE_VPN_HOST:8010.'
