"""Consistent stopped-stack backups; deletion ledgers never move backwards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

from .common import AdmissionError,FileLease,digest,file_hash,inside,read_json,write_json
from .deployment import require_candidate

SCOPES=('state/issac-stream','state/isaac-strategy','state/issac-materials')
LOCKS=('state/issac-stream/application.lock','state/isaac-strategy/host.lock',
       'state/issac-stream/voice.lock','state/issac-stream/flashhead.lock','state/issac-stream/model-gateway.lock')


class StoppedState:
    def __init__(self,root):self.root=root;self.leases=[]
    def __enter__(self):
        try:
            for name in LOCKS:self.leases.append(FileLease(inside(self.root,name)).acquire())
            import psutil
            registry=inside(self.root,'state/issac-stream/application.json')
            if registry.exists():
                for row in read_json(registry).get('processes',[]):
                    if row['name']=='isaac-game':continue
                    try:
                        process=psutil.Process(row['pid'])
                        if process.create_time()==row['created_at']:
                            raise AdmissionError('STOP_REGISTERED_COMPONENTS_BEFORE_STATE_RECOVERY')
                    except psutil.NoSuchProcess:pass
            return self
        except Exception:self.__exit__(None,None,None);raise
    def __exit__(self,*_):
        for lease in reversed(self.leases):lease.close()


def files(root):
    for scope in SCOPES:
        folder=inside(root,scope)
        if not folder.exists():continue
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.suffix in {'.lock','.log','.tmp'} or path.name.endswith(('-wal','-shm')):continue
            if any(part in {'dsh-home','dsh-logs','process-logs','stop-requests','clips','inspection'} for part in path.relative_to(folder).parts):continue
            yield path


def privacy_heads(root):
    return {p:file_hash(inside(root,p)) if inside(root,p).exists() else None
        for p in ('state/deletion-ledger.jsonl','state/deletion-head.json')}


def interaction_watermark(path):
    if not path.exists():return None
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'stream_events' not in tables:return None
        row=db.execute("SELECT event_seq,payload_sha256 FROM stream_events WHERE event_type IN ('input.accepted','playback.completed') ORDER BY event_seq DESC LIMIT 1").fetchone()
        return list(row) if row else [0,None]
    finally:db.close()


def backup(root):
    candidate=require_candidate(root,hardware=False)
    with StoppedState(root):
        folder=inside(root,'backups/issac')/('state-'+uuid.uuid4().hex);folder.mkdir(parents=True)
        rows=[]
        for path in files(root):
            relative=path.relative_to(root).as_posix();target=folder/'files'/relative;target.parent.mkdir(parents=True,exist_ok=True)
            if path.suffix=='.sqlite3':
                source=sqlite3.connect(path);dest=sqlite3.connect(target)
                try:
                    source.backup(dest)
                    if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise AdmissionError('BACKUP_SQLITE_INTEGRITY_FAILED')
                finally:source.close();dest.close()
                method='sqlite_online_backup_while_owners_stopped'
            else:shutil.copy2(path,target);method='byte_copy_while_owners_stopped'
            rows.append({'path':relative,'sha256':file_hash(target),'bytes':target.stat().st_size,'method':method})
        report={**candidate,'id':folder.name,'created_unix':time.time(),'files':rows,
            'privacy_heads':privacy_heads(root),
            'interaction_watermark':interaction_watermark(inside(root,'state/issac-stream/stream.sqlite3')),
            'source_manifest_sha256':digest(read_json(inside(root,'.setup/source-manifest.json'))),
            'game_saves_included':False,'deletion_ledgers_must_not_roll_back':True}
        write_json(folder/'manifest.json',report)
        return {'backup':folder.relative_to(root).as_posix(),'files':len(rows),'manifest_sha256':digest(report)}


def restore(root,relative):
    folder=inside(root,relative)
    if not folder.is_relative_to(inside(root,'backups/issac')):raise AdmissionError('ISAAC_BACKUP_SCOPE_REQUIRED')
    manifest=read_json(folder/'manifest.json')
    current=require_candidate(root,hardware=False)
    if manifest['candidate_id']!=current['candidate_id']:raise AdmissionError('SAME_VERSION_STATE_RESTORE_REQUIRED')
    # Preserve the live store's deletion generation. Never replace a newer
    # privacy tombstone with an earlier copy, even during a version drill.
    with StoppedState(root):
        if privacy_heads(root)!=manifest.get('privacy_heads'):
            raise AdmissionError('EXTERNAL_PRIVACY_LEDGER_CHANGED_RESTORE_BLOCKED')
        if interaction_watermark(inside(root,'state/issac-stream/stream.sqlite3'))!=manifest.get('interaction_watermark'):
            raise AdmissionError('RESTORE_WOULD_LOSE_NEW_INTERACTIONS')
        for row in manifest['files']:
            source=folder/'files'/row['path'];target=inside(root,row['path'])
            if file_hash(source)!=row['sha256']:raise AdmissionError('STATE_BACKUP_CHANGED')
            if target.suffix=='.sqlite3' and target.is_file():
                old=sqlite3.connect(source);live=sqlite3.connect(target)
                try:
                    tables={x[0] for x in live.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if 'rooms' in tables:
                        now=live.execute('SELECT character_id,room_id,deletion_generation FROM rooms').fetchall()
                        prior={(x[0],x[1]):x[2] for x in old.execute('SELECT character_id,room_id,deletion_generation FROM rooms')}
                        if any(generation>prior.get((c,r),-1) for c,r,generation in now):
                            raise AdmissionError('NEWER_DELETION_GENERATION_BLOCKS_ROLLBACK')
                    if 'deletion_ledger' in tables:
                        if live.execute('SELECT COUNT(*) FROM deletion_ledger').fetchone()[0]!=old.execute('SELECT COUNT(*) FROM deletion_ledger').fetchone()[0]:
                            raise AdmissionError('DELETION_LEDGER_CHANGED_ROLLBACK_BLOCKED')
                finally:old.close();live.close()
        # Keep a fresh recovery point for every replaced file; never overwrite
        # the only durable copy of the current installation's state.
        rescue=inside(root,'backups/issac')/('pre-restore-'+uuid.uuid4().hex)
        for row in manifest['files']:
            source=folder/'files'/row['path'];target=inside(root,row['path'])
            if target.exists():
                safe=rescue/row['path'];safe.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,safe)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        return {'restored_files':len(manifest['files']),'same_candidate':True,'game_saves_restored':False,
                'prior_state_backup':rescue.relative_to(root).as_posix(),'autopilot_resumed':False,'playback_resumed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('action',choices=['backup','restore']);parser.add_argument('--backup');args=parser.parse_args()
    print(json.dumps(backup(args.root.resolve()) if args.action=='backup' else restore(args.root.resolve(),args.backup),ensure_ascii=False))
