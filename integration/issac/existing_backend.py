"""Register one hash-pinned existing local model without downloads or conversion."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from .common import AdmissionError,FileLease,file_hash,inside,read_json,write_json

POLICY_ID='NM-ISSAC-EXISTING-QWEN27B-20261109-v1'
SOURCE='C:/dev/comfyUI/ComfyUI/models/LLM/Qwen3.8-27B-UD-IQ4_XS.gguf'
SHA256='40fac4050e940397dbf13087afd50f4734a11805bf9d65ef8ddd7483470e6199'
SIZE=14252845984
CATALOGUE='models/naimei-existing-catalogue'
MODEL_PATH='Qwen/Qwen3.8-27B/Qwen3.8-27B-UD-IQ4_XS.gguf'


def selection(root):
    policy=read_json(inside(root,'configs/issac/existing-model-backend.json'))
    expected={'policy_id':POLICY_ID,'source_file':SOURCE,'bytes':SIZE,'sha256':SHA256,
        'catalogue_root':CATALOGUE,'catalogue_path':MODEL_PATH,'model_identifier':'issac-naimei-local',
        'context_length':16384,'gpu_offload':1,'model_downloads_allowed':False,'cloud_fallback':False,
        'existing_swift_files_preserved':True,'model_weight_conversion_allowed':False}
    if any(type(policy.get(k)) is not type(v) or policy[k]!=v for k,v in expected.items()):
        raise AdmissionError('EXACT_EXISTING_LOCAL_BACKEND_POLICY_REQUIRED')
    return policy


def verify_existing_file(path,*,size=SIZE,sha256=SHA256):
    path=Path(path);before=path.stat()
    if not path.is_file() or before.st_size!=size:
        raise AdmissionError('EXISTING_MODEL_SIZE_CHANGED')
    with path.open('rb') as stream:
        if stream.read(4)!=b'GGUF':raise AdmissionError('EXISTING_GGUF_REQUIRED')
    actual=file_hash(path);after=path.stat()
    if actual!=sha256 or (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
        raise AdmissionError('EXISTING_MODEL_HASH_OR_IDENTITY_CHANGED')
    return {'path':str(path.resolve()),'bytes':after.st_size,'sha256':actual,
            'mtime_ns':after.st_mtime_ns,'file_id':after.st_ino}


def catalogue_root(root,config):
    if config.get('backend_policy_id')!=POLICY_ID:
        return Path('C:/dev/lmstudio/models').resolve()
    policy=selection(root);target=inside(root,policy['catalogue_root'])
    if Path(config.get('catalogue_root','')).resolve()!=target:
        raise AdmissionError('OWNED_EXISTING_MODEL_CATALOGUE_REQUIRED')
    return target


def register_link(root,source):
    """Only add a task-owned link; never write the shared weight's contents."""
    base=inside(root,CATALOGUE);destination=inside(root,CATALOGUE+'/'+MODEL_PATH)
    destination.parent.mkdir(parents=True,exist_ok=True)
    for path in [base,*destination.parents]:
        if not path.is_relative_to(Path(root).resolve()):continue
        if path.is_symlink() or path.is_junction():raise AdmissionError('PLAIN_OWNED_MODEL_CATALOGUE_REQUIRED')
    if destination.exists():
        if not os.path.samefile(source,destination):raise AdmissionError('EXISTING_CATALOGUE_FILE_PRESERVED')
    else:os.link(source,destination)
    if not os.path.samefile(source,destination) or file_hash(destination)!=SHA256:
        raise AdmissionError('EXACT_EXISTING_MODEL_LINK_REQUIRED')
    return destination


def bind_catalogue(root):
    root=Path(root).resolve();home=inside(root,'tools/lmstudio/home');link=home/'models'
    selected=inside(root,CATALOGUE);retained=Path('C:/dev/lmstudio/models').resolve()
    backup=home/'models-retained-swift-source'
    if link.exists() and link.resolve()==selected:return
    if link.exists():
        if not link.is_junction() or link.resolve()!=retained or backup.exists():
            raise AdmissionError('UNEXPECTED_MODEL_CATALOGUE_PRESERVED')
        # Rename the reparse entry itself, without traversing or moving its target.
        # Both names are literal children of this task's existing copied home.
        os.rename(link,backup)
        if not backup.is_junction() or backup.resolve()!=retained:
            raise AdmissionError('RETAINED_SOURCE_JUNCTION_PRESERVATION_FAILED')
    elif backup.exists() and (not backup.is_junction() or backup.resolve()!=retained):
        raise AdmissionError('RETAINED_SOURCE_BACKUP_CHANGED')
    result=subprocess.run([r'C:\Windows\System32\cmd.exe','/d','/c','mklink','/J',str(link),str(selected)],
        capture_output=True,timeout=10,creationflags=0x08000000)
    if result.returncode or not link.is_junction() or link.resolve()!=selected:
        raise AdmissionError('OWNED_MODEL_CATALOGUE_JUNCTION_REQUIRED')


def validate_prepared_config(root,config):
    policy=selection(root);base=catalogue_root(root,config)
    expected=inside(root,CATALOGUE+'/'+MODEL_PATH)
    rows=config.get('retained_model_files')
    if (config.get('backend_policy_id')!=POLICY_ID or config.get('model')!=policy['model_identifier']
        or config.get('retained_model_key')!=MODEL_PATH or config.get('context_window')!=16384
        or config.get('gpu_offload')!=1 or config.get('cloud_fallback') is not False
        or config.get('model_downloads_allowed') is not False or not isinstance(rows,list) or len(rows)!=1):
        raise AdmissionError('EXACT_EXISTING_LOCAL_BACKEND_CONFIGURATION_REQUIRED')
    row=rows[0]
    if (Path(row.get('path','')).resolve()!=expected or row.get('bytes')!=SIZE or row.get('sha256')!=SHA256
        or not expected.is_relative_to(base) or not os.path.samefile(expected,Path(SOURCE))):
        raise AdmissionError('EXACT_EXISTING_LOCAL_BACKEND_FILE_REQUIRED')
    return policy


def prepare_locked(root):
    from .deployment import require_candidate
    import psutil
    root=Path(root).resolve();candidate=require_candidate(root);policy=selection(root)
    registration=inside(root,'.setup/issac-lmstudio-owner.json')
    if registration.is_file():
        owner=read_json(registration)
        try:
            if psutil.Process(owner['pid']).create_time()==owner['created_at']:
                raise AdmissionError('OWNED_MODEL_CLIENT_MUST_CLOSE_BEFORE_CATALOGUE_CHANGE')
        except psutil.NoSuchProcess:pass
    config_path=inside(root,'private/issac/model.json');config=read_json(config_path)
    source=Path(policy['source_file']).resolve();proof=verify_existing_file(source)
    preserved=config.get('preserved_swift_files',config.get('retained_model_files',[]))
    if config.get('backend_policy_id')!=POLICY_ID:
        if len(preserved)!=2:raise AdmissionError('TWO_EXISTING_SWIFT_ASSETS_MUST_BE_PRESERVED')
        for row in preserved:
            path=Path(row['path']).resolve()
            if not path.is_relative_to(Path('C:/dev/lmstudio/models').resolve()) or path.stat().st_size!=row['bytes']:
                raise AdmissionError('RETAINED_SWIFT_ASSET_CHANGED')
        write_json(inside(root,'operations/model-backend-history/swift-private-config.json'),config)
    destination=register_link(root,source);bind_catalogue(root)
    config.update(backend_policy_id=POLICY_ID,model=policy['model_identifier'],
        retained_model_key=policy['catalogue_path'],catalogue_root=str(inside(root,CATALOGUE)),
        retained_model_files=[{'path':str(destination),'bytes':SIZE,'sha256':SHA256}],
        preserved_swift_files=preserved,context_window=16384,gpu_offload=1,
        model_downloads_allowed=False,cloud_fallback=False,qualified=False)
    config.pop('response_model_id',None)
    validate_prepared_config(root,config)
    write_json(config_path,config)
    row={**candidate,'policy_id':POLICY_ID,'passed':True,'source':proof,
        'catalogue_path':policy['catalogue_path'],'destination':str(destination),
        'method':'native_NTFS_hardlink','new_model_download_bytes':0,'additional_weight_payload_bytes':0,
        'existing_swift_files_preserved':len(preserved),'original_weight_content_written':False,
        'same_naimei_channel_model':policy['model_identifier'],'channel_endpoint':'owned_local_gateway',
        'model_qualified':False,'at_unix':time.time()}
    write_json(inside(root,'state/isaac-strategy/existing-model-preparation.json'),row)
    return row


def prepare(root):
    with FileLease(inside(root,'state/isaac-strategy/existing-model-preparation.lock')):
        return prepare_locked(root)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('action',choices=['prepare']);args=parser.parse_args()
    print(json.dumps(prepare(args.root),ensure_ascii=False))
