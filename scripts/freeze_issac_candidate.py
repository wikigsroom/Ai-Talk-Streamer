"""Freeze a whole completed source round, before any application testing."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integration.issac.common import AdmissionError, digest, file_hash, inside, read_json, write_json


def preserved_blobs(root,git):
    """Package an explicitly preserved historical document from HEAD only."""
    changes=git('status','--porcelain=v1','-z','--untracked-files=normal').decode('utf-8').split('\0')
    changes=[row for row in changes if row]
    if not changes:return {},[]
    amendment=read_json(inside(root,'configs/issac/live120.json'))
    allowed=amendment.get('preserved_unrelated_worktree_changes',[])
    approved='docs/issac/实施任务与验收清单20261107.csv'
    expected='10e9199849894b36f9204e9dacf7e3d7cd1c31ef70a35c6b7087aef8f34adc65'
    if (amendment.get('amendment_id')!='NM-ISSAC-EXECUTION-120S-20261109-v1'
            or allowed!=[{'path':approved,'worktree_sha256':expected,'candidate_content':'HEAD_blob_only'}]
            or changes!=[' M '+approved] or file_hash(inside(root,approved))!=expected):
        raise AdmissionError('COMMIT_WHOLE_ROUND_BEFORE_FREEZE')
    blob=git('show','HEAD:'+approved)
    receipt={'path':approved,'preserved_worktree_sha256':expected,'candidate_content':'HEAD_blob_only',
             'packaged_sha256':hashlib.sha256(blob).hexdigest(),'worktree_modified_by_freeze':False}
    return {approved:blob},[receipt]


def freeze(root, destination, inventory_relative=None):
    flags={'creationflags':0x08000000}
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args],**flags)
    if git('branch','--show-current').decode().strip()!='issac':
        raise AdmissionError('ISAAC_BRANCH_REQUIRED')
    blobs,preserved=preserved_blobs(root,git)
    inventory_relative=inventory_relative or read_json(root/'configs/issac/execution-rounds.json')['round_2_onward']['inventory']
    if not inventory_relative.startswith('configs/issac/') or '..' in Path(inventory_relative).parts:
        raise AdmissionError('TRACKED_ROUND_INVENTORY_REQUIRED')
    inventory=read_json(inside(root,inventory_relative))
    ids=[item['id'] for item in inventory['items']]
    if (inventory.get('application_tests_started') is not False or inventory.get('candidate_frozen') is not False
            or {item['status'] for item in inventory['items']}!={'code_complete_pending_acceptance'}
            or not ids or len(set(ids))!=len(ids) or inventory.get('branch')!='issac'
            or inventory.get('manual_whole_round_source_review_complete') is not True):
        raise AdmissionError('ALL_ROUND_CODE_AND_MANUAL_REVIEW_REQUIRED_BEFORE_TESTING')
    commit=git('rev-parse','HEAD').decode().strip()
    candidate_id='issac-'+commit[:12]+'-'+uuid.uuid4().hex[:8]
    names=git('ls-files','-z').decode('utf-8').split('\0')
    if inventory_relative not in names or any(name not in names for item in inventory['items'] for name in item['source_files']):
        raise AdmissionError('ROUND_INVENTORY_FILES_MUST_BE_COMMITTED')
    rows=[];excluded=[]
    denied={'private','state','runtime','models','cache','game','.setup'}
    for name in names:
        if not name:
            continue
        parts=Path(name).parts
        # The inherited repository tracks historical exported media and old
        # operator scripts. Preserve them in Git, outside this deployment's
        # source package and writeable outputs/operations namespaces.
        if parts[0] in {'outputs','operations'}:
            excluded.append(name)
            continue
        if (parts[0] in denied or 'private' in parts or name.endswith('.env')
                or name.lower().endswith(('.aac','.gguf','.sqlite3'))):
            raise AdmissionError('PRIVATE_OR_RUNTIME_FILE_IN_SOURCE_COMMIT')
        path=root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise AdmissionError('SOURCE_LINK_NOT_ALLOWED')
        content=blobs.get(name)
        rows.append({'path':name,'bytes':len(content) if content is not None else path.stat().st_size,
                     'sha256':hashlib.sha256(content).hexdigest() if content is not None else file_hash(path)})
    manifest={'schema_version':1,'candidate_id':candidate_id,'branch':'issac','source_commit':commit,
              'round':inventory['round'],'all_round_code_complete':True,
              'development_inventory':inventory_relative,'development_inventory_sha256':file_hash(root/inventory_relative),
              'tests_started_at_freeze':False,'files':rows,'preserved_unrelated_changes':preserved,
              'excluded_historical_tracked_outputs_and_operations':excluded}
    destination.mkdir(parents=True,exist_ok=True)
    archive=destination/(candidate_id+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for row in rows:
            if row['path'] in blobs:output.writestr(row['path'],blobs[row['path']])
            else:output.write(root/row['path'],row['path'])
        output.writestr('.source-manifest.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')))
    receipt={'candidate_id':candidate_id,'source_commit':commit,'archive':archive.name,
             'archive_sha256':file_hash(archive),'source_manifest_sha256':digest(manifest),
             'files':len(rows),'application_tests_started':False,'production_accepted':False}
    write_json(destination/(candidate_id+'.json'),receipt)
    write_json(destination/(candidate_id+'.manifest.json'),manifest)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--destination',type=Path,default=ROOT/'operations/issac-candidates')
    parser.add_argument('--inventory',default=None)
    args=parser.parse_args()
    print(json.dumps(freeze(ROOT,args.destination.resolve(),args.inventory),ensure_ascii=False))
