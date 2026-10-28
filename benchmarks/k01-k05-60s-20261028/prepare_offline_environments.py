"""Transfer hash-checked wheels over the overlay; install only in benchmark venvs."""
import os,sys,time,json,hashlib,subprocess,traceback,urllib.request,concurrent.futures
from pathlib import Path
import psutil
R=Path('C:/dev/虚拟数字人直播');W=R/'operations/k01-k05-60s-20261028';O=R/'outputs/lipsync-k01-k05-60s-20261028'
cache=R/'cache/lipsync-benchmark/wheelhouse';cache.mkdir(parents=True,exist_ok=True)
op=urllib.request.build_opener(urllib.request.ProxyHandler({}));url='http://192.168.196.87:8038/'
state={'started_at':time.time(),'ready':False,'files':{},'replaced_only_task_installer_pids':[]};envstate={}
def save():
    tmp=O/'offline-environment-progress.json.tmp';tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,O/'offline-environment-progress.json')
try:
    manifest=json.load(op.open(url+'manifest.json',timeout=15))
    # Stop the obsolete network installer only after its replacement source is reachable.
    # Never match bootstrap/model download, ComfyUI, production or unrelated MCP jobs.
    for p in psutil.process_iter(['pid','cmdline']):
        try:
            cmd=p.info['cmdline'] or []
            if not any(Path(a).name=='bench_launch.py' and str(W) in a for a in cmd) or 'prepare_environments.py' not in cmd:continue
            for child in reversed(p.children(recursive=True)):
                try:child.terminate();child.wait(timeout=8);state['replaced_only_task_installer_pids'].append(child.pid)
                except psutil.NoSuchProcess:pass
            p.terminate();p.wait(timeout=8);state['replaced_only_task_installer_pids'].append(p.pid)
        except psutil.NoSuchProcess:continue
    save()
    def fetch(item):
        name=item['name'];assert Path(name).name==name and (name.endswith('.whl') or name.endswith('.tar.gz'))
        target=cache/name
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:
            data=op.open(url+name,timeout=90).read()
            if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:raise RuntimeError('Wheel hash mismatch: '+name)
            target.write_bytes(data)
        return name
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for f in concurrent.futures.as_completed([pool.submit(fetch,item) for item in manifest]):state['files'][f.result()]=True;save()
    env=os.environ.copy();env.update(PIP_CACHE_DIR=str(R/'cache/lipsync-benchmark/pip'),PYTHONUTF8='1',PYTHONNOUSERSITE='1',PIP_CONFIG_FILE=os.devnull,NO_PROXY='*',no_proxy='*')
    for key in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','PIP_PROXY']:env.pop(key,None)
    for name,packages in [('feather',['onnxruntime==1.23.2']),('latent',['diffusers==0.32.2','transformers==4.48.0','omegaconf==2.3.0','decord==0.6.0','kornia==0.8.0','ffmpeg-python==0.2.0','imageio-ffmpeg==0.5.1','lpips==0.1.4','imageio==2.31.1','matplotlib==3.10.7'])]:
        state['stage']='install-'+name;save();tick=time.perf_counter();dest=R/'runtime/lipsync-benchmark'/name;python=dest/'Scripts/python.exe'
        shared=R/'runtime/livetalking/Lib/site-packages'
        (dest/'Lib/site-packages/benchmark-shared-runtime.pth').write_text('import sys; sys.path.append('+json.dumps(str(shared),ensure_ascii=True)+')\n',encoding='ascii')
        log=W/f'environment-offline-{name}.log'
        with log.open('ab') as output:
            subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','--no-index','--find-links',str(cache),'--no-build-isolation',*packages],stdout=output,stderr=output,env=env,check=True,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            imports='import torch,torchvision,cv2,numpy,soundfile;import onnxruntime' if name=='feather' else 'import torch,torchvision,diffusers,transformers,decord,kornia,omegaconf,librosa,imageio,matplotlib;from diffusers import AutoencoderKL,DDIMScheduler'
            subprocess.run([str(python),'-X','utf8','-c',imports],stdout=output,stderr=output,env=env,check=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        envstate[name]={'ready':True,'python':str(python),'seconds':time.perf_counter()-tick,'dependency_source':'overlay hash-checked wheelhouse','shared_torch':'existing native production library, read-only'}
        temp=O/'environments.json.tmp';temp.write_text(json.dumps(envstate,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,O/'environments.json')
    state.update(ready=True,stage='completed',seconds=time.time()-state['started_at']);save()
except Exception:
    state['error']=traceback.format_exc();save();raise
