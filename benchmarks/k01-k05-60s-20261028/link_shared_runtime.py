"""Expose existing native Torch packages to benchmark-only venvs; production stays untouched."""
import json,subprocess,sys
from pathlib import Path
R=Path('C:/dev/虚拟数字人直播');O=R/'outputs/lipsync-k01-k05-60s-20261028'
shared=R/'runtime/livetalking/Lib/site-packages'
if not shared.is_dir():raise RuntimeError('Expected existing production package directory is absent')
result={}
for name in ['feather','latent']:
    folder=R/'runtime/lipsync-benchmark'/name
    site=folder/'Lib/site-packages';site.mkdir(parents=True,exist_ok=True)
    # Python 3.10 reads .pth using the Windows locale: keep the file ASCII only.
    (site/'benchmark-shared-runtime.pth').write_text('import sys; sys.path.append('+json.dumps(str(shared),ensure_ascii=True)+')\n',encoding='ascii')
    probe="import torch,sys,json,importlib.metadata as m;print(json.dumps({'torch':torch.__version__,'torch_file':torch.__file__,'packages':{n:m.version(n) for n in ['torch','torchvision','transformers','diffusers','sympy','packaging','tokenizers','safetensors']}}))"
    proc=subprocess.run([str(folder/'Scripts/python.exe'),'-X','utf8','-c',probe],capture_output=True,text=True,encoding='utf-8',timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    result[name]={'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,'shared_site':str(shared)}
(O/'runtime-link.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
