"""Frozen-round acceptance runner. It records failures and never edits source."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter,deque
import json
from pathlib import Path
import sqlite3
import struct
import subprocess
import time
import uuid

from .common import AdmissionError,Audit,FileLease,digest,file_hash,inside,read_json,write_json
from .deployment import require_candidate
from .saves import SaveProtection
from .delivery import recording_seconds,recording_gate
from .readiness import verified_drink_pause

GATES={'native_game','save_protection','ordinary_inputs','wiki_prompt_tools','original_api_channel','verified_events',
 'seven_extensions','ncm01','mouth_fangs_25fps','body_continuity','mc_programme','single_audio','fault_recovery',
 'cohost_1800','cohost_7200','full_run_outcome','rollback','official_recording_600'}

REVIEW_CHECKS={
 'native_game':{'pinned_x86_executable','actual_bridge_abi','real_state_and_capture','same_pid_creation_identity'},
 'save_protection':{'private_byte_backups_verified','slot_3_actual_binding','slots_1_2_unchanged','no_save_gameplay_value_edit'},
 'ordinary_inputs':{'actual_normal_inputs','one_controller','confirmed_normal_pause','controller_loss_pause','no_arbitrary_lua_route'},
 'wiki_prompt_tools':{'complete_skill_in_actual_prompt','actual_fifth_wiki_tool_called','forced_rep_and_version_citations',
    'bounded_read_only_queries','stale_context_rejected'},
 'original_api_channel':{'actual_approved_official_channel_probe','deepseek_flash_responses','model_context_1m_registered','same_core_tool_result_roundtrip','finish_reason_complete','no_channel_or_model_substitution'},
 'verified_events':{'actual_native_causality','accepted_not_success','same_run_room_bridge','actual_pcm_before_spoken','no_restart_replay'},
 'seven_extensions':{'all_seven_loaded_receipts','persona_applied','game_facts_not_viewer_memories','single_naimei_core_authority'},
 'ncm01':{'merged_reference_hash_private','locked_omnivoice_parameters','generated_audio_auditioned','no_reference_audio_served','no_old_voice_fallback'},
 'mouth_fangs_25fps':{'all_three_modes','actual_ncm01_speech','actual_25fps','audio_synchronous','fluent_nonstatic_mouth',
    'two_upper_fangs_all_frames','silence_closed_natural','all_frame_sheets_and_full_speed_review'},
 'body_continuity':{'three_modes','actual_g0_joins','natural_controller_actions','complete_drink_chains','pause_for_drink',
    'no_endpoint_replacement','no_speech_with_cup','random_events_observed'},
 'mc_programme':{'actual_1920_1080_30','mc_geometry_preserved','title_only_visual_change','actual_game_bottom',
    'transparent_programme_top','chat_sides_and_queue','four_scenes_no_game_control','silent_preview'},
 'single_audio':{'one_official_playback_authority','actual_game_and_ncm01_audible','no_double_audio','preview_silent',
    'duck_and_restore_observed','actual_pcm_completion'},
 'fault_recovery':{'owned_faults_observed','bridge_and_model_loss','pause_within_lease','no_stale_plan_execution',
    'slow_client_bounded','no_auto_rearm','current_source_recovery_observed','unrelated_processes_preserved'},
 'rollback':{'consistent_state_backup_restore','source_generation_switch_both_directions','real_source_hashes',
    'privacy_ledger_preserved','no_new_interaction_loss','no_auto_start_or_rearm','fresh_prompt_and_playback_epoch'},
}


def sql(root,statement):
    path=inside(root,'state/issac-stream/stream.sqlite3')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)
    db.row_factory=sqlite3.Row
    try:return [dict(r) for r in db.execute(statement)]
    finally:db.close()


def required_gates(root):
    return (GATES-{'official_recording_600'})|{recording_gate(root)}


def record_gate(root,name,checks,artifacts,details=None):
    candidate=require_candidate(root,hardware=False)
    if name not in required_gates(root) or not checks or any(type(v) is not bool for v in checks.values()):
        raise AdmissionError('EXPLICIT_ACCEPTANCE_CHECKS_REQUIRED')
    files=[{'path':p,'sha256':file_hash(inside(root,p))} for p in artifacts]
    if not files:raise AdmissionError('ACTUAL_ACCEPTANCE_ARTIFACTS_REQUIRED')
    result={**candidate,'gate':name,'passed':all(checks.values()),'checks':checks,'artifacts':files,
            'details':details,'checked_unix':time.time(),'historical_result_inherited':False}
    write_json(inside(root,'state/issac-acceptance/gates/'+name+'.json'),result)
    return result


def verify_gates(root,*,before_recording=False):
    candidate=require_candidate(root)
    expected=required_gates(root)-({recording_gate(root)} if before_recording else set())
    results=[]
    for name in sorted(expected):
        value=read_json(inside(root,'state/issac-acceptance/gates/'+name+'.json'))
        if value.get('candidate_id')!=candidate['candidate_id'] or value.get('gate')!=name or value.get('passed') is not True:
            raise AdmissionError('CURRENT_ACCEPTANCE_GATE_NOT_PASSED_'+name.upper())
        for item in value['artifacts']:
            if file_hash(inside(root,item['path']))!=item['sha256']:raise AdmissionError('ACCEPTANCE_EVIDENCE_CHANGED')
        results.append(name)
    return {**candidate,'passed':results,'accepted':not before_recording,'public_broadcast_allowed':False}


class Runner:
    def __init__(self,root):
        self.root=Path(root).resolve();self.candidate=require_candidate(root)
        self.owner=FileLease(inside(root,'state/issac-acceptance/runner.lock')).acquire()
        self.id='accept-'+uuid.uuid4().hex
        self.folder=inside(root,'state/issac-acceptance/runs/'+self.id);self.folder.mkdir(parents=True)
        self.audit=Audit(self.folder/'samples.jsonl')
        write_json(self.folder/'phase.json',{**self.candidate,'phase':'uniform_acceptance','source_mutation_allowed':False,
            'started_unix':time.time(),'defects_are_for_next_whole_round':True})
        self.config=read_json(inside(root,'configs/issac/runtime.json'))

    async def json(self,http,port,path):
        from aiohttp import ClientTimeout
        async with http.get(f'http://127.0.0.1:{port}'+path,timeout=ClientTimeout(total=4)) as response:
            if response.status!=200:raise AdmissionError('LIVE_ACCEPTANCE_SERVICE_UNAVAILABLE')
            return await response.json()

    async def snapshot(self,http):
        routes={'studio':(8062,'/health'),'engine':(8040,'/health'),'voice':(9893,'/health'),
            'narrator':(3104,'/api/dsh/status'),'player':(3104,'/api/dsh/platforms/status'),
            'game':(9534,'/status'),'state':(9532,'/query?topic=state'),'naimei_core':(3104,'/api/dsh/issac/core/status'),
            'extensions':(3104,'/api/dsh/extensions'),'channel':(3104,'/api/dsh/extensions/model')}
        values=await asyncio.gather(*(self.json(http,*route) for route in routes.values()),return_exceptions=True)
        return {key:value if not isinstance(value,Exception) else {'error':'SERVICE_SAMPLE_FAILED'} for key,value in zip(routes,values)}

    def regressions(self):
        paths=self.config['native_paths'];tests=[
            [str(inside(self.root,paths['game_python'])),'-X','utf8','-B','-m','unittest','discover','-s','integration/issac/tests','-v'],
            [str(inside(self.root,paths['game_python'])),'-X','utf8','-B','-m','unittest','discover','-s','integration/isaac-agent/tests','-q'],
            [str(inside(self.root,paths['node'])),'--test','integration/issac/tests/contracts.test.mjs',
              'integration/issac/tests/naimei_core.test.mjs',
              'integration/issac/tests/native_bridge.test.mjs',
              'integration/issac/tests/channel.test.mjs',
              'integration/issac/tests/model_backend.test.mjs',
              'integration/isaac-agent/tests/test_dsh_binding.mjs']]
        tests.append([str(inside(self.root,paths['node'])),'--test',
            *[str(p.relative_to(self.root)) for p in sorted(inside(self.root,'tests').glob('*.test.mjs'))]])
        tests.append([str(inside(self.root,paths['media_python'])),'-X','utf8','-B','-m','unittest','discover','-s','tests','-p','test_*.py','-q'])
        results=[]
        for index,command in enumerate(tests):
            started=time.monotonic();path=self.folder/f'regression-{index}.log'
            with path.open('wb') as log:
                try:
                    process=subprocess.run(command,cwd=self.root,stdout=log,stderr=subprocess.STDOUT,timeout=600,creationflags=0x08000000)
                    results.append({'test':index,'exit_code':process.returncode,'seconds':time.monotonic()-started})
                except subprocess.TimeoutExpired:results.append({'test':index,'error':'REGRESSION_DEADLINE','exit_code':-1})
        result={**self.candidate,'suite':'whole_round_regression','results':results,'passed':all(r['exit_code']==0 for r in results)}
        write_json(self.folder/'regression.json',result);return result

    async def cohost(self,seconds):
        from aiohttp import ClientSession,ClientTimeout,WSMsgType
        if seconds not in {recording_seconds(self.root),600,1800,7200}:raise AdmissionError('PINNED_ACCEPTANCE_DURATION_REQUIRED')
        protection=SaveProtection(self.root);protection.verify()
        wire=Counter();intervals=[];last_sequence=last_time=None;profile=None;errors=[];identities=set()
        start=time.monotonic();first=None;last=None;capture_task=None;verification=None;finished=asyncio.Event()
        async with ClientSession(trust_env=False) as http:
            status=await self.json(http,8062,'/health');revision=status['programme']['revision']
            url=f'http://127.0.0.1:8062/api/studio/stream?v=3&codec=h264&programme_revision={revision}'
            async def receive():
                nonlocal profile,last_sequence,last_time
                try:
                    async with http.ws_connect(url,heartbeat=20,max_msg_size=4*1024*1024,compress=0) as socket:
                        async for message in socket:
                            if finished.is_set():break
                            if message.type==WSMsgType.TEXT:
                                value=json.loads(message.data)
                                if value.get('type')=='media.init':
                                    if profile is not None:wire['unexpected_profile_changes']+=1
                                    profile=value
                                    if (value.get('protocol_version'),value.get('width'),value.get('height'),value.get('fps_num'))!=(3,512,512,25):
                                        raise AdmissionError('ACTUAL_MEDIA_PROFILE_CHANGED')
                                continue
                            if message.type!=WSMsgType.BINARY:continue
                            data=message.data;seq,length,rate=struct.unpack_from('<III',data)
                            if not profile or rate!=16000 or len(data)!=12+length+1280 or data[12:16]!=b'AVC1':
                                raise AdmissionError('ACTUAL_H264_PCM_PACKET_INVALID')
                            now=time.perf_counter()
                            if last_sequence is not None and seq!=(last_sequence+1)&0xffffffff:wire['sequence_gaps']+=1
                            if last_time is not None:intervals.append(now-last_time)
                            last_sequence,last_time=seq,now;wire['packets']+=1
                except Exception as error:errors.append(str(error) if isinstance(error,AdmissionError) else 'MEDIA_OBSERVER_DISCONNECTED')
            capture_task=asyncio.create_task(receive())
            try:
                due=start
                while time.monotonic()-start<seconds:
                    if verification is not None and verification.done():
                        await verification;verification=None
                    value=await self.snapshot(http)
                    if first is None:first=value
                    last=value;wire['status_samples']+=1
                    game=value['state'];player=value['player'].get('output_player') or {}
                    active=value['naimei_core'].get('automatic') is True
                    drink=not active and verified_drink_pause(value)
                    wire['active_samples']+=active;wire['verified_drink_samples']+=drink
                    okay=(game.get('connected') and game.get('age_ms') is not None and game['age_ms']<1500
                        and player.get('connected') and player.get('programme')=='issac'
                        and value['narrator'].get('health',{}).get('authority_ready')
                        and value['studio'].get('ready') and value['game'].get('save_slot')==3
                        and value['naimei_core'].get('ready') and (active or drink)
                        and value['naimei_core'].get('actor_id')=='naimei'
                        and value['naimei_core'].get('strategic_owner')=='naimei_core_dsh')
                    wire['ready_samples']+=bool(okay)
                    if game.get('identity'):identities.add(digest(game['identity']))
                    self.audit.append('live_sample',elapsed_seconds=time.monotonic()-start,**value)
                    write_json(self.folder/'progress.json',{'elapsed_seconds':time.monotonic()-start,'required_seconds':seconds,
                        'packets':wire['packets'],'ready_samples':wire['ready_samples'],'total_samples':wire['status_samples'],
                        'candidate_id':self.candidate['candidate_id'],'finished':False})
                    if wire['status_samples']%30==0:
                        # Full source hashing can take seconds on this device.
                        # Keep receiving actual media while the immutable-source
                        # and save checks run; observer stalls are not stream stalls.
                        if verification is None:
                            verification=asyncio.create_task(verify_during_media(self.root,protection))
                        try:
                            async with http.get('http://127.0.0.1:9534/frame.jpg',timeout=ClientTimeout(total=5)) as response:
                                if response.status==200:(self.folder/f'game-{wire["status_samples"]:06d}.jpg').write_bytes(await response.read())
                        except Exception:wire['game_frame_inspection_failures']+=1
                    due+=1;await asyncio.sleep(max(0,due-time.monotonic()))
            finally:
                try:
                    if verification is not None:await verification
                finally:
                    finished.set();capture_task.cancel();await asyncio.gather(capture_task,return_exceptions=True)
        elapsed=time.monotonic()-start;protection.verify()
        samples=sorted(intervals)
        percentile=lambda q:samples[min(len(samples)-1,int(len(samples)*q))] if samples else None
        initial=first['studio'].get('counters',{});final=last['studio'].get('counters',{})
        delta={k:final.get(k,0)-initial.get(k,0) for k in set(initial)|set(final)}
        checks={'required_real_duration':elapsed>=seconds,'wire_25fps':wire['packets']/elapsed>=24.75,
            'no_sequence_gaps':wire['sequence_gaps']==0,'no_media_observer_errors':not errors,
            'stable_profile':wire['unexpected_profile_changes']==0,'p99_packet_interval_under_80ms':percentile(.99) is not None and percentile(.99)<=.08,
            'no_long_media_freeze':percentile(1) is not None and percentile(1)<=.25,
            'service_readiness_99_percent':wire['ready_samples']/max(1,wire['status_samples'])>=.99,
            'real_game_progress':len(identities)>=max(3,seconds//120),'actual_mouth_frames':delta.get('actual_audio_driven_mouth_frames',0)>=seconds,
            'actual_open_mouth_frames':delta.get('actual_model_oral_open_frames',0)>=seconds//2,
            'no_source_underflows':delta.get('source_underflows_during_speech',0)==0,
            'no_media_quality_faults':delta.get('media_faults',0)==0,'no_pump_stalls':delta.get('pump_stalls',0)==0,
            'protected_saves_unchanged':True,
            'actual_naimei_core_choices':last['naimei_core'].get('turns',0)-first['naimei_core'].get('turns',0)>=max(1,seconds//120),
            'actual_complete_game_utterances':last['naimei_core'].get('actual_completed_game_utterances',0)
                -first['naimei_core'].get('actual_completed_game_utterances',0)>=max(1,seconds//60),
            'naimei_core_decision_p95_under_8_seconds':last['naimei_core'].get('decision_latency_p95_ms') is not None
                and last['naimei_core']['decision_latency_p95_ms']<=8000}
        report={**self.candidate,'seconds':seconds,'elapsed_seconds':elapsed,'wire':dict(wire),'counters_delta':delta,
            'interval_p50':percentile(.5),'interval_p95':percentile(.95),'interval_p99':percentile(.99),'max_interval':percentile(1),
            'observed_contexts':len(identities),'errors':errors,'checks':checks,'passed':all(checks.values()),
            'official_recording_is_separate':True,'browser_receipt_is_not_audience_receipt':True}
        write_json(self.folder/'cohost.json',report)
        if seconds in {1800,7200}:
            record_gate(self.root,'cohost_'+str(seconds),checks,[(self.folder/'cohost.json').relative_to(self.root).as_posix(),
                (self.folder/'samples.jsonl').relative_to(self.root).as_posix()])
        return report

    def close(self):self.owner.close()


def review_gate(root,relative):
    review=read_json(inside(root,relative));candidate=require_candidate(root,hardware=False)
    if (review.get('candidate_id')!=candidate['candidate_id'] or not review.get('reviewer')
        or not review.get('actual_evidence_reviewed') or review.get('historical_result_inherited') is not False):
        raise AdmissionError('ACTUAL_CURRENT_CANDIDATE_REVIEW_REQUIRED')
    if (review.get('gate') not in REVIEW_CHECKS or set(review.get('checks',{}))!=REVIEW_CHECKS[review['gate']]
        or not review.get('artifacts')):
        raise AdmissionError('GATE_SPECIFIC_CHECKLIST_AND_ACTUAL_EXTERNAL_EVIDENCE_REQUIRED')
    for row in review.get('artifacts',[]):
        if file_hash(inside(root,row['path']))!=row['sha256']:raise AdmissionError('REVIEW_ARTIFACT_CHANGED')
    return record_gate(root,review['gate'],review['checks'],[relative,*[r['path'] for r in review['artifacts']]],review.get('details'))


def templates(root):
    candidate=require_candidate(root,hardware=False);paths=[]
    for name,checks in REVIEW_CHECKS.items():
        path=inside(root,'state/issac-acceptance/review-templates/'+candidate['candidate_id']+'/'+name+'.json')
        if path.exists():continue
        write_json(path,{**candidate,'gate':name,'reviewer':None,'actual_evidence_reviewed':False,
            'historical_result_inherited':False,'checks':{key:False for key in sorted(checks)},'artifacts':[],
            'details':None})
        paths.append(path.relative_to(root).as_posix())
    return {'templates':paths,'passed_gates_created':0}


async def verify_during_media(root,protection):
    await asyncio.to_thread(require_candidate,root,hardware=False)
    await asyncio.to_thread(protection.verify)


def failed_check_names(value):
    checks=value.get('checks',value.get('results',{}))
    if isinstance(checks,dict):return [k for k,v in checks.items() if v is False]
    if isinstance(checks,list):
        return [str(row.get('check',row.get('test','unknown'))) for row in checks
                if isinstance(row,dict) and (row.get('passed') is False or row.get('exit_code',0)!=0)]
    return []


def close_phase(root):
    candidate=require_candidate(root,hardware=False);failures=[]
    for path in sorted(inside(root,'state/issac-acceptance').rglob('*.json')):
        value=read_json(path)
        if isinstance(value,dict) and value.get('candidate_id')==candidate['candidate_id'] and value.get('passed') is False:
            failures.append({'path':path.relative_to(root).as_posix(),'sha256':file_hash(path),
                'failed_checks':failed_check_names(value)})
    result={**candidate,'phase':'acceptance_closed','defects':failures,'recorded_failures':len(failures),
        'complete_acceptance_requires_all_18_verified_gates':True,
        'next_action':'whole_correction_round_then_freeze' if failures else 'review_all_remaining_gates',
        'source_changes_permitted_only_in_new_development_round':True,'closed_unix':time.time()}
    write_json(inside(root,'state/issac-acceptance/closed-phases/'+candidate['candidate_id']+'.json'),result)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('action',choices=['regressions','cohost','review','release','templates','close-phase']);parser.add_argument('--seconds',type=int)
    parser.add_argument('--review');args=parser.parse_args();root=args.root.resolve()
    if args.action=='templates':result=templates(root)
    elif args.action=='close-phase':result=close_phase(root)
    elif args.action=='review':result=review_gate(root,args.review)
    elif args.action=='release':result=verify_gates(root);write_json(inside(root,'state/issac-acceptance/release.json'),result)
    else:
        runner=Runner(root)
        try:result=runner.regressions() if args.action=='regressions' else asyncio.run(runner.cohost(args.seconds))
        finally:runner.close()
    print(json.dumps(result,ensure_ascii=False))
    if result.get('passed') is False:raise SystemExit(1)


if __name__=='__main__':main()
