"""Standalone native source installer; creates provenance after byte verification.

The caller supplies an archive transferred over the authorized direct ZeroTier
connection and its controller-side SHA256. Existing runtimes/models/state remain
separate. This tool neither starts the game nor runs application tests.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid
import zipfile


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while data:=stream.read(1024*1024):
            value.update(data)
    return value.hexdigest()


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def install(archive, expected, root):
    if os.name!='nt' or root!=Path('C:/dev/虚拟数字人直播/issac').resolve():
        raise ValueError('PINNED_NATIVE_INSTALLATION_REQUIRED')
    if sha(archive)!=expected:
        raise ValueError('TRANSFERRED_SOURCE_CHECKSUM_MISMATCH')
    registry=root/'state/issac-stream/application.json'
    if registry.exists():
        import psutil
        for row in json.loads(registry.read_text('utf-8-sig')).get('processes',[]):
            if row['name']=='isaac-game':continue
            try:
                process=psutil.Process(row['pid'])
                if process.create_time()==row['created_at']:
                    raise ValueError('REGISTERED_COMPONENT_STILL_LIVE_STOP_BEFORE_SOURCE_INSTALL')
            except psutil.NoSuchProcess:pass
    # A live owner's kernel lock must be obtainable before changing its code.
    import msvcrt
    handles=[]
    for relative in ('state/isaac-strategy/host.lock','state/issac-stream/application.lock','state/issac-stream/model-gateway.lock',
                     'state/issac-stream/voice.lock','state/issac-stream/flashhead.lock',
                     'state/issac-stream/media-rehearsal.lock','state/issac-stream/media30-controller.lock','state/issac-acceptance/runner.lock',
                     'state/issac-stream/official-recording.lock','state/issac-acceptance/round-runner.lock'):
        lock=root/relative
        lock.parent.mkdir(parents=True,exist_ok=True)
        stream=lock.open('a+b');stream.seek(0,2)
        if not stream.tell():stream.write(b'0');stream.flush()
        stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            stream.close()
            for acquired in handles:
                acquired.seek(0);msvcrt.locking(acquired.fileno(),msvcrt.LK_UNLCK,1);acquired.close()
            raise ValueError('STOP_OWNED_SERVICES_BEFORE_SOURCE_INSTALL') from None
        handles.append(stream)
    stage=root/'operations/source-install'/uuid.uuid4().hex
    stage.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as source:
            manifest=json.loads(source.read('.source-manifest.json'))
            if manifest.get('branch')!='issac' or manifest.get('all_round_code_complete') is not True or manifest.get('tests_started_at_freeze') is not False:
                raise ValueError('WHOLE_ROUND_FROZEN_ARCHIVE_REQUIRED')
            names=[row['path'] for row in manifest['files']]
            if len(set(names))!=len(names) or set(source.namelist())!=set(names)|{'.source-manifest.json'}:
                raise ValueError('SOURCE_ARCHIVE_MEMBERS_DIFFER')
            forbidden={'private','state','runtime','models','cache','game','references','outputs','operations','.setup'}
            for row in manifest['files']:
                name=row['path'];path=stage/name
                if (Path(name).is_absolute() or ':' in name or '\\' in name or '..' in Path(name).parts
                        or Path(name).parts[0] in forbidden or 'private' in Path(name).parts):
                    raise ValueError('SOURCE_ARCHIVE_PATH_REJECTED')
                path.parent.mkdir(parents=True,exist_ok=True)
                with source.open(name) as incoming,path.open('xb') as output:
                    shutil.copyfileobj(incoming,output,1024*1024)
                if path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:
                    raise ValueError('SOURCE_MANIFEST_CHECKSUM_MISMATCH')
        prior=root/'operations/source-install'/('backup-'+uuid.uuid4().hex)
        old_path=root/'.setup/source-manifest.json'
        old=json.loads(old_path.read_text('utf-8-sig')) if old_path.is_file() else {'files':[]}
        if old_path.is_file():
            previous_origin=json.loads((root/'.setup/deployment-origin.json').read_text('utf-8-sig'))
            if hashlib.sha256(canonical(old).encode()).hexdigest()!=previous_origin['source_manifest_sha256']:
                raise ValueError('PREVIOUS_SOURCE_MANIFEST_PROVENANCE_CHANGED')
        old_rows={row['path']:row for row in old['files']}
        new_rows={row['path']:row for row in manifest['files']}
        retired=[];changed=[];created=[]
        for name,row in old_rows.items():
            path=(root/name).resolve()
            if (Path(name).is_absolute() or ':' in name or '\\' in name or '..' in Path(name).parts
                    or not path.is_relative_to(root) or name.split('/')[0] in forbidden):
                raise ValueError('PREVIOUS_SOURCE_MANIFEST_SCOPE_INVALID')
            if not path.is_file() or sha(path)!=row['sha256']:
                raise ValueError('PREVIOUS_FROZEN_SOURCE_CHANGED_STOP_INSTALL')
            if name not in new_rows:retired.append(row)
        for row in manifest['files']:
            path=root/row['path']
            if not path.resolve().is_relative_to(root) or path.is_symlink():
                raise ValueError('INSTALLED_SOURCE_LINK_REJECTED')
            if path.exists() and row['path'] not in old_rows and sha(path)!=row['sha256']:
                raise ValueError('UNTRACKED_DESTINATION_SOURCE_CONFLICT_PRESERVED')
            if path.exists() and sha(path)!=row['sha256']:
                backup=prior/row['path'];backup.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,backup);changed.append({'path':row['path'],'sha256':sha(backup)})
            elif not path.exists():created.append(row)
        for row in retired:
            backup=prior/row['path'];backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(root/row['path'],backup)
            if sha(backup)!=row['sha256']:raise ValueError('RETIRED_SOURCE_BACKUP_FAILED')
        prior.mkdir(parents=True,exist_ok=True)
        metadata={}
        for name in ('source-manifest.json','deployment-origin.json','candidate.json'):
            path=root/'.setup'/name
            if path.exists():
                metadata[name]=path.read_bytes();(prior/('metadata-'+name)).write_bytes(metadata[name])
        try:
            for row in manifest['files']:
                path=root/row['path'];path.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(stage/row['path'],path)
                if sha(path)!=row['sha256']:raise ValueError('INSTALLED_SOURCE_CHECKSUM_MISMATCH')
            for row in retired:
                path=(root/row['path']).resolve()
                if not path.is_relative_to(root) or sha(path)!=row['sha256']:
                    raise ValueError('RETIRED_SOURCE_CHANGED_PRESERVED')
                path.unlink()  # exact former source member; verified backup remains
        except Exception:
            for row in changed+retired:
                target=root/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(prior/row['path'],target)
            for row in created:
                target=(root/row['path']).resolve()
                if target.is_relative_to(root) and target.is_file() and sha(target)==row['sha256']:target.unlink()
            raise
        # The receipt is emitted only after every installed source member was
        # independently checked, never copied from another device/branch.
        setup=root/'.setup';setup.mkdir(exist_ok=True)
        manifest_hash=hashlib.sha256(canonical(manifest).encode()).hexdigest()
        origin={'kind':'verified_source_archive_installation','schema_version':1,'target':'issac-rtx4090',
                'branch':'issac','source_commit':manifest['source_commit'],'archive_sha256':expected,
                'source_manifest_sha256':manifest_hash,'verified_source_manifest':True,
                'installed_at_unix':time.time(),'verified_files':len(manifest['files']),
                'transfer_required':'direct_ZeroTier_192.168.196.87_to_192.168.196.209',
                'previous_source_backup':str(prior),'previous_source_files':changed,
                'retired_source_files':retired,'previous_candidate_id':old.get('candidate_id'),
                'application_accepted':False,'public_broadcast_allowed':False}
        records={'source-manifest.json':manifest,'deployment-origin.json':origin,
                 'candidate.json':{'id':manifest['candidate_id'],'source_commit':manifest['source_commit'],
                                   'source_manifest_sha256':manifest_hash,'accepted':False}}
        try:
            for name,value in records.items():
                tmp=setup/(name+'.tmp');tmp.write_text(canonical(value)+'\n','utf-8');os.replace(tmp,setup/name)
        except Exception:
            for row in changed+retired:
                target=root/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(prior/row['path'],target)
            for row in created:
                target=(root/row['path']).resolve()
                if target.is_relative_to(root) and target.is_file() and sha(target)==row['sha256']:target.unlink()
            for name,data in metadata.items():(setup/name).write_bytes(data)
            for name in records:
                if name not in metadata and (setup/name).is_file():(setup/name).unlink()
            raise
        return {'candidate_id':manifest['candidate_id'],'verified_files':len(manifest['files']),
                'source_commit':manifest['source_commit'],'application_accepted':False}
    finally:
        for stream in handles:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1);stream.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--root',type=Path,default=Path('C:/dev/虚拟数字人直播/issac'))
    args=parser.parse_args()
    print(json.dumps(install(args.archive.resolve(),args.sha256,args.root.resolve()),ensure_ascii=False))
