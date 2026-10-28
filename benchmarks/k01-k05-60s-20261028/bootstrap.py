"""Prepare only selected K03-K05 native sources, weights and isolated dependencies."""
from pathlib import Path
import concurrent.futures,hashlib,json,os,shutil,subprocess,sys,threading,time,traceback,urllib.request,zipfile
R=Path('C:/dev/虚拟数字人直播');W=R/'operations/k01-k05-60s-20261028';O=R/'outputs/lipsync-k01-k05-60s-20261028'
plan=json.loads((W/'download-plan.json').read_text(encoding='utf-8'));lock=threading.Lock();state={}
def update(key,value):
 with lock:
  state[key]=value;p=O/'setup-progress.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
 print(json.dumps({key:value},ensure_ascii=False),flush=True)
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def fetch(urls,target,expected=None,expected_sha=None):
 target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists() and (not expected or target.stat().st_size==expected) and (not expected_sha or sha(target)==expected_sha):return
 part=target.with_name(target.name+'.part');error=None
 for url in urls:
  for proxy in [None,'http://127.0.0.1:10808','http://192.168.10.120:10808']:
   try:
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({} if proxy is None else {'http':proxy,'https':proxy}))
    offset=part.stat().st_size if part.exists() else 0
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0',**({'Range':f'bytes={offset}-'} if offset else {})})
    with opener.open(req,timeout=35) as response:
     append=offset and response.status==206
     with part.open('ab' if append else 'wb') as stream:
      last=time.monotonic()
      while True:
       chunk=response.read(2**20)
       if not chunk:break
       stream.write(chunk)
       if time.monotonic()-last>10:
        stream.flush();update(str(target.relative_to(R)),{'downloading_bytes':part.stat().st_size,'expected_bytes':expected});last=time.monotonic()
    if expected and part.stat().st_size!=expected:raise RuntimeError(f'Length mismatch {part.stat().st_size} != {expected}')
    if expected_sha and sha(part)!=expected_sha:raise RuntimeError('SHA256 mismatch')
    part.replace(target);update(str(target.relative_to(R)),{'ready':True,'bytes':target.stat().st_size,'sha256':sha(target)});return
   except Exception as e:error=e;update(str(target.relative_to(R)),{'retry_error':str(e),'proxy':proxy})
 raise RuntimeError(str(error))
def model(item):
 key='latent' if 'LatentSync' in item['repo'] else 'wav2lip';target=R/'models/lipsync-benchmark'/key/item['file']
 urls=[f"https://{host}/{item['repo']}/resolve/{item['revision']}/{item['file']}?download=true" for host in ['hf-mirror.com','huggingface.co']]
 fetch(urls,target,item['bytes'],item.get('sha256'))
def source(name,item):
 dest=R/'src/lipsync-benchmark'/name;archive=W/(name+'-source.zip')
 if not (dest/'README.md').exists():
  fetch([f"https://codeload.github.com/{item['repo']}/zip/{item['revision']}"],archive)
  dest.mkdir(parents=True,exist_ok=True)
  with zipfile.ZipFile(archive) as z:
   for info in z.infolist():
    rel=Path(*Path(info.filename).parts[1:])
    if not rel.parts or info.is_dir() or rel.suffix.lower() in ['.mp4','.gif','.webm','.jpg']:continue
    target=(dest/rel).resolve()
    if not target.is_relative_to(dest.resolve()):raise RuntimeError('Unsafe archive path')
    target.parent.mkdir(parents=True,exist_ok=True)
    with z.open(info) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
 (dest/'benchmark-source.json').write_text(json.dumps(item),encoding='utf-8');update('source-'+name,{'ready':True,**item})
def environment(name,packages):
 dest=R/'runtime/lipsync-benchmark'/name;python=dest/'Scripts/python.exe'
 if not python.exists():subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(dest)],check=True)
 log=W/('pip-'+name+'.log')
 with log.open('a',encoding='utf-8') as output:
  env=os.environ.copy();env.update(PIP_CACHE_DIR=str(R/'cache/lipsync-benchmark/pip'),TORCH_HOME=str(R/'cache/lipsync-benchmark/torch'))
  subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','--index-url','https://pypi.org/simple',*packages],env=env,stdout=output,stderr=subprocess.STDOUT,check=True)
 update('environment-'+name,{'ready':True,'python':str(python)})
jobs={}
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
 for item in plan['models']:jobs[ex.submit(model,item)]=item['file']
 for name,item in plan['sources'].items():jobs[ex.submit(source,name,item)]=name
 for f in concurrent.futures.as_completed(jobs):
  try:f.result()
  except Exception: update('failed-'+jobs[f],{'error':traceback.format_exc()})
for name,packages in [('feather',['onnxruntime==1.23.2','tqdm']),('latent',['diffusers==0.32.2','transformers==4.48.0','omegaconf==2.3.0','decord==0.6.0','kornia==0.8.0','ffmpeg-python==0.2.0','imageio-ffmpeg==0.5.1','lpips==0.1.4'])]:
 try:environment(name,packages)
 except Exception:update('failed-environment-'+name,{'error':traceback.format_exc()})
update('completed',True)
