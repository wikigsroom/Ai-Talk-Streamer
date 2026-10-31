$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
[Net.WebRequest]::DefaultWebProxy=$null
try {
 $root='C:\dev\虚拟数字人直播\naimei'
 $origin=Get-Content -LiteralPath (Join-Path $root '.setup\deployment-origin.json') -Raw -Encoding UTF8|ConvertFrom-Json
 if($origin.branch -ne 'naimei' -or -not $origin.verified_source_manifest){throw 'Verified Naimei installation required'}
 $status=Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/status' -TimeoutSec 5
 if($status.health.character_id -ne 'naimei' -or $status.active_request -or $status.broadcast.state -eq 'LIVE'){throw 'Naimei must be paused without active speech'}
 $platform=Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/platforms/status' -TimeoutSec 5
 foreach($row in $platform.outputs){if($row.state -in @('STARTING','STREAMING','COMPANION_READY','MANUAL_LIVE')){throw 'Platform output is active'}}
 $queue=Invoke-RestMethod 'http://127.0.0.1:8188/queue' -TimeoutSec 5
 if($queue.queue_running.Count -or $queue.queue_pending.Count){throw 'Preserve the unrelated GPU task; wait for it to finish'}
 foreach($port in @(9891,9892)){
  $h=Invoke-RestMethod ('http://127.0.0.1:'+$port+'/health') -TimeoutSec 5
  if($h.character_id -ne 'naimei' -or $h.busy){throw 'A voice service is not quiet and owned'}
 }
 $registry=Get-Content -LiteralPath (Join-Path $root 'state\naimei\processes\services.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $all=@(Get-CimInstance Win32_Process)
 $stopping=@()
 foreach($name in @('bridge','studio','voice-primary','voice-fallback')){
  $entry=$registry.$name
  if($entry.root -ne $root){throw ('Unowned process registry: '+$name)}
  $marker=if($name -eq 'bridge'){'backend\dsh-bridge\server.mjs'}elseif($name -eq 'studio'){'integration.naimei_studio'}else{'integration.naimei_voice_worker'}
  $launcher=@($all|Where-Object {$_.ProcessId -eq [int]$entry.pid})
  if($launcher.Count -ne 1 -or -not $launcher[0].CommandLine.Contains($root) -or -not $launcher[0].CommandLine.Contains($marker)){throw ('Process ownership mismatch: '+$name)}
  $tree=@($all|Where-Object {$_.CommandLine -and $_.CommandLine.Contains($root) -and $_.CommandLine.Contains($marker) -and ($_.ProcessId -eq [int]$entry.pid -or $_.ParentProcessId -eq [int]$entry.pid)})
  $stopping+=@($tree|ForEach-Object {$_.ProcessId})
 }
 $python='C:\dev\虚拟数字人直播\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe'
 $check="import sys;sys.path.insert(0,r'C:\dev\虚拟数字人直播\naimei');from integration.naimei_voice_contract import load_profile;p=load_profile(r'C:\dev\虚拟数字人直播\naimei');print(p['default_voice_id'])"
 $checked=& $python -X utf8 -B -c $check
 if($LASTEXITCODE -ne 0 -or $checked -ne 'O07'){throw 'Original voice contract did not validate'}
 foreach($taskPid in @($stopping|Select-Object -Unique)){if(Get-Process -Id $taskPid -ErrorAction SilentlyContinue){Stop-Process -Id $taskPid}}
 $code=@'
from pathlib import Path
import json, os, subprocess
root=Path(r'C:\dev\虚拟数字人直播\naimei')
python=Path(r'C:\dev\虚拟数字人直播\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe')
logs=root/'state/naimei'
with (logs/'approved-voice-start.stdout.log').open('ab') as out, (logs/'approved-voice-start.stderr.log').open('ab') as err:
 p=subprocess.Popen([str(python),'-X','utf8','-B',str(root/'scripts/start_naimei.py'),'--root',str(root)],cwd=root,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=0x08000000,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'))
print(json.dumps({'launcher_pid':p.pid,'preserved':['FlashHead8030','ComfyUI8188','legacy9881/9882'],'public_broadcast':False}))
'@
 & $python -X utf8 -B -c $code
 if($LASTEXITCODE -ne 0){throw 'Native launcher failed'}
} catch {
 @{failure=$_.Exception.Message}|ConvertTo-Json -Compress
 exit 1
}
