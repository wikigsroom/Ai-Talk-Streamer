"""File preparation only: reuse retained GGUF files and copy the offline NLTK cache."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(4*1024*1024):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    root=args.root.resolve()
    if os.name!='nt' or root!=Path('C:/dev/虚拟数字人直播/issac').resolve():raise ValueError('ISOLATED_NATIVE_INSTALLATION_REQUIRED')
    source=Path('C:/dev/虚拟数字人直播/cache/nltk_data');destination=root/'cache/nltk_data'
    rows=[]
    if not source.is_dir():raise ValueError('EXISTING_OFFLINE_NLTK_CACHE_MISSING')
    for path in sorted(source.rglob('*')):
        if not path.is_file():continue
        target=destination/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True)
        before=sha(path)
        if target.exists():
            if sha(target)!=before:raise ValueError('ISOLATED_NLTK_FILE_CONFLICT')
        else:shutil.copy2(path,target)
        if sha(target)!=before or sha(path)!=before:raise ValueError('NLTK_BYTE_COPY_FAILED')
        rows.append({'path':path.relative_to(source).as_posix(),'bytes':target.stat().st_size,'sha256':before})
    model_root=Path('C:/dev/lmstudio/models').resolve()
    files=sorted(model_root.rglob('*.gguf'))
    if len(files)!=2 or sum(p.stat().st_size for p in files)!=75827956000:
        raise ValueError('PINNED_RETAINED_SWIFT_SHARDS_REQUIRED')
    key=files[0].relative_to(model_root).as_posix()
    model={'base_url':'http://127.0.0.1:1234/v1','model':'issac-swift-local','api_key':'','context_window':16384,
        'retained_model_key':key,'gpu_offload':.45,
        'retained_model_files':[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files],
        'model_downloads_allowed':False,'cloud_fallback':False,'qualified':False}
    private=root/'private/issac/model.json';private.parent.mkdir(parents=True,exist_ok=True)
    if private.exists():
        old=json.loads(private.read_text('utf-8-sig'))
        if old!=model:raise ValueError('EXISTING_PRIVATE_MODEL_CONFIGURATION_LEFT_UNCHANGED')
    else:private.write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n','utf-8')
    receipt={'id':uuid.uuid4().hex,'nltk_files':rows,'nltk_verified_files':len(rows),
        'retained_model_files':model['retained_model_files'],'new_model_download_bytes':0,
        'application_tests_run':False,'models_loaded':False,'old_reference_audio_served':False}
    folder=root/'operations/native-input-preparation';folder.mkdir(parents=True,exist_ok=True)
    (folder/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k not in {'nltk_files','retained_model_files'}},ensure_ascii=False))


if __name__=='__main__':main()
