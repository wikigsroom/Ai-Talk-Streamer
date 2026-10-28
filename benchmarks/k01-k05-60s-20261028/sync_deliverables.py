"""Receive real original files over the overlay with per-file SHA256 checking."""
import json,urllib.request,urllib.parse,hashlib,os,sys,time
from pathlib import Path,PurePosixPath
P=Path(__file__).resolve().parent;O=P.parent.parent/'outputs/lipsync-k01-k05-60s-20261028'
base='http://192.168.196.209:8035/'
op=urllib.request.build_opener(urllib.request.ProxyHandler({}));O.mkdir(parents=True,exist_ok=True)
with op.open(base+'delivery-manifest.json',timeout=20) as r:data=json.load(r)
received=0;reused=0
for item in data['files']:
 rel=PurePosixPath(item['path'])
 if rel.is_absolute() or '..' in rel.parts:raise ValueError('Invalid review artifact path')
 dest=O.joinpath(*rel.parts)
 if dest.exists() and dest.stat().st_size==item['bytes']:
  with dest.open('rb') as f:found=hashlib.file_digest(f,'sha256').hexdigest()
  if found==item['sha256']:reused+=1;continue
 dest.parent.mkdir(parents=True,exist_ok=True);tmp=dest.with_suffix(dest.suffix+'.receiving')
 for attempt in range(3):
  try:
   digest=hashlib.sha256();size=0
   with op.open(base+urllib.parse.quote(item['path'],safe='/'),timeout=45) as r,tmp.open('wb') as f:
    while block:=r.read(1024*1024):f.write(block);digest.update(block);size+=len(block)
   if size!=item['bytes'] or digest.hexdigest()!=item['sha256']:raise RuntimeError('Artifact content does not match manifest: '+item['path'])
   os.replace(tmp,dest);received+=1;break
  except Exception:
   if attempt==2:raise
   time.sleep(2)
 if received%10==0:print(json.dumps({'received':received,'reused':reused,'last':item['path']}),flush=True)
(O/'delivery-manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
receipt={'complete':data['complete'],'verified_hashes':received+reused,'new_files':received,'unchanged_files':reused,'manifest_bytes':data['bytes'],'received_at':time.time(),'source':base,'archive_created':False,'model_and_training_cache_excluded':True}
(O/'delivery-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(receipt),flush=True)
