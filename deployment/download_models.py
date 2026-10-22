"""Download selected inference assets with upstream file hashes; no inference."""
from pathlib import Path
import concurrent.futures,datetime,hashlib,json,os,shutil,sys,tarfile,threading,time,urllib.parse,urllib.request,zipfile
ROOT=Path(__file__).resolve().parents[1]
SETUP=ROOT/'.setup'
LIVE=ROOT/'src/LiveTalking'
TTS=ROOT/'src/GPT-SoVITS'
PROXY=os.getenv('AVATAR_DOWNLOAD_PROXY', '').strip()
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({'http':PROXY,'https':PROXY}) if PROXY else urllib.request.ProxyHandler())
LOCK=threading.Lock()

def event(stage,**kwargs):
    record={'at':datetime.datetime.now().astimezone().isoformat(),'stage':stage,**kwargs}
    with LOCK:
        with (SETUP/'models.events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
        print(json.dumps(record,ensure_ascii=False),flush=True)

def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(8*1024*1024):h.update(b)
    return h.hexdigest()

def get(url):
    return OPENER.open(urllib.request.Request(url,headers={'User-Agent':'avatar-local-model-preparation'}),timeout=90)

def model_info(repo):
    for attempt in range(4):
        try:
            with get('https://huggingface.co/api/models/'+repo+'?blobs=true') as r:info=json.load(r)
            (SETUP/(repo.replace('/','__')+'.model.json')).write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
            return info
        except Exception:
            if attempt==3:raise
            time.sleep(3)

def download(record):
    target=ROOT/record['local_path'];target.parent.mkdir(parents=True,exist_ok=True)
    expected=record.get('sha256_upstream');size=record.get('size')
    if target.exists() and (size is None or target.stat().st_size==size):
        digest=sha256(target)
        if expected is None or digest==expected:
            event('file_present',path=record['local_path'],bytes=target.stat().st_size)
            return {**record,'sha256_local':digest,'bytes':target.stat().st_size,'ok':True}
    part=target.with_name(target.name+'.part')
    for attempt in range(6):
        try:
            event('download_start',path=record['local_path'],url=record['url'],expected_bytes=size)
            with get(record['url']) as r,part.open('wb') as f:
                while block:=r.read(8*1024*1024):f.write(block)
            if size is not None and part.stat().st_size!=size:raise ValueError('size mismatch')
            digest=sha256(part)
            if expected and digest!=expected:raise ValueError('upstream SHA256 mismatch')
            part.replace(target)
            event('download_complete',path=record['local_path'],bytes=target.stat().st_size,sha256=digest)
            return {**record,'sha256_local':digest,'bytes':target.stat().st_size,'ok':True}
        except Exception as e:
            event('download_retry',path=record['local_path'],attempt=attempt+1,error=str(e))
            if attempt==5:return {**record,'ok':False,'error':str(e)}
            time.sleep(3+attempt*2)

def select(repo,predicate,dest):
    info=model_info(repo);sha=info['sha'];records=[]
    for f in info['siblings']:
        name=f['rfilename']
        if not predicate(name):continue
        lfs=f.get('lfs') or {}
        records.append({'repo':repo,'revision':sha,'remote_file':name,'url':'https://huggingface.co/'+repo+'/resolve/'+sha+'/'+urllib.parse.quote(name,safe='/'),'local_path':str((dest/name).relative_to(ROOT)),'size':f.get('size') or lfs.get('size'),'sha256_upstream':lfs.get('sha256')})
    if not records:raise ValueError('No files selected from '+repo)
    return records

def main():
    records=[]
    records+=select('TMElyralab/MuseTalk',lambda n:n.startswith('musetalkV15/') or n in ['README.md','LICENSE'],LIVE/'models')
    records+=select('stabilityai/sd-vae-ft-mse',lambda n:n in ['config.json','diffusion_pytorch_model.bin','README.md'],LIVE/'models/sd-vae')
    records+=select('openai/whisper-tiny',lambda n:n.endswith('.json') or n in ['pytorch_model.bin','README.md'],LIVE/'models/whisper')
    records+=select('ManyOtherFunctions/face-parse-bisent',lambda n:n in ['79999_iter.pth','resnet18-5c106cde.pth','README.md'],LIVE/'models/face-parse-bisent')
    # Download both selected v2 and v2ProPlus inference profiles; omit training discriminator weights.
    records+=select('lj1995/GPT-SoVITS',lambda n:n.startswith(('chinese-roberta-wwm-ext-large/','chinese-hubert-base/','sv/')) or n in ['gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt','gsv-v2final-pretrained/s2G2333k.pth','v2Pro/s2Gv2ProPlus.pth','s1v3.ckpt','README.md'],TTS/'GPT_SoVITS/pretrained_models')
    records+=select('XXXXRT/GPT-SoVITS-Pretrained',lambda n:n in ['G2PWModel.zip','nltk_data.zip','open_jtalk_dic_utf_8-1.11.tar.gz'],ROOT/'downloads/tts-text')
    # Face detector referenced by LiveTalking's own local face_detection module.
    records.append({'url':'https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth','local_path':'cache/torch/hub/checkpoints/s3fd-619a316812.pth','role':'face_detection'})
    (SETUP/'model-download.plan.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    event('plan_ready',files=len(records),known_bytes=sum(r.get('size') or 0 for r in records))
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(download,records):
            results.append(result)
            (SETUP/'model-download.results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['ok'] for r in results):raise RuntimeError('Some required model downloads failed')
    for archive_name,dest in [('G2PWModel.zip',TTS/'GPT_SoVITS/text'),('nltk_data.zip',ROOT/'cache')]:
        archive=ROOT/'downloads/tts-text'/archive_name
        dest.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive) as z:z.extractall(dest)
    event('model_downloads_finished',ok=True,files=len(results),bytes=sum(r['bytes'] for r in results))
    (SETUP/'models.result.json').write_text(json.dumps({'ok':True,'files':len(results),'bytes':sum(r['bytes'] for r in results)},indent=2),encoding='utf-8')

if __name__=='__main__':
    try:main()
    except Exception as e:
        event('model_preparation_failed',error=str(e))
        raise
