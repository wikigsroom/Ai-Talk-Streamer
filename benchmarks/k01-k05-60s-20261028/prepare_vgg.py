"""Fetch only the original FeatherTalk trainer's required torchvision VGG19 loss weights."""
import urllib.request,hashlib,os,time,json,traceback
from pathlib import Path
R=Path('C:/dev/虚拟数字人直播');O=R/'outputs/lipsync-k01-k05-60s-20261028';p=R/'cache/lipsync-benchmark/torch/hub/checkpoints/vgg19-dcbb9e9d.pth';p.parent.mkdir(parents=True,exist_ok=True)
def report(d):
 temp=O/'vgg-setup.json.tmp';temp.write_text(json.dumps(d,indent=2),encoding='utf-8');os.replace(temp,O/'vgg-setup.json')
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(8*2**20),b''):h.update(chunk)
 return h.hexdigest()
try:
 if p.exists() and digest(p).startswith('dcbb9e9d'):report({'ready':True,'existing':True,'bytes':p.stat().st_size,'sha256':digest(p)})
 else:
  url='https://download.pytorch.org/models/vgg19-dcbb9e9d.pth';part=p.with_suffix('.pth.part');offset=part.stat().st_size if part.exists() else 0;headers={'User-Agent':'Mozilla/5.0'}
  if offset:headers['Range']=f'bytes={offset}-'
  op=urllib.request.build_opener(urllib.request.ProxyHandler({}));last=0
  with op.open(urllib.request.Request(url,headers=headers),timeout=45) as response:
   if response.status!=206:offset=0
   total=offset+int(response.headers['Content-Length'])
   with part.open('ab' if offset else 'wb') as out:
    for chunk in iter(lambda:response.read(1024*1024),b''):
     out.write(chunk)
     if time.monotonic()-last>10:out.flush();report({'ready':False,'downloaded_bytes':part.stat().st_size,'expected_bytes':total,'required_by':'upstream FeatherTalk perceptual training loss'});last=time.monotonic()
  sha=digest(part)
  if not sha.startswith('dcbb9e9d') or part.stat().st_size!=total:raise RuntimeError('Official VGG19 weight length/hash check failed')
  part.replace(p);report({'ready':True,'bytes':p.stat().st_size,'sha256':sha,'source':url,'required_by':'upstream FeatherTalk perceptual training loss'})
except Exception:report({'ready':False,'error':traceback.format_exc()});raise
