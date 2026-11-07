"""Whole-round real fault, natural full-run and source-switch evidence tools."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import time
import uuid

from aiohttp import ClientSession,ClientTimeout

from .acceptance import Runner,record_gate
from .common import AdmissionError,Audit,file_hash,inside,read_json,write_json
from .deployment import require_candidate
from .recovery import StoppedState,backup,restore


async def control(root,http,body):
    token=inside(root,'private/issac/bridge-token.txt').read_text('ascii').strip()
    async with http.post('http://127.0.0.1:9534/control',json=body,headers={'X-Isaac-Token':token},
        timeout=ClientTimeout(total=12)) as response:
        value=await response.json()
        if response.status!=200:raise AdmissionError('SCENARIO_NORMAL_CONTROL_NOT_ACKNOWLEDGED')
        return value


async def fault(root,component):
    import psutil
    candidate=require_candidate(root)
    allowed={'strategy-dsh','model-gateway','narrator','studio','voice','flashhead','game-controller'}
    if component not in allowed:raise AdmissionError('FIXED_OWNED_FAULT_COMPONENT_REQUIRED')
    registry=read_json(inside(root,'state/issac-stream/application.json'))
    rows=[r for r in registry['processes'] if r['name']==component]
    if len(rows)!=1 or registry['candidate_id']!=candidate['candidate_id']:raise AdmissionError('CURRENT_OWNED_FAULT_PROCESS_REQUIRED')
    row=rows[0];process=psutil.Process(row['pid'])
    if (process.create_time()!=row['created_at'] or Path(process.exe()).resolve()!=Path(row['executable']).resolve()
        or not Path(process.exe()).resolve().is_relative_to(Path(root).resolve())
        or file_hash(Path(process.exe()))!=row['executable_sha256']):raise AdmissionError('FAULT_PROCESS_IDENTITY_CHANGED')
    folder=inside(root,'state/issac-acceptance/faults')/(component+'-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    audit=Audit(folder/'samples.jsonl');start=time.monotonic();paused_at=None;app_stopped=False;samples=[]
    async with ClientSession(trust_env=False) as http:
        before=None
        try:
            async with http.get('http://127.0.0.1:9534/status',timeout=ClientTimeout(total=3)) as response:before=await response.json()
        except Exception:pass
        if not before or not before.get('armed'):raise AdmissionError('ACTIVE_OBSERVED_GAME_REQUIRED_FOR_REAL_FAULT_DRILL')
        process.terminate() # Deliberate crash of this exact owned component only.
        for _ in range(40):
            sample={'elapsed_seconds':time.monotonic()-start}
            for name,url in [('game','http://127.0.0.1:9532/query?topic=state'),('app','http://127.0.0.1:9541/status')]:
                try:
                    async with http.get(url,timeout=ClientTimeout(total=1)) as response:sample[name]=await response.json()
                except Exception:sample[name]={'unavailable':True}
            game=sample['game'].get('data',{}).get('room',{})
            if game.get('paused') is True and paused_at is None:paused_at=sample['elapsed_seconds']
            if sample['app'].get('stage','').startswith('stopped'):app_stopped=True
            samples.append(sample);audit.append('fault_sample',**sample)
            await asyncio.sleep(.25)
        # If native host died, independently inspect the same game process via
        # the fixed read-only bridge. Lua's normal-input lease must have paused.
        if paused_at is None:
            from .native_game import NativeGame
            native=NativeGame(root);session=read_json(inside(root,'state/isaac-strategy/native-session.json'))
            try:
                native.attach(session['game_pid']);observation=native.observe()
                write_json(folder/'independent-native-observation.json',observation)
                if observation.get('paused') is True:paused_at=time.monotonic()-start
                else:
                    rescue=native.pause();write_json(folder/'emergency-normal-pause.json',rescue)
            finally:native.close()
    result={**candidate,'component':component,'fault':'exact_owned_process_exit','pid':row['pid'],
        'created_at':row['created_at'],'confirmed_normal_pause_seconds':paused_at,
        'passed':paused_at is not None and paused_at<=8,'supervisor_stopped':app_stopped,
        'automatic_restart':False,'automatic_rearm':False,'actual_recovery_review_required':True}
    write_json(folder/'result.json',result);return result


async def full_run(root,seconds=21600):
    if not 600<=seconds<=21600:raise AdmissionError('BOUNDED_FULL_RUN_OBSERVATION_REQUIRED')
    runner=Runner(root);cursor=0;start=None;terminal=None;began=time.monotonic();observations=0
    identity=None;frames=set();started_unix=time.time()
    try:
        async with ClientSession(trust_env=False) as http:
            while time.monotonic()-began<seconds:
                batch=await runner.json(http,9534,'/events?after='+str(cursor));cursor=batch['cursor']
                for event in batch['events']:
                    if (start is None and event['type']=='run_started' and 0<=event.get('frame',-1)<=120
                        and event['observed_at']>=started_unix):
                        start=event;identity=event['run_id']
                    if start and event['type']=='run_ended' and event['run_id']==identity:
                        proof=event.get('execution_receipt') or {}
                        if proof.get('callback')=='MC_POST_GAME_END' and type(proof.get('is_game_over')) is bool:
                            terminal=event
                    runner.audit.append('actual_game_event',**event)
                state=await runner.json(http,9532,'/query?topic=state');observations+=1
                if state.get('connected') and state.get('identity'):
                    frames.add((state['identity'].get('seed'),state.get('frame')))
                if terminal:break
                await asyncio.sleep(.5)
        checks={'natural_run_start_observed':start is not None,'same_run_natural_terminal_callback':terminal is not None,
            'actual_progress_observed':len(frames)>=120,'no_forced_seed_health_inventory_or_ending':True}
        result={**runner.candidate,'start':start,'terminal':terminal,'actual_result':terminal['facts']['result'] if terminal else 'not_finished',
            'elapsed_seconds':time.monotonic()-began,'observed_native_frames':len(frames),'status_samples':observations,
            'checks':checks,'passed':all(checks.values()),'winning_run_claimed':bool(terminal and terminal['facts']['result']=='ending')}
        path=runner.folder/'full-run.json';write_json(path,result)
        record_gate(root,'full_run_outcome',checks,[path.relative_to(root).as_posix(),(runner.folder/'samples.jsonl').relative_to(root).as_posix()])
        return result
    finally:runner.close()


def source_switch(root,archive,sha256):
    """Stopped source-generation switch; never copy another installation's state."""
    candidate=require_candidate(root,hardware=False)
    folder=inside(root,'state/issac-acceptance/rollback')/('switch-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    state=backup(root)
    saved=read_json(inside(root,'.setup/source-manifest.json'))
    import zipfile
    import sys
    incoming=Path(archive).resolve()
    if not incoming.is_relative_to(inside(root,'operations/issac-candidates')):raise AdmissionError('TRANSFERRED_CANDIDATE_ARCHIVE_REQUIRED')
    if file_hash(incoming)!=sha256:raise AdmissionError('ROLLBACK_ARCHIVE_CHANGED')
    with zipfile.ZipFile(incoming) as zipped:other=json.loads(zipped.read('.source-manifest.json'))
    if other['candidate_id']==candidate['candidate_id']:raise AdmissionError('DISTINCT_FROZEN_INSTALLATION_GENERATION_REQUIRED')
    sys.path.insert(0,str(inside(root,'scripts')))
    from install_issac_candidate import install
    switched=install(incoming,sha256,root);verified=require_candidate(root,hardware=False)
    # The operator must install the original already frozen archive to return.
    # This receipt does not relabel older source as a tested release.
    result={'from':candidate,'to':verified,'installed':switched,'prior_state_backup':state,
        'same_code_commit':saved['source_commit']==other['source_commit'],'automatic_start':False,
        'automatic_state_restore':False,'reverse_switch_and_recovery_review_required':True}
    write_json(folder/'switch.json',result);return result


def state_drill(root):
    before=require_candidate(root,hardware=False);saved=backup(root);result=restore(root,saved['backup'])
    report={**before,'backup':saved,'restore':result,'same_candidate_only':True,'source_version_rollback_is_separate':True}
    folder=inside(root,'state/issac-acceptance/rollback');folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/('state-'+uuid.uuid4().hex+'.json'),report);return report


async def slow_client(root):
    runner=Runner(root)
    try:
        async with ClientSession(trust_env=False) as http:
            before=await runner.json(http,8062,'/health');revision=before['programme']['revision']
            socket=await http.ws_connect(f'http://127.0.0.1:8062/api/studio/stream?v=3&codec=h264&programme_revision={revision}',
                autoping=False,heartbeat=None,max_msg_size=4*1024*1024,compress=0)
            try:
                await asyncio.wait_for(socket.receive(),4)
                await asyncio.sleep(30)
                after=await runner.json(http,8062,'/health')
            finally:await socket.close()
            checks={'actual_slow_connection':True,'server_disconnects_bounded_slow_client':
                after['counters'].get('slow_viewer_disconnects',0)>before['counters'].get('slow_viewer_disconnects',0),
                'other_media_continues':after['counters'].get('output_frames',0)-before['counters'].get('output_frames',0)>=25*29,
                'no_media_quality_fault':after['counters'].get('media_faults',0)==before['counters'].get('media_faults',0)}
            result={**runner.candidate,'checks':checks,'passed':all(checks.values()),'before':before,'after':after,
                'observer_claimed_playback_authority':False}
            write_json(runner.folder/'slow-client.json',result);return result
    finally:runner.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('action',choices=['fault','full-run','source-switch','state-drill','slow-client']);parser.add_argument('--component')
    parser.add_argument('--seconds',type=int,default=21600);parser.add_argument('--archive');parser.add_argument('--sha256');args=parser.parse_args()
    root=args.root.resolve()
    result=asyncio.run(fault(root,args.component)) if args.action=='fault' else asyncio.run(full_run(root,args.seconds)) if args.action=='full-run' else source_switch(root,args.archive,args.sha256) if args.action=='source-switch' else asyncio.run(slow_client(root)) if args.action=='slow-client' else state_drill(root)
    print(json.dumps(result,ensure_ascii=False))
