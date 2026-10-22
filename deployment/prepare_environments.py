"""Create project-confined native Windows Python environments and install deps."""
from pathlib import Path
import datetime,json,os,subprocess,sys,tarfile,urllib.request
ROOT=Path(__file__).resolve().parents[1]
SETUP=ROOT/'.setup'
env=os.environ.copy()
proxy=os.getenv('AVATAR_DOWNLOAD_PROXY', '').strip()
if proxy:
    for key in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']: env[key]=proxy
env['NO_PROXY']='localhost,127.0.0.1'
for key,rel in {'UV_CACHE_DIR':'cache/uv','UV_PYTHON_INSTALL_DIR':'runtime/python','UV_PYTHON_BIN_DIR':'runtime/bin','PIP_CACHE_DIR':'cache/pip','MAMBA_ROOT_PREFIX':'runtime/mamba','TEMP':'cache/tmp','TMP':'cache/tmp','HF_HOME':'cache/huggingface','TORCH_HOME':'cache/torch','NLTK_DATA':'cache/nltk_data'}.items():
    path=ROOT/rel;path.mkdir(parents=True,exist_ok=True);env[key]=str(path)
uv=next((ROOT/'tools/uv').rglob('uv.exe'))
git=next((ROOT/'tools/git').rglob('git.exe'))
env['PATH']=str(git.parent)+';'+env['PATH']

def run(args,cwd=ROOT):
    print(json.dumps({'at':datetime.datetime.now().astimezone().isoformat(),'run':[str(a) for a in args]},ensure_ascii=False),flush=True)
    subprocess.run([str(a) for a in args],cwd=cwd,env=env,check=True)

def main():
    run([uv,'python','install','3.10'])
    native=next(p for p in (ROOT/'runtime/python').glob('cpython-3.10.*-windows-x86_64-none/python.exe'))
    for name in ['livetalking','tts']:
        path=ROOT/'runtime'/name
        python=path/'Scripts/python.exe'
        works=python.exists() and subprocess.run([str(python),'-c','import sys; print(sys.version)'],env=env,capture_output=True).returncode==0
        if not works:
            # CPython's native launcher supports this Chinese project path;
            # uv's current Windows trampoline does not resolve it correctly.
            run([native,'-m','venv','--clear',path])
        run([uv,'pip','install','--python',python,'pip','setuptools==75.8.2','wheel'])
    live=ROOT/'runtime/livetalking/Scripts/python.exe'
    tts=ROOT/'runtime/tts/Scripts/python.exe'
    for python in [live,tts]:
        run([uv,'pip','install','--python',python,'torch==2.9.1','torchvision==0.24.1','torchaudio==2.9.1','--index-url','https://download.pytorch.org/whl/cu128'])
    constraints=SETUP/'windows-constraints.txt'
    constraints.write_text('numpy==1.26.4\ntransformers==4.51.3\nopencv-python-headless==4.11.0.86\nopencv-python==4.11.0.86\ntorch==2.9.1\ntorchaudio==2.9.1\ntorchvision==0.24.1\ngradio==4.44.1\ngradio-client==1.3.0\n',encoding='utf-8')
    live_req=ROOT/'src/LiveTalking/requirements.txt'
    run([uv,'pip','install','--python',live,'-r',live_req,'-c',constraints,'diffusers==0.35.1','accelerate','requests','huggingface_hub','imageio-ffmpeg','pyvirtualcam','psutil','rich','resampy','dlib-bin==20.0.1.post1','face-recognition-models==0.3.0'])
    tts_req=ROOT/'src/GPT-SoVITS/requirements.txt'
    # The upstream option forces an opencc source build even when a native wheel exists.
    windows_req=SETUP/'tts-requirements.windows.txt'
    windows_req.write_text('\n'.join(line for line in tts_req.read_text(encoding='utf-8').splitlines() if not line.startswith(('--no-binary','jieba_fast','pyopenjtalk')))+'\npyopenjtalk-plus\n',encoding='utf-8')
    run([uv,'pip','install','--python',tts,'-r',windows_req,'-c',constraints,'torchcodec==0.8.1','jieba==0.42.1','requests','setuptools==75.8.2','wheel'])
    run([uv,'pip','install','--python',tts,'-r',ROOT/'src/GPT-SoVITS/extra-req.txt','-c',constraints])
    (SETUP/'environments.result.json').write_text(json.dumps({'ok':True,'python':'3.10','torch':'2.9.1+cu128','paths':{'livetalking':str(live),'tts':str(tts)}},ensure_ascii=False,indent=2),encoding='utf-8')
    print('ENVIRONMENT_DEPENDENCIES_INSTALLED',flush=True)

if __name__=='__main__':
    try: main()
    except Exception as exc:
        (SETUP/'environments.error.json').write_text(json.dumps({'error':str(exc)},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
