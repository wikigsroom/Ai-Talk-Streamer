param([string]$Upstream,[string]$ClientExecutable,[string]$PythonExe,[switch]$Stop)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!$PythonExe) {
 if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'runtime/receiver/Scripts/python.exe')) { $PythonExe=Join-Path $PSScriptRoot 'runtime/receiver/Scripts/python.exe' }
 else {
 $ReceiverPython=Get-Command python.exe -ErrorAction SilentlyContinue
 if (!$ReceiverPython) { throw 'Pass -PythonExe with a native Python that has aiohttp and psutil installed.' }
 $PythonExe=$ReceiverPython.Source
 }
}
if ($Stop) { & $PythonExe -X utf8 -B scripts/receiver_control.py stop; exit $LASTEXITCODE }
if ($Upstream) {
 $ReceiverArgs=@('-X','utf8','-B','scripts/receiver_control.py','configure','--upstream',$Upstream)
 if ($ClientExecutable) { $ReceiverArgs+=@('--client',$ClientExecutable) }
 & $PythonExe @ReceiverArgs
 if ($LASTEXITCODE -ne 0) { throw 'Receiver configuration failed' }
}
& $PythonExe -X utf8 -B scripts/receiver_control.py start
if ($LASTEXITCODE -ne 0) { throw 'Receiver startup failed' }
