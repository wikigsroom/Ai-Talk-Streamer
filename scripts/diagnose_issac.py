"""Frozen native probes and narrowly scoped retirement of a closed failed run."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integration.issac.common import AdmissionError,file_hash,inside,read_json,write_json
from integration.issac.deployment import require_candidate
from integration.issac.preparation import relocate_native_environments,runtime_environment
from integration.issac.strategy_dsh import bridge_token


def json_http(root,url,body=None,timeout=5):
    request=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json','X-Isaac-Token':bridge_token(root)})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=timeout) as response:return json.load(response)


def process_identity(root,row):
    import psutil
    process=psutil.Process(row['pid']);path=Path(process.exe()).resolve()
    if (process.create_time()!=row['created_at'] or path!=Path(row['executable']).resolve()
            or not path.is_relative_to(root) or file_hash(path)!=row['executable_sha256']):
        raise AdmissionError('DIAGNOSTIC_PROCESS_IDENTITY_CHANGED')
    return process


def owned_status(root):
    import psutil
    from integration.issac.resources import snapshot
    registry=read_json(inside(root,'state/issac-stream/application.json'))
    rows=[]
    for row in registry['processes']:
        try:
            process=process_identity(root,row)
            rows.append({'name':row['name'],'pid':process.pid,'alive':True,
                'children':[{'pid':p.pid,'created_at':p.create_time(),'executable':p.exe()} for p in process.children(recursive=True)]})
        except psutil.NoSuchProcess:rows.append({'name':row['name'],'pid':row['pid'],'alive':False})
    return {'installation_id':registry['installation_id'],'candidate_id':registry['candidate_id'],
            'stage':registry['stage'],'processes':rows,'resources':snapshot()}


def dependencies(root,folder):
    config=read_json(inside(root,'configs/issac/runtime.json'))['native_paths']
    probes={
      'game':('game_python','import frida,lupa.lua53,psutil,win32gui;from PIL import Image;print("native_game_dependencies_ok")'),
      'studio':('media_python','import torch,cv2,numpy,aiohttp;assert torch.__version__=="2.9.1+cu128";print("native_media_dependencies_ok",torch.__version__)'),
      'voice':('voice_python','import sys;from pathlib import Path;sys.path.insert(0,str(Path.cwd()/"src/tts-benchmark/omnivoice"));import torch,transformers,omnivoice;assert torch.__version__=="2.9.1+cu128";print("native_voice_dependencies_ok",torch.__version__,transformers.__version__)')}
    results=[]
    for kind,(key,code) in probes.items():
        log=folder/('dependencies-'+kind+'.log');started=time.monotonic()
        with log.open('wb') as output:
            try:
                result=subprocess.run([str(inside(root,config[key])),'-X','utf8','-B','-c',code],cwd=root,
                    env=runtime_environment(root,kind),stdout=output,stderr=subprocess.STDOUT,timeout=120,creationflags=0x08000000)
                row={'kind':kind,'passed':result.returncode==0,'exit_code':result.returncode}
            except subprocess.TimeoutExpired:row={'kind':kind,'passed':False,'reason':'DEPENDENCY_IMPORT_DEADLINE'}
        results.append({**row,'seconds':time.monotonic()-started,'log':log.relative_to(root).as_posix(),'sha256':file_hash(log)})
    return {'passed':all(x['passed'] for x in results),'probes':results,'models_loaded':False}


def retire_stalled_owner(root,expected_id,folder):
    """Explicit recovery operation, never a success/fault-acceptance shortcut.

    It is available only after the previous phase is closed as failed and the
    registered game has ended. SQLite backup precedes any forced own-process
    retirement; unknown/foreign PIDs and new incarnations are preserved.
    """
    import psutil
    registry=read_json(inside(root,'state/issac-stream/application.json'))
    if not expected_id or registry['installation_id']!=expected_id:
        raise AdmissionError('EXPLICIT_PREVIOUS_INSTALLATION_ID_REQUIRED')
    closed=read_json(inside(root,'state/issac-acceptance/closed-phases/'+registry['candidate_id']+'.json'))
    if closed.get('phase')!='acceptance_closed' or not closed.get('recorded_failures'):
        raise AdmissionError('CLOSED_FAILED_PHASE_REQUIRED_FOR_STALLED_RETIREMENT')
    if not any(word in registry['stage'] for word in ('stop','cleanup')):
        raise AdmissionError('PREVIOUS_OWNER_NOT_ALREADY_STOPPING')
    games=[r for r in registry['processes'] if r['name']=='isaac-game']
    for row in games:
        try:
            process_identity(root,row)
            raise AdmissionError('GAME_STILL_LIVE_REQUIRES_NORMAL_PAUSE_AND_CLOSE')
        except psutil.NoSuchProcess:pass
    # Preserve a consistent copy of every owned SQLite store, even if its
    # writer is stuck. SQLite's backup API includes committed WAL contents.
    shutil.copy2(inside(root,'state/issac-stream/application.json'),folder/'previous-owner.json')
    backups=[]
    for parent in ('state/isaac-strategy','state/issac-stream'):
        for path in inside(root,parent).rglob('*'):
            if not path.is_file() or path.suffix.lower() not in {'.sqlite','.sqlite3','.db'}:continue
            with path.open('rb') as stream:
                if stream.read(16)!=b'SQLite format 3\x00':continue
            destination=folder/'databases'/path.relative_to(root);destination.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10) as source,sqlite3.connect(destination) as target:
                source.backup(target,pages=256,sleep=.05)
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise AdmissionError('RETIREMENT_DATABASE_BACKUP_INVALID')
            backups.append({'path':destination.relative_to(root).as_posix(),'sha256':file_hash(destination)})
    retired=[]
    allowed={'strategy-dsh','model-gateway','game-controller','narrator','studio','voice','flashhead'}
    for name in ('narrator','studio','flashhead','voice','strategy-dsh','model-gateway','game-controller'):
        rows=[r for r in registry['processes'] if r['name']==name]
        if len(rows)>1:raise AdmissionError('DUPLICATE_PREVIOUS_COMPONENT_RECORD')
        if not rows:continue
        row=rows[0]
        if name not in allowed:raise AdmissionError('FIXED_STALLED_COMPONENT_REQUIRED')
        try:process=process_identity(root,row)
        except psutil.NoSuchProcess:continue
        stop=Path(row['stop_file']).resolve()
        if (stop.parent!=inside(root,'state/issac-stream/stop-requests')
                or stop.name!=expected_id+'-'+name+'.stop'):raise AdmissionError('PREVIOUS_STOP_FILE_SCOPE_INVALID')
        stop.write_text(expected_id,encoding='ascii')
        try:process.wait(10);continue
        except psutil.TimeoutExpired:pass
        descendants=process.children(recursive=True)
        owned=[]
        for child in descendants:
            path=Path(child.exe()).resolve()
            if not path.is_relative_to(root/'runtime') and not path.is_relative_to(root/'tools/node'):
                raise AdmissionError('UNKNOWN_STALLED_PROCESS_CHILD_PRESERVED')
            owned.append({'pid':child.pid,'created_at':child.create_time(),'executable':str(path),'executable_sha256':file_hash(path)})
        for item in [*reversed(owned),row]:
            try:
                target=process_identity(root,item)
                target.terminate();target.wait(10)
                retired.append({'name':name,'pid':item['pid'],'clean':False,'reason':'closed_failed_idle_owner_cleanup_deadline'})
            except psutil.NoSuchProcess:pass
    # Let the still-running previous application finish its own cleanup first.
    try:app=psutil.Process(registry['pid'])
    except psutil.NoSuchProcess:
        return {'retired':retired,'database_backups':backups,'accepted_fault_recovery':False,
                'foreign_processes_terminated':0,'public_broadcast_started':False}
    if app.create_time()!=registry['created_at'] or not Path(app.exe()).resolve().is_relative_to(root/'runtime'):
        raise AdmissionError('PREVIOUS_APPLICATION_IDENTITY_CHANGED')
    try:app.wait(60)
    except psutil.TimeoutExpired:
        # All registered components and the game must be dead before retiring
        # an application that now holds only its own process/metadata lock.
        for row in registry['processes']:
            try:process_identity(root,row);raise AdmissionError('PREVIOUS_COMPONENT_STILL_LIVE')
            except psutil.NoSuchProcess:pass
        if app.children():raise AdmissionError('UNREGISTERED_APPLICATION_CHILD_PRESERVED')
        app.terminate();app.wait(10)
        retired.append({'name':'application','pid':app.pid,'clean':False})
    return {'retired':retired,'database_backups':backups,'accepted_fault_recovery':False,
            'foreign_processes_terminated':0,'public_broadcast_started':False}


def native_game_probe(root,folder):
    import psutil,win32gui,win32process,win32con
    candidate=require_candidate(root)
    config=read_json(inside(root,'configs/issac/runtime.json'))
    game_py=inside(root,config['native_paths']['game_python'])
    log=folder/'game-stack.log';checks={};observation=None;handle=None
    with log.open('wb') as output:
        handle=subprocess.Popen([str(game_py),'-X','utf8','-B',str(inside(root,'scripts/start_issac.py')),
            '--root',str(root),'--components','game'],cwd=root,env=runtime_environment(root,'game'),
            stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=0x08000200)
        try:
            deadline=time.monotonic()+150
            while time.monotonic()<deadline:
                if handle.poll() is not None:raise AdmissionError('PROBE_APPLICATION_EXITED')
                try:
                    status=json_http(root,'http://127.0.0.1:9541/status')
                    if status['candidate_id']==candidate['candidate_id'] and status['stage']=='running_candidate_not_accepted':break
                except (OSError,ValueError):pass
                time.sleep(.5)
            else:raise AdmissionError('PROBE_APPLICATION_READY_DEADLINE')
            game=json_http(root,'http://127.0.0.1:9541/action',{'action':'launch_game'},20)
            process=process_identity(root,game)
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                try:
                    attached=json_http(root,'http://127.0.0.1:9534/control',{'action':'attach','pid':game['pid']},10)
                    if attached.get('lua_ready'):break
                except (OSError,ValueError):pass
                time.sleep(.5)
            else:raise AdmissionError('PROBE_NATIVE_ATTACH_DEADLINE')
            observation=json_http(root,'http://127.0.0.1:9534/control',{'action':'observe'},12)
            checks['real_native_observation']=isinstance(observation.get('observation'),dict)
            modules=json_http(root,'http://127.0.0.1:9534/control',{'action':'modules'},12)
            checks['pinned_game_modules']=modules.get('modules_ready') is True
            pause=json_http(root,'http://127.0.0.1:9534/control',{'action':'pause'},12)['native_receipt']
            checks['normal_pause_or_idle']=pause.get('no_active_run') is True or pause.get('normal_game_pause_acknowledged') is True
            # This probe owns the new idle menu only. Never close a living run.
            if observation['observation']['players']==0:
                windows=[]
                def collect(hwnd,_):
                    if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1]==game['pid'] and 'Binding of Isaac' in win32gui.GetWindowText(hwnd):windows.append(hwnd)
                win32gui.EnumWindows(collect,None)
                if len(windows)!=1:raise AdmissionError('PROBE_UNIQUE_IDLE_GAME_WINDOW_REQUIRED')
                process_identity(root,game)
                win32gui.PostMessage(windows[0],win32con.WM_CLOSE,0,0);process.wait(15)
                checks['own_idle_game_closed_normally']=True
        finally:
            try:json_http(root,'http://127.0.0.1:9541/action',{'action':'stop'},5)
            except (OSError,ValueError):pass
            try:code=handle.wait(180)
            except subprocess.TimeoutExpired:code=None
            checks['owned_stack_stopped']=code==0
    return {'passed':all(checks.values()),'checks':checks,'observation':observation,
            'log':log.relative_to(root).as_posix(),'autopilot_enabled':False,'normal_full_run_accepted':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('action',choices=['environment','dependencies','owned-status','retire-stalled-owner','native-game','model-prepare'])
    parser.add_argument('--expected-installation-id');args=parser.parse_args();root=args.root.resolve()
    if os.name!='nt' or root!=Path('C:/dev/虚拟数字人直播/issac').resolve():raise AdmissionError('PINNED_NATIVE_DIAGNOSTIC_ROOT_REQUIRED')
    candidate=require_candidate(root,hardware=False)
    folder=inside(root,'state/issac-acceptance/diagnostics')/(args.action+'-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    try:
        if args.action=='environment':result=relocate_native_environments(root)
        elif args.action=='dependencies':result=dependencies(root,folder)
        elif args.action=='owned-status':result=owned_status(root)
        elif args.action=='retire-stalled-owner':result=retire_stalled_owner(root,args.expected_installation_id,folder)
        elif args.action=='native-game':result=native_game_probe(root,folder)
        else:
            from integration.issac.local_model import LocalModel
            result=LocalModel(root).prepare()
        result={**candidate,**result};require_candidate(root,hardware=False)
        write_json(folder/'report.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
        if result.get('passed') is False:raise SystemExit(1)
    except Exception as error:
        result={**candidate,'passed':False,'error':str(error) if isinstance(error,AdmissionError) else type(error).__name__}
        write_json(folder/'report.json',result);print(json.dumps(result,ensure_ascii=False),flush=True);raise


if __name__=='__main__':main()
