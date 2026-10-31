$Root='C:\dev\虚拟数字人直播\naimei'
$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
[Net.WebRequest]::DefaultWebProxy=$null
$rootPath=[IO.Path]::GetFullPath($Root)
if ($rootPath -ne 'C:\dev\虚拟数字人直播\naimei') {throw 'Naimei installation path required'}
$origin=Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $rootPath '.setup\deployment-origin.json')|ConvertFrom-Json
if ($origin.branch -ne 'naimei' -or -not $origin.verified_source_manifest) {throw 'Verified Naimei source required'}
$policy=Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $rootPath 'configs\naimei\live-runtime.json')|ConvertFrom-Json
if ($policy.character_id -ne 'naimei' -or $policy.public_broadcast_allowed) {throw 'Local Naimei rehearsal configuration required'}
$status=Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/status' -TimeoutSec 5
if ($status.health.character_id -ne 'naimei') {throw 'Another character owns the bridge'}
$platform=Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/platforms/status' -TimeoutSec 5
foreach($row in $platform.outputs){if($row.state -in @('STARTING','STREAMING','COMPANION_READY','MANUAL_LIVE')) {throw 'Platform output is active; no service was stopped'}}
if($status.active_request){throw 'Speech is active; no service was stopped'}
if($status.broadcast.state -eq 'LIVE') {
  $body=@{broadcast_id=$status.broadcast.broadcast_id;expected_revision=$status.broadcast.revision}|ConvertTo-Json -Compress
  Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/broadcast/pause' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 5|Out-Null
}
$registryPath=Join-Path $rootPath 'state\naimei\processes\services.json'
$registry=Get-Content -Raw -Encoding UTF8 -LiteralPath $registryPath|ConvertFrom-Json
$allProcesses=@(Get-CimInstance Win32_Process)
$verifiedPids=@()
foreach($name in @('bridge','studio')) {
  $entry=$registry.$name
  if($entry.root -ne $rootPath){throw "Unowned $name process; nothing else was stopped"}
  $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$entry.pid)
  $script=if($name -eq 'bridge'){'backend\dsh-bridge\server.mjs'}else{'integration.naimei_studio'}
  if($process -and ($process.CommandLine -notlike ('*'+$rootPath+'*') -or $process.CommandLine -notlike ('*'+$script+'*'))) {throw "Process ownership mismatch for $name"}
  # Native venv Python has a launcher and a base-interpreter child. Both
  # must be stopped to ensure the replacement source actually takes effect.
  if($process){
    $verifiedPids+=@($allProcesses|Where-Object {
      $_.CommandLine -and $_.CommandLine.Contains($rootPath) -and $_.CommandLine.Contains($script) -and
      ($_.ProcessId -eq [int]$entry.pid -or $_.ParentProcessId -eq [int]$entry.pid)
    }|ForEach-Object {$_.ProcessId})
  }
}
foreach($taskPid in @($verifiedPids|Select-Object -Unique)) {
  if(Get-Process -Id $taskPid -ErrorAction SilentlyContinue){Stop-Process -Id $taskPid}
}
$python='C:\dev\虚拟数字人直播\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe'
$logs=Join-Path $rootPath 'state\naimei'
$empty=Join-Path $logs 'empty.stdin'
[IO.File]::WriteAllText($empty,'')
$process=Start-Process -FilePath $python -ArgumentList @('-X','utf8','-B',(Join-Path $rootPath 'scripts\start_naimei.py'),'--root',$rootPath) -WorkingDirectory $rootPath -WindowStyle Hidden -RedirectStandardInput $empty -RedirectStandardOutput (Join-Path $logs 'reload.stdout.log') -RedirectStandardError (Join-Path $logs 'reload.stderr.log') -PassThru
@{launcher_pid=$process.Id;preserved=@('FlashHead8030','primary9891','fallback9892','ComfyUI8188');public_broadcast=$false}|ConvertTo-Json -Compress
