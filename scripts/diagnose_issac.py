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
import urllib.error
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integration.issac.common import AdmissionError,FileLease,file_hash,inside,read_json,write_json
from integration.issac.deployment import require_candidate
from integration.issac.preparation import relocate_native_environments,runtime_environment
from integration.issac.offline_dependencies import install_voice_dependencies
from integration.issac.strategy_dsh import bridge_token


def json_http(root,url,body=None,timeout=5):
    request=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json','X-Isaac-Token':bridge_token(root)})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request,timeout=timeout) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        try:code=json.loads(error.read(8192)).get('error','')
        except (ValueError,AttributeError):code=''
        if not isinstance(code,str) or not code or len(code)>160 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for c in code):
            code='LOCAL_DIAGNOSTIC_HTTP_REJECTED_'+str(error.code)
        raise AdmissionError(code) from None


def wait_native_observation(root,timeout=45):
    """A Lua pointer appears before the main-menu Lua API can answer."""
    deadline=time.monotonic()+timeout;last_error='NATIVE_BRIDGE_NOT_READY'
    while time.monotonic()<deadline:
        try:return json_http(root,'http://127.0.0.1:9534/control',{'action':'observe'},12)
        except AdmissionError as error:
            if str(error) not in {'NATIVE_BRIDGE_REQUEST_FAILED','GAME_NATIVE_SAVE_ABI_NOT_CONFIRMED'}:raise
            last_error=str(error)
        except (OSError,ValueError):last_error='NATIVE_OBSERVATION_TRANSPORT_NOT_READY'
        time.sleep(.5)
    raise AdmissionError('NATIVE_OBSERVATION_READY_DEADLINE_'+last_error)


def close_idle_window(root,record,observe):
    """Normal WM_CLOSE only after two current, real no-player observations."""
    before=observe();time.sleep(.2);confirmed=observe()
    if any(type(row.get('players')) is not int or row['players']!=0 for row in (before,confirmed)):
        raise AdmissionError('LIVING_OR_UNKNOWN_GAME_PRESERVED')
    import win32gui,win32process,win32con
    process=process_identity(root,record);windows=[]
    def collect(hwnd,_):
        if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1]==record['pid'] and 'Binding of Isaac' in win32gui.GetWindowText(hwnd):windows.append(hwnd)
    win32gui.EnumWindows(collect,None)
    if len(windows)!=1:raise AdmissionError('UNIQUE_OWN_IDLE_GAME_WINDOW_REQUIRED')
    process_identity(root,record)
    final=observe()
    if type(final.get('players')) is not int or final['players']!=0:raise AdmissionError('LIVING_OR_UNKNOWN_GAME_PRESERVED')
    win32gui.PostMessage(windows[0],win32con.WM_CLOSE,0,0);process.wait(15)
    return {'own_idle_game_closed_normally':True,'pid':record['pid'],'forced_termination':False}


def close_owned_idle_game(root,expected_id):
    """Recover an explicitly identified closed phase's own idle menu."""
    import psutil
    from integration.issac.native_game import NativeGame
    from integration.issac.saves import SaveProtection
    registry=read_json(inside(root,'state/issac-stream/application.json'))
    if not expected_id or registry['installation_id']!=expected_id:
        raise AdmissionError('EXPLICIT_PREVIOUS_INSTALLATION_ID_REQUIRED')
    closed=read_json(inside(root,'state/issac-acceptance/closed-phases/'+registry['candidate_id']+'.json'))
    if closed.get('phase')!='acceptance_closed' or not closed.get('recorded_failures'):
        raise AdmissionError('CLOSED_FAILED_PHASE_REQUIRED_FOR_IDLE_CLOSE')
    games=[r for r in registry['processes'] if r['name']=='isaac-game']
    if len(games)!=1:raise AdmissionError('UNIQUE_REGISTERED_PREVIOUS_GAME_REQUIRED')
    with FileLease(inside(root,'state/issac-stream/application.lock')),FileLease(inside(root,'state/isaac-strategy/host.lock')):
        for record in registry['processes']:
            if record['name']=='isaac-game':continue
            try:process_identity(root,record)
            except psutil.NoSuchProcess:continue
            raise AdmissionError('PREVIOUS_COMPONENT_STILL_LIVE')
        game=games[0]
        try:process_identity(root,game)
        except psutil.NoSuchProcess:return {'own_game_already_ended':True,'forced_termination':False}
        protection=SaveProtection(root);protection.verify();native=NativeGame(root,protection)
        try:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if native.attach(game['pid']).get('lua_ready'):break
                time.sleep(.5)
            else:raise AdmissionError('IDLE_RECOVERY_NATIVE_ATTACH_DEADLINE')
            # No assumption is made from the old failed observation or a PID.
            result=close_idle_window(root,game,native.observe)
        finally:native.close()
        protection.verify()
        return {**result,'previous_installation_id':expected_id,'previous_candidate_id':registry['candidate_id'],
                'accepted_fault_recovery':False,'foreign_processes_terminated':0}


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


def dependency_code(kind):
    modules={
        'game':['frida','lupa.lua53','psutil','win32gui','PIL.Image'],
        'studio':['torch','cv2','numpy','aiohttp'],
        'voice':['torch','transformers','omnivoice']}[kind]
    return '\n'.join([
        'import faulthandler,importlib,json,sys,time',
        'from pathlib import Path',
        'faulthandler.enable();faulthandler.dump_traceback_later(60,repeat=True)',
        'sys.path.insert(0,str(Path.cwd()/"src/tts-benchmark/omnivoice"))' if kind=='voice' else 'pass',
        'print(json.dumps({"stage":"interpreter_ready","kind":'+repr(kind)+'}),flush=True)',
        'for name in '+repr(modules)+':',
        ' print(json.dumps({"stage":"import_begin","module":name}),flush=True)',
        ' started=time.monotonic();module=importlib.import_module(name)',
        ' if name=="torch":assert module.__version__=="2.9.1+cu128"',
        ' print(json.dumps({"stage":"import_complete","module":name,"seconds":time.monotonic()-started}),flush=True)',
        'faulthandler.cancel_dump_traceback_later()',
        'print(json.dumps({"stage":"dependencies_ready","kind":'+repr(kind)+'}),flush=True)'])


def dependencies(root,folder):
    config=read_json(inside(root,'configs/issac/runtime.json'))['native_paths']
    probes={
      'game':('game_python',60),'studio':('media_python',180),'voice':('voice_python',300)}
    results=[]
    for kind,(key,deadline) in probes.items():
        log=folder/('dependencies-'+kind+'.log');started=time.monotonic()
        with log.open('wb') as output:
            try:
                result=subprocess.run([str(inside(root,config[key])),'-X','utf8','-B','-u','-c',dependency_code(kind)],cwd=root,
                    env=runtime_environment(root,kind),stdout=output,stderr=subprocess.STDOUT,timeout=deadline,creationflags=0x08000000)
                row={'kind':kind,'passed':result.returncode==0,'exit_code':result.returncode}
            except subprocess.TimeoutExpired:row={'kind':kind,'passed':False,'reason':'DEPENDENCY_IMPORT_DEADLINE'}
        stages=[]
        for line in log.read_text('utf8',errors='replace').splitlines():
            try:value=json.loads(line)
            except ValueError:continue
            if isinstance(value,dict) and value.get('stage') in {'interpreter_ready','import_begin','import_complete','dependencies_ready'}:
                stages.append({k:value[k] for k in ('stage','module','kind','seconds') if k in value})
        results.append({**row,'seconds':time.monotonic()-started,'deadline_seconds':deadline,
                        'observed_import_stages':stages,'log':log.relative_to(root).as_posix(),'sha256':file_hash(log)})
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
                except AdmissionError as error:
                    if str(error) not in {'NATIVE_BRIDGE_ATTACH_FAILED','NATIVE_BRIDGE_REQUEST_FAILED'}:raise
                except (OSError,ValueError):pass
                time.sleep(.5)
            else:raise AdmissionError('PROBE_NATIVE_ATTACH_DEADLINE')
            observation=wait_native_observation(root)
            checks['real_native_observation']=isinstance(observation.get('observation'),dict)
            modules=json_http(root,'http://127.0.0.1:9534/control',{'action':'modules'},12)
            checks['pinned_game_modules']=modules.get('modules_ready') is True
            pause=json_http(root,'http://127.0.0.1:9534/control',{'action':'pause'},12)['native_receipt']
            checks['normal_pause_or_idle']=pause.get('no_active_run') is True or pause.get('normal_game_pause_acknowledged') is True
            # This probe owns the new idle menu only. Never close a living run.
            if observation['observation']['players']==0:
                closed=close_idle_window(root,game,lambda:json_http(root,'http://127.0.0.1:9534/control',{'action':'observe'},12)['observation'])
                checks['own_idle_game_closed_normally']=closed['own_idle_game_closed_normally']
        finally:
            try:json_http(root,'http://127.0.0.1:9541/action',{'action':'stop'},5)
            except (OSError,ValueError,AdmissionError):pass
            try:code=handle.wait(180)
            except subprocess.TimeoutExpired:code=None
            checks['owned_stack_stopped']=code==0
    return {'passed':all(checks.values()),'checks':checks,'observation':observation,
            'log':log.relative_to(root).as_posix(),'autopilot_enabled':False,'normal_full_run_accepted':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('action',choices=['environment','dependencies','owned-status','retire-stalled-owner','close-owned-idle-game','native-game','model-prepare'])
    parser.add_argument('--capacity-wait-seconds',type=int,default=0)
    parser.add_argument('--expected-installation-id');args=parser.parse_args();root=args.root.resolve()
    if os.name!='nt' or root!=Path('C:/dev/虚拟数字人直播/issac').resolve():raise AdmissionError('PINNED_NATIVE_DIAGNOSTIC_ROOT_REQUIRED')
    candidate=require_candidate(root,hardware=False)
    folder=inside(root,'state/issac-acceptance/diagnostics')/(args.action+'-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    try:
        if args.action=='environment':
            result=relocate_native_environments(root)
            result['voice_inference_dependencies']=install_voice_dependencies(root)
        elif args.action=='dependencies':result=dependencies(root,folder)
        elif args.action=='owned-status':result=owned_status(root)
        elif args.action=='retire-stalled-owner':result=retire_stalled_owner(root,args.expected_installation_id,folder)
        elif args.action=='close-owned-idle-game':result=close_owned_idle_game(root,args.expected_installation_id)
        elif args.action=='native-game':result=native_game_probe(root,folder)
        else:
            from integration.issac.local_model import LocalModel
            result=LocalModel(root).prepare(capacity_wait_seconds=args.capacity_wait_seconds)
        result={**candidate,**result};require_candidate(root,hardware=False)
        write_json(folder/'report.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
        if result.get('passed') is False:raise SystemExit(1)
    except Exception as error:
        result={**candidate,'passed':False,'error':str(error) if isinstance(error,AdmissionError) else type(error).__name__}
        write_json(folder/'report.json',result);print(json.dumps(result,ensure_ascii=False),flush=True);raise


if __name__=='__main__':main()
