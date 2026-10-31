$ErrorActionPreference='Stop'
$root='C:\dev\虚拟数字人直播\naimei'
$voice=Join-Path $root 'assets\naimei\live-v1\voice'
$history=Join-Path $root 'outputs\archives\nmv-draft-20261031'
if(-not (Test-Path -LiteralPath $history)){
 if(-not ([IO.Path]::GetFullPath($history).StartsWith($root+'\outputs\archives\'))){throw 'Archive path outside Naimei'}
 Copy-Item -LiteralPath $voice -Destination $history -Recurse
}
$python='C:\dev\虚拟数字人直播\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe'
$probe=@'
from pathlib import Path
import json
root=Path('C:/dev/虚拟数字人直播/src/tts-benchmark')
records=[]
for name in ['omnivoice','f5']:
    for path in (root/name).rglob('*.py'):
        if any(x in path.parts for x in ['.git','__pycache__']):continue
        lines=path.read_text('utf-8',errors='replace').splitlines()
        hits=[line.strip()[:180] for line in lines if line.startswith('class OmniVoice') or (name=='f5' and ('self.ema_model =' in line or 'class F5TTS' in line))]
        if hits:records.append({'file':path.relative_to(root).as_posix(),'lines':hits[:4]})
        if len(records)>=6:break
print(json.dumps({'draft_preserved':True,'model_api':records},ensure_ascii=False))
'@
& $python -X utf8 -B -c $probe
