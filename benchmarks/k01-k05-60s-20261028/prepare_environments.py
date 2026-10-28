"""Install selected-backend dependencies only in isolated native venvs; CPU smoke checks."""
import os,sys,time,json,subprocess,traceback
from pathlib import Path
R=Path('C:/dev/虚拟数字人直播');W=R/'operations/k01-k05-60s-20261028';O=R/'outputs/lipsync-k01-k05-60s-20261028'
state={};env=os.environ.copy();env.update(PIP_CACHE_DIR=str(R/'cache/lipsync-benchmark/pip'),PYTHONUTF8='1',PYTHONNOUSERSITE='1',PIP_CONFIG_FILE=os.devnull,NO_PROXY='*',no_proxy='*')
for key in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','PIP_PROXY']:env.pop(key,None)
def save():
 tmp=O/'environments.json.tmp';tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,O/'environments.json')
for name,packages in [('feather',['onnxruntime==1.23.2']),('latent',['diffusers==0.32.2','transformers==4.48.0','omegaconf==2.3.0','decord==0.6.0','kornia==0.8.0','ffmpeg-python==0.2.0','imageio-ffmpeg==0.5.1','lpips==0.1.4','imageio==2.31.1','matplotlib==3.10.7'])]:
 start=time.perf_counter();dest=R/'runtime/lipsync-benchmark'/name;python=dest/'Scripts/python.exe';log=W/f'environment-{name}.log'
 try:
  if not python.exists():subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(dest)],check=True)
  shared=R/'runtime/livetalking/Lib/site-packages'
  (dest/'Lib/site-packages/benchmark-shared-runtime.pth').write_text('import sys; sys.path.append('+json.dumps(str(shared),ensure_ascii=True)+')\n',encoding='ascii')
  with log.open('ab') as output:
   for index_url in ['https://pypi.org/simple','https://pypi.tuna.tsinghua.edu.cn/simple']:
    code=subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','--retries','1','--timeout','20','--index-url',index_url,*packages],stdout=output,stderr=output,env=env,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW).returncode
    if code==0:break
   if code:raise RuntimeError('Selected-backend dependency installation failed; see environment log')
   imports='import torch,torchvision,cv2,numpy,soundfile;import onnxruntime' if name=='feather' else 'import torch,torchvision,diffusers,transformers,decord,kornia,omegaconf,librosa,imageio,matplotlib;from diffusers import AutoencoderKL,DDIMScheduler'
   subprocess.run([str(python),'-c',imports],stdout=output,stderr=output,env=env,check=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
  state[name]={'ready':True,'python':str(python),'seconds':time.perf_counter()-start};save()
 except Exception:state[name]={'ready':False,'error':traceback.format_exc()};save()
