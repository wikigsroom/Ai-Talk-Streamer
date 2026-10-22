"""Fetch pinned public sources and portable native tools. No model execution."""
from pathlib import Path
import concurrent.futures
import datetime
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / '.setup'
DL = ROOT / 'downloads'
for p in [SETUP, DL, ROOT/'src', ROOT/'tools', ROOT/'cache', ROOT/'logs',ROOT/'runtime',ROOT/'models',ROOT/'assets']:
    p.mkdir(parents=True,exist_ok=True)
PROXY=os.getenv('AVATAR_DOWNLOAD_PROXY', '').strip()
opener=urllib.request.build_opener(urllib.request.ProxyHandler({'http':PROXY,'https':PROXY}) if PROXY else urllib.request.ProxyHandler())

def event(stage,**kwargs):
    item={'at':datetime.datetime.now().astimezone().isoformat(),'stage':stage,**kwargs}
    with (SETUP/'bootstrap.events.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(item,ensure_ascii=False)+'\n')
    print(json.dumps(item,ensure_ascii=False),flush=True)

def request(url):
    return opener.open(urllib.request.Request(url,headers={'User-Agent':'avatar-local-deployment','Accept':'application/vnd.github+json'}),timeout=45)

def api(url):
    for attempt in range(4):
        try:
            with request(url) as r: return json.load(r)
        except Exception:
            if attempt==3: raise
            time.sleep(2+attempt*2)

def download(url,target,digest=None):
    if target.exists() and target.stat().st_size>0:
        if digest is None or hashlib.sha256(target.read_bytes()).hexdigest()==digest:
            return target
    temp=target.with_name(target.name+'.part')
    for attempt in range(5):
        try:
            event('download_start',url=url,file=str(target))
            with request(url) as r, temp.open('wb') as f:
                while block:=r.read(4*1024*1024): f.write(block)
            actual=hashlib.sha256(temp.read_bytes()).hexdigest()
            if digest and actual!=digest: raise ValueError('SHA256 mismatch for '+target.name)
            temp.replace(target)
            event('download_complete',file=str(target),bytes=target.stat().st_size,sha256=actual)
            return target
        except Exception as exc:
            event('download_retry',file=str(target),attempt=attempt+1,error=str(exc))
            if attempt==4: raise
            time.sleep(3+attempt*2)

def extract_source(name,repo):
    locks=json.loads((ROOT/'configs/sources.lock.json').read_text(encoding='utf-8'))
    sha=locks[name]['sha']
    if locks[name]['repo'] != repo: raise RuntimeError('Source lock repository mismatch')
    archive=download('https://codeload.github.com/'+repo+'/zip/'+sha,DL/(name+'-'+sha[:12]+'.zip'))
    dest=ROOT/'src'/name
    marker=SETUP/(name+'.source.json')
    if dest.exists():
        if not marker.exists() or json.loads(marker.read_text(encoding='utf-8')).get('sha') != sha:
            raise RuntimeError('Existing source does not match the recorded lock; preserve it and use a fresh project directory: '+name)
    if not dest.exists():
        with zipfile.ZipFile(archive) as z:
            top=z.namelist()[0].split('/')[0]
            z.extractall(ROOT/'src')
        (ROOT/'src'/top).rename(dest)
    record={'repo':repo,'sha':sha,'directory':str(dest),'archive':str(archive)}
    (SETUP/(name+'.source.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    event('source_ready',**record)
    return record

def tool_release(name,repo,predicate,tag='latest'):
    release=api('https://api.github.com/repos/'+repo+'/releases/'+('latest' if tag=='latest' else 'tags/'+tag))
    asset=next(a for a in release['assets'] if predicate(a['name']))
    expected=(asset.get('digest') or '').removeprefix('sha256:') or None
    archive=download(asset['browser_download_url'],DL/asset['name'],expected)
    dest=ROOT/'tools'/name
    marker=dest/'.extracted'
    if not marker.exists():
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as z: z.extractall(dest)
        marker.write_text(release['tag_name'],encoding='utf-8')
    record={'name':name,'repo':repo,'tag':release['tag_name'],'asset':asset['name'],'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'upstream_digest':expected,'directory':str(dest)}
    (SETUP/(name+'.tool.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    event('tool_ready',**record)
    return record

def main():
    jobs=[
      ('LiveTalking',lambda:extract_source('LiveTalking','lipku/LiveTalking')),
      ('GPT-SoVITS',lambda:extract_source('GPT-SoVITS','RVC-Boss/GPT-SoVITS')),
      ('uv',lambda:tool_release('uv','astral-sh/uv',lambda n:n=='uv-x86_64-pc-windows-msvc.zip')),
      ('git',lambda:tool_release('git','git-for-windows/git',lambda n:n.startswith('MinGit-') and n.endswith('-64-bit.zip') and 'busybox' not in n.lower())),
      ('ffmpeg',lambda:tool_release('ffmpeg','BtbN/FFmpeg-Builds',lambda n:n=='ffmpeg-master-latest-win64-gpl.zip')),
      ('obs',lambda:tool_release('obs','obsproject/obs-studio',lambda n:n.lower().endswith('-windows-x64.zip'),'31.1.2')),
    ]
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(job):name for name,job in jobs}
        for future in concurrent.futures.as_completed(futures):
            name=futures[future]
            try: results.append({'name':name,'ok':True,'result':future.result()})
            except Exception as exc:
                event('task_failed',name=name,error=str(exc))
                results.append({'name':name,'ok':False,'error':str(exc)})
    (SETUP/'bootstrap.result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    event('bootstrap_finished',ok=all(r['ok'] for r in results))
    if not all(r['ok'] for r in results):raise SystemExit(1)

if __name__=='__main__': main()
