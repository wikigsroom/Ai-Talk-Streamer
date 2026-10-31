$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
[Net.WebRequest]::DefaultWebProxy=$null
try {
 $root='C:\dev\虚拟数字人直播\naimei'
 $health=Invoke-RestMethod 'http://127.0.0.1:9892/health' -TimeoutSec 5
 if($health.character_id -ne 'naimei' -or $health.voice_id -ne 'F07' -or $health.busy){throw 'Only the quiet owned F07 worker can be reloaded'}
 $registry=Get-Content -LiteralPath (Join-Path $root 'state\naimei\processes\services.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $entry=$registry.'voice-fallback'
 if($entry.root -ne $root){throw 'F07 registry ownership mismatch'}
 $all=@(Get-CimInstance Win32_Process)
 $process=@($all|Where-Object {$_.ProcessId -eq [int]$entry.pid})
 if($process.Count -ne 1 -or -not $process[0].CommandLine.Contains($root) -or -not $process[0].CommandLine.Contains('integration.naimei_voice_worker')){throw 'F07 process ownership mismatch'}
 $tree=@($all|Where-Object {$_.CommandLine -and $_.CommandLine.Contains($root) -and $_.CommandLine.Contains('integration.naimei_voice_worker') -and ($_.ProcessId -eq [int]$entry.pid -or $_.ParentProcessId -eq [int]$entry.pid)})
 foreach($proc in $tree){if(Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue){Stop-Process -Id $proc.ProcessId}}
 $python='C:\dev\虚拟数字人直播\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe'
 $code=@'
from pathlib import Path
import json, os, subprocess
root=Path(r'C:\dev\虚拟数字人直播\naimei')
python=Path(r'C:\dev\虚拟数字人直播\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe')
state=root/'state/naimei'
with (state/'approved-voice-start.stdout.log').open('ab') as out, (state/'approved-voice-start.stderr.log').open('ab') as err:
 p=subprocess.Popen([str(python),'-X','utf8','-B',str(root/'scripts/start_naimei.py'),'--root',str(root)],cwd=root,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=0x08000000,env=dict(os.environ))
print(json.dumps({'launcher_pid':p.pid,'preserved':['O07','FlashHead8030','ComfyUI8188']}))
'@
 & $python -X utf8 -B -c $code
 if($LASTEXITCODE -ne 0){throw 'Native launcher failed'}
}catch{@{failure=$_.Exception.Message}|ConvertTo-Json -Compress;exit 1}
