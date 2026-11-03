"""Update a stopped, verified source installation from a reviewed public ZIP.

Keep immutable dependencies and operator data. Back up changed source and old
preparation checks; generate origin only from the verified new package manifest.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,os,shutil,uuid
import mc_deployment as mc
from native_operation import operation,atomic_json,safe_path


def update(root,archive,expected):
 root=Path(root).resolve();stage=root.parent/('.mc-source-review-'+uuid.uuid4().hex)
 require=mc.require;installed=None
 try:
  # Uses the existing bounded ZIP importer and exact full-file verification.
  installed=mc.install_source(archive,stage,expected)
  reviewed=mc.read(stage/mc.SOURCE_ORIGIN);new=reviewed['manifest']['source']
  with operation(root,'mc-reviewed-source-update'):
   old=mc.installed_source_identity(root);old_origin=mc.read(root/mc.SOURCE_ORIGIN)
   import psutil
   anchors={str((root/name).resolve()).casefold() for name in [
    'backend/dsh-bridge/server.mjs','src/LiveTalking/app.py','integration/resident_tts_service.py',
    'scripts/receiver_service.py','scripts/mc_game_service.py','scripts/mc_vision_service.py']}
   for process in psutil.process_iter(['cmdline']):
    try:require(not anchors.intersection(str(a).replace('/','\\').casefold() for a in process.info['cmdline'] or []),'MC_SOURCE_UPDATE_RUNNING_OWNER')
    except (psutil.NoSuchProcess,psutil.AccessDenied):continue
   changed=[name for name in sorted(set(old['files'])|set(new['files'])) if old['files'].get(name)!=new['files'].get(name)]
   backup=safe_path(root,root/'.setup/mc-source-backups'/uuid.uuid4().hex);backup.mkdir(parents=True)
   for name in changed:
    if name in old['files']:
     target=safe_path(root,backup/name);target.parent.mkdir(parents=True,exist_ok=True)
     shutil.copyfile(mc.inside(root,name),target)
   atomic_json(root,backup/'source-origin.json',old_origin)
   written=[]
   try:
    for name in changed:
     target=safe_path(root,root/name)
     if name in new['files']:
      data=mc.inside(stage,name).read_bytes();require(mc.hashlib.sha256(data).hexdigest()==new['files'][name],'MC_SOURCE_REVIEW_CHANGED')
      target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name('.mc-update-'+uuid.uuid4().hex+'.tmp')
      try:
       with temp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
       os.replace(temp,target)
      finally:temp.unlink(missing_ok=True)
     else:target.unlink()
     written.append(name)
    require(mc._installed_source_files(root)==new['files'],'MC_SOURCE_UPDATE_FILE_INVENTORY')
    # This new installation binding is derived from the fully verified package;
    # no historical origin or readiness record is adopted as current proof.
    origin={**reviewed,'installation_path':str(root)}
    # LiveTalking imports its private server copy, not integration/ directly.
    # Refresh this reviewed source projection in the same stopped transaction.
    from mc_runtime_projection import applied
    with applied(root,new,backup) as projection:
     atomic_json(root,root/mc.SOURCE_ORIGIN,origin);mc.installed_source_identity(root)
   except BaseException:
    for name in reversed(written):
     target=safe_path(root,root/name)
     if name in old['files']:shutil.copyfile(safe_path(root,backup/name),target)
     elif target.exists() and mc.sha(target)==new['files'][name]:target.unlink()
    atomic_json(root,root/mc.SOURCE_ORIGIN,old_origin)
    raise
   archived=[]
   for name in [mc.RECEIPT,'.setup/readiness.result.json','.setup/asset-check.result.json']:
    path=safe_path(root,root/name)
    if path.exists():shutil.move(str(path),str(backup/path.name));archived.append(name)
   result={'ok':True,'schema_version':1,'at':datetime.now(timezone.utc).isoformat(),
    'before_snapshot_sha256':old['snapshot_sha256'],'source_snapshot_sha256':new['snapshot_sha256'],
    'package_sha256':expected,'changed_files':changed,'backup':backup.relative_to(root).as_posix(),
    'archived_stale_preparation':archived,'runtime_projection':projection,
    'services_started':False,'models_loaded':False,'environment_prepared':False}
   atomic_json(root,root/'.setup/mc-source-update.json',result)
  return result
 finally:
  if installed:
   # Exactly this newly created, marked sibling; never an inferred user folder.
   require(stage.resolve()==stage and stage.parent==root.parent,'MC_SOURCE_UPDATE_STAGE_PATH')
   marker=(stage/mc.SOURCE_INSTALL_OWNER).read_text(encoding='ascii')
   mc._remove_source_stage(stage,root.parent,marker)


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--sha256',required=True);a=p.parse_args()
 print(json.dumps(update(a.root,a.archive,a.sha256),ensure_ascii=False))
