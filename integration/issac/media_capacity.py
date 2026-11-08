"""Measure the frozen media models together; this never approves live quality."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import subprocess
import time
import uuid

from .common import AdmissionError,FileLease,digest,file_hash,inside,read_json,write_json
from .deployment import require_candidate
from .materials import MATERIAL_ROOT,OPEN_ANCHOR
from .preparation import runtime_environment
from .resources import MEDIA_RESERVE_MIB,HOST_MARGIN_MIB,MIB,available_for_initialization,snapshot


def input_signature(root):
    media=read_json(inside(root,'configs/issac/runtime.json'))['media']
    return digest({'media':media,'voice_profile':file_hash(inside(root,'assets/naimei/voice-final-v1/profile.json')),
        'voice_models':file_hash(inside(root,'configs/naimei/voice-models.json')),
        'oral_conditioning_anchor':file_hash(inside(root,MATERIAL_ROOT+'/'+OPEN_ANCHOR))})


def measured_reserves(report):
    """Keep all original margins and add 2 GiB above the measured media peak."""
    if (report.get('passed') is not True or report.get('scope')!='capacity_only'
            or report.get('quality_accepted') is not False or report.get('normal_cleanup') is not True
            or report.get('concurrent_residency_observed') is not True
            or report.get('foreign_jobs_observed') is not False):
        raise AdmissionError('ACTUAL_CONCURRENT_MEDIA_CAPACITY_REQUIRED')
    actors=report.get('actors',{})
    if set(actors)!={'voice','mouth'}:raise AdmissionError('BOTH_REAL_MEDIA_ACTORS_REQUIRED')
    for role,row in actors.items():
        if (row.get('role')!=role or row.get('passed') is not True or row.get('exit_code')!=0
                or type(row.get('cuda_peak_reserved_bytes')) is not int or row['cuda_peak_reserved_bytes']<=0
                or type(row.get('host_peak_bytes')) is not int or row['host_peak_bytes']<=0):
            raise AdmissionError('ACTUAL_MEDIA_ACTOR_PEAKS_REQUIRED')
    voice=actors['voice'];mouth=actors['mouth']
    if (voice.get('voice_id')!='NCM01' or voice.get('precision')!='torch.float16'
            or voice.get('steps')!=32 or voice.get('reference_preprocess_prompt') is not False
            or mouth.get('actual_new_frames',0)<288 or mouth.get('steps')!=4 or mouth.get('batch')!=1
            or mouth.get('width')!=512 or mouth.get('height')!=512
            or mouth.get('compile_mode')!='model-vae' or mouth.get('fast_rope') is not True):
        raise AdmissionError('FROZEN_MEDIA_SETTINGS_REQUIRED')
    gpu_peak=report.get('observed_gpu_delta_bytes');host_peak=report.get('observed_host_delta_bytes')
    if type(gpu_peak) is not int or gpu_peak<=0 or type(host_peak) is not int or host_peak<0:
        raise AdmissionError('ACTUAL_MEDIA_OBSERVATIONS_REQUIRED')
    gpu_peak=max(gpu_peak,sum(r['cuda_peak_reserved_bytes'] for r in actors.values()))
    host_peak=max(host_peak,sum(r['host_peak_bytes'] for r in actors.values()))
    media_mib=math.ceil(gpu_peak/MIB)+2048
    # The original 6 GiB host allowance remains the minimum. If measured media
    # plus 2 GiB headroom exceeds it, reserve the difference as well.
    host_extra=max(0,math.ceil(host_peak/MIB)+2048-HOST_MARGIN_MIB)
    return {'media_reserve_mib':media_mib,'host_extra_reserve_mib':host_extra,
            'measured_gpu_peak_bytes':gpu_peak,'measured_host_peak_bytes':host_peak,
            'media_headroom_mib':2048,'host_headroom_mib':2048}


def budget(root,candidate):
    fallback={'media_reserve_mib':MEDIA_RESERVE_MIB,'host_extra_reserve_mib':0,'source':'unmeasured_default'}
    pointer=inside(root,'.setup/issac-media-capacity.json')
    if not pointer.is_file():return fallback
    row=read_json(pointer)
    if row.get('candidate_id')!=candidate:return fallback
    path=inside(root,row['report'])
    if file_hash(path)!=row.get('sha256'):raise AdmissionError('MEDIA_CAPACITY_REPORT_CHANGED')
    report=read_json(path)
    age=time.time()-report.get('finished_unix',0)
    if (report.get('candidate_id')!=candidate or report.get('input_signature')!=input_signature(root)
            or not -5<=age<=24*3600):
        raise AdmissionError('CURRENT_FROZEN_MEDIA_CAPACITY_REQUIRED')
    for item in report.get('artifacts',[]):
        if file_hash(inside(root,item['path']))!=item['sha256']:
            raise AdmissionError('MEDIA_CAPACITY_ARTIFACT_CHANGED')
    if {x.get('role') for x in report.get('artifacts',[])}!={'voice','mouth'}:
        raise AdmissionError('BOTH_REAL_MEDIA_REPORTS_REQUIRED')
    for item in report['artifacts']:
        actual=read_json(inside(root,item['path']))
        expected=dict(report['actors'][item['role']]);expected.pop('exit_code',None)
        if actual!=expected:raise AdmissionError('MEDIA_CAPACITY_ACTOR_CHANGED')
    return {**measured_reserves(report),'source':'actual_concurrent_models',
            'report':row['report'],'report_sha256':row['sha256']}


def run(root):
    candidate=require_candidate(root);folder=inside(root,'state/issac-acceptance/media-capacity')/uuid.uuid4().hex
    folder.mkdir(parents=True);stop=folder/'stop';children={};identities={};logs=[];samples=[];actors={}
    initial=snapshot();started=time.time();foreign=False;normal=False
    if not available_for_initialization(initial,MEDIA_RESERVE_MIB+4096):
        raise AdmissionError('EXISTING_GPU_TASKS_RETAINED_WAIT_FOR_MEDIA_PROBE')
    def progress(stage,**values):
        write_json(folder/'progress.json',{**candidate,'stage':stage,'started_unix':started,'at_unix':time.time(),**values})
        print(__import__('json').dumps({'stage':stage,**values},ensure_ascii=False),flush=True)
    def observe():
        nonlocal foreign
        row=snapshot();samples.append(row)
        if row.get('comfy_running_jobs'):foreign=True;raise AdmissionError('FOREIGN_GPU_JOB_STARTED_MEDIA_PROBE_STOPPED')
        return row
    def wait_ready(role,seconds):
        end=time.monotonic()+seconds;last=0;report=folder/(role+'.json')
        while time.monotonic()<end:
            if children[role].poll() is not None:raise AdmissionError('MEDIA_ACTOR_EXITED_BEFORE_MEASUREMENT_'+role.upper())
            if report.is_file():
                row=read_json(report)
                if row.get('passed') is False:raise AdmissionError('MEDIA_ACTOR_FAILED_'+role.upper()+'_'+str(row.get('error')))
                if row.get('stage')=='measured':return row
            observe()
            if time.monotonic()-last>=15:
                progress('waiting_for_'+role,actor_pid=children[role].pid,remaining_seconds=max(0,end-time.monotonic()));last=time.monotonic()
            time.sleep(2)
        raise AdmissionError('BOUNDED_MEDIA_MEASUREMENT_DEADLINE_'+role.upper())
    with FileLease(inside(root,'state/issac-acceptance/media-capacity.lock')):
        try:
            config=read_json(inside(root,'configs/issac/runtime.json'))['native_paths']
            for role,kind,key,timeout in [('voice','voice','voice_python',900),('mouth','engine','media_python',1800)]:
                log=(folder/(role+'.log')).open('wb');logs.append(log)
                command=[str(inside(root,config[key])),'-X','utf8','-B','-m','integration.issac.media_capacity_worker',
                    '--root',str(root),'--folder',str(folder),'--role',role]
                children[role]=subprocess.Popen(command,cwd=root,env=runtime_environment(root,kind),stdout=log,
                    stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=0x08000000)
                import psutil
                identities[role]=psutil.Process(children[role].pid).create_time()
                actors[role]=wait_ready(role,timeout)
                if role=='mouth' and children['voice'].poll() is not None:
                    raise AdmissionError('VOICE_NOT_RESIDENT_DURING_MOUTH_MEASUREMENT')
            observe();normal=True
        finally:
            stop.touch()
            for role,process in children.items():
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    # A Windows venv launcher can have a separate Python child.
                    # Only this exact probe launch tree may be stopped.
                    import psutil
                    parent=psutil.Process(process.pid)
                    if parent.create_time()!=identities[role]:
                        raise AdmissionError('MEDIA_PROBE_WORKER_IDENTITY_CHANGED')
                    targets=[parent,*parent.children(recursive=True)]
                    exact=[(p,p.create_time()) for p in targets]
                    for p,created in reversed(exact):
                        try:
                            if p.create_time()==created:p.terminate()
                        except psutil.NoSuchProcess:pass
                    _,alive=psutil.wait_procs(targets,timeout=10)
                    if alive:raise AdmissionError('OWN_MEDIA_PROBE_WORKERS_NOT_CLOSED')
                    process.wait(timeout=10);normal=False
                if role in actors:actors[role]['exit_code']=process.returncode
            for log in logs:log.close()
            progress('workers_closed',normal_cleanup=normal)
        verified=require_candidate(root,hardware=False)
        out={**verified,'scope':'capacity_only','quality_accepted':False,'passed':normal,'normal_cleanup':normal,
            'concurrent_residency_observed':len(actors)==2,'foreign_jobs_observed':foreign,'actors':actors,
            'initial':initial,'samples':samples,'input_signature':input_signature(root),
            'observed_gpu_delta_bytes':max((initial['gpu_free_mib']-s['gpu_free_mib'])*MIB for s in samples),
            'observed_host_delta_bytes':max(0,max(initial['host_available_bytes']-s['host_available_bytes'] for s in samples)),
            'finished_unix':time.time(),'artifacts':[{'role':role,'path':(folder/(role+'.json')).relative_to(root).as_posix(),
                'sha256':file_hash(folder/(role+'.json'))} for role in actors]}
        out['reserves']=measured_reserves(out)
        write_json(folder/'report.json',out)
        pointer={'candidate_id':candidate['candidate_id'],'report':(folder/'report.json').relative_to(root).as_posix(),
                 'sha256':file_hash(folder/'report.json')}
        write_json(inside(root,'.setup/issac-media-capacity.json'),pointer)
        progress('complete',report=pointer['report'],reserves=out['reserves'])
        return out


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();run(args.root.resolve())
