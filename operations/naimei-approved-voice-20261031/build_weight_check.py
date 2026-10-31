from pathlib import Path
import json

root = Path(__file__).resolve().parents[2]
lock = json.loads((root / 'configs/releases/o07-f07-runtime-lock.json').read_text('utf-8'))
records = [v for v in lock['model_files'] if v['path'].endswith(
    ('.safetensors', '.bin', 'vocab.txt', 'config.json', 'config.yaml', 'tokenizer.json'))]
code = r"""from pathlib import Path
import json, hashlib
expected = EXPECTED
root=Path(r'C:\dev\虚拟数字人直播')
records=[]
for item in expected:
 path=root/item['path']
 digest=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(16*1024*1024),b''):digest.update(chunk)
 actual=digest.hexdigest()
 records.append(dict(path=item['path'],bytes=path.stat().st_size,sha256=actual,match=actual==item['sha256'] and path.stat().st_size==item['bytes']))
print(json.dumps(dict(model_files=records,all_matched=all(x['match'] for x in records)),ensure_ascii=False))
""".replace('EXPECTED', repr(records))
command = "$ErrorActionPreference='Stop'\n$python='C:\\dev\\虚拟数字人直播\\runtime\\python\\cpython-3.10.22-windows-x86_64-none\\python.exe'\n$code=@'\n" + code + "'@\n& $python -X utf8 -B -c $code\n"
(Path(__file__).parent / 'verify-model-files.ps1').write_text(command, 'utf-8')
print(json.dumps({'model_files': len(records)}))
