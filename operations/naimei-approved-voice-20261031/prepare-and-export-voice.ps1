$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$python='C:\dev\虚拟数字人直播\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe'
$code=@'
from pathlib import Path
import json, os, subprocess
root=Path(r'C:\dev\虚拟数字人直播\naimei')
state=root/'state/naimei'
pipeline=state/'approved-voice-pipeline.py'
source=r'''
from pathlib import Path
import hashlib, json, runpy, sys, traceback, urllib.request, urllib.parse, uuid, zipfile
root=Path(r'C:\dev\虚拟数字人直播\naimei')
state=root/'state/naimei'
voice=root/'assets/naimei/live-v1/voice'
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
result={'complete':False,'public_broadcast':False}
try:
 with http.open('http://127.0.0.1:8188/queue',timeout=5) as response: queue=json.load(response)
 if queue['queue_running'] or queue['queue_pending']: raise RuntimeError('UNRELATED_GPU_TASK_ACTIVE')
 archive=root/'outputs/archives/nmv-draft-20261031'
 for name in ['NMV01-reference.wav','NMV02-reference.wav','NMV03-reference.wav','fallback/NMV01-f5-check.wav','fallback/NMV01-f5-check.json']:
  target=(voice/name).resolve()
  if not target.is_relative_to(voice.resolve()): raise RuntimeError('RETIRE_SCOPE_INVALID')
  if target.exists():
   backup=archive/name
   if not backup.is_file() or hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(backup.read_bytes()).digest(): raise RuntimeError('NMV_HISTORY_BACKUP_MISMATCH')
   target.unlink()
 for script in ['prepare_naimei_auditions.py','prepare_naimei_speech.py','verify_naimei_fallback.py','verify_naimei_voice_failover.py']:
  sys.argv=[str(root/'scripts'/script),'--root',str(root)]
  runpy.run_path(sys.argv[0],run_name='__main__')
 target=state/'approved-voice-assets.zip'
 records=[]
 with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as bundle:
  for path in sorted(voice.rglob('*')):
   if not path.is_file(): continue
   name=path.relative_to(root).as_posix()
   data=path.read_bytes()
   records.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
   bundle.writestr(name,data)
  bundle.writestr('_voice-transfer-manifest.json',json.dumps(records,ensure_ascii=False).encode())
 data=target.read_bytes()
 sha=hashlib.sha256(data).hexdigest()
 boundary='----NaimeiApprovedVoice'+uuid.uuid4().hex
 body=b''
 for key,value in [('type','input'),('subfolder','naimei-approved-voice'),('overwrite','false')]:
  body+=('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode()
 body+=('--'+boundary+'\r\nContent-Disposition: form-data; name="image"; filename="'+sha[:16]+'-voice-assets.zip"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+data
 body+=('\r\n--'+boundary+'--\r\n').encode()
 with http.open(urllib.request.Request('http://127.0.0.1:8188/upload/image',data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary}),timeout=30) as response: upload=json.load(response)
 result.update(complete=True,files=len(records),bytes=len(data),sha256=sha,url='http://192.168.196.209:8188/view?'+urllib.parse.urlencode({'type':'input','subfolder':upload['subfolder'],'filename':upload['name']}))
except Exception as exc:
 result['failure']=type(exc).__name__+': '+str(exc)
 traceback.print_exc()
(state/'approved-voice-pipeline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
'''
pipeline.write_text(source,'utf-8')
python=Path(r'C:\dev\虚拟数字人直播\runtime\livetalking\Scripts\python.exe')
with (state/'approved-voice-pipeline.stdout.log').open('ab') as out, (state/'approved-voice-pipeline.stderr.log').open('ab') as err:
 p=subprocess.Popen([str(python),'-X','utf8','-B',str(pipeline)],cwd=root,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=0x08000000,env=dict(os.environ,PYTHONPATH=str(root)))
print(json.dumps({'voice_asset_pipeline_pid':p.pid,'expected_speech_assets':25,'auditions':2}))
'@
& $python -X utf8 -B -c $code
if($LASTEXITCODE -ne 0){throw 'Approved voice pipeline launch failed'}
