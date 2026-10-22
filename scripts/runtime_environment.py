"""Project-confined runtime paths, with offline models and local media services."""
from pathlib import Path
import os
ROOT=Path(__file__).resolve().parents[1]

def environment(offline=True,cpu=False):
    env=os.environ.copy()
    locations={'HF_HOME':'cache/huggingface','HUGGINGFACE_HUB_CACHE':'cache/huggingface/hub',
        'TORCH_HOME':'cache/torch','NLTK_DATA':'cache/nltk_data','FTLANG_CACHE':'cache/fasttext',
        'MODELSCOPE_CACHE':'cache/modelscope','XDG_CACHE_HOME':'cache','MPLCONFIGDIR':'cache/matplotlib',
        'NUMBA_CACHE_DIR':'cache/numba','GRADIO_TEMP_DIR':'cache/gradio','TEMP':'cache/tmp','TMP':'cache/tmp'}
    for key,relative in locations.items():
        path=ROOT/relative;path.mkdir(parents=True,exist_ok=True);env[key]=str(path)
    env.update({'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1',
                'HF_HUB_DISABLE_TELEMETRY':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
                'OPENBLAS_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','KMP_BLOCKTIME':'0',
                'GRADIO_ANALYTICS_ENABLED':'False','DO_NOT_TRACK':'1','AVATAR_GPU_ISOLATION':'1',
                'HF_HUB_OFFLINE':'1' if offline else '0','TRANSFORMERS_OFFLINE':'1' if offline else '0',
                'NO_PROXY':'localhost,127.0.0.1','no_proxy':'localhost,127.0.0.1'})
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        env.pop(key,None)
    # A shared build supplies the FFmpeg DLLs required by TorchCodec on Windows.
    bins=[]
    for name in ('ffmpeg7-shared','ffmpeg-shared','ffmpeg'):
        folder=ROOT/'tools'/name
        if folder.exists():
            exe=next(folder.rglob('ffmpeg.exe'),None)
            if exe:bins.append(str(exe.parent))
    env['PATH']=';'.join(bins+[env.get('PATH','')])
    env['PYTHONPATH']=str(ROOT/'scripts')
    if cpu:env['CUDA_VISIBLE_DEVICES']='-1'
    channel=ROOT/'configs/channel.env'
    if channel.exists():
        for line in channel.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip() or line.lstrip().startswith('#') or '=' not in line:continue
            key,value=line.split('=',1);key=key.strip();value=value.strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
            if key.startswith('AVATAR_'):env[key]=value
    return env
