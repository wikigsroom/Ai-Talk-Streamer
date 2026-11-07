"""Owned native Windows stack; isolated ports, identity receipts and safe stop."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

from .common import AdmissionError,Audit,FileLease,file_hash,inside,port_available,read_json,write_json
from .deployment import require_candidate
from .preparation import prepare_saves,relocate_native_environments,runtime_environment
from .strategy_dsh import bridge_token


class Application:
    def __init__(self, root):
        self.root=Path(root).resolve()
        self.candidate=require_candidate(root)
        self.config=read_json(inside(root,'configs/issac/runtime.json'))
        self.owner=FileLease(inside(root,'state/issac-stream/application.lock')).acquire()
        self.id=uuid.uuid4().hex
        self.token=bridge_token(root)
        self.audit=Audit(inside(root,'state/issac-stream/application-events.jsonl'))
        self.children={}
        self.handles=[]
        self.stop_event=threading.Event()
        self.stage='preparing'
        self.error=None
        self.cleanup_faults=[]
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.server=self.make_server()

    def http(self,url,body=None,timeout=4):
        request=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),
                    headers={'Content-Type':'application/json','X-Isaac-Token':self.token})
        with self.opener.open(request,timeout=timeout) as response:return json.load(response)

    def child(self,name,executable,args,kind,*,cwd=None,environment=None):
        import psutil
        if name in self.children:
            raise AdmissionError('OWNED_COMPONENT_ALREADY_STARTED')
        executable=inside(self.root,executable)
        logs=inside(self.root,'state/issac-stream/process-logs');logs.mkdir(parents=True,exist_ok=True)
        output=(logs/(name+'.log')).open('ab');self.handles.append(output)
        stop=inside(self.root,'state/issac-stream/stop-requests')/(self.id+'-'+name+'.stop')
        stop.parent.mkdir(parents=True,exist_ok=True)
        env=runtime_environment(self.root,kind)
        if environment:env.update(environment)
        env['ISSAC_STOP_FILE']=str(stop)
        process=subprocess.Popen([str(executable),*args],cwd=inside(self.root,cwd) if cwd else self.root,env=env,
                    stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,creationflags=0x08000200)
        launcher=psutil.Process(process.pid)
        identity=launcher
        if executable.name.lower() in {'python.exe','pythonw.exe'} and executable.parent.name.lower()=='scripts':
            deadline=time.monotonic()+3
            while process.poll() is None and time.monotonic()<deadline:
                matches=[p for p in launcher.children() if Path(p.exe()).resolve().is_relative_to(self.root/'runtime')
                         and p.cmdline()[1:]==args and Path(p.exe()).name.lower() in {'python.exe','pythonw.exe'}]
                if len(matches)==1:identity=matches[0];break
                if len(matches)>1:raise AdmissionError('UNIQUE_NATIVE_PYTHON_CHILD_REQUIRED')
                time.sleep(.05)
        record={'name':name,'pid':identity.pid,'created_at':identity.create_time(),'executable':identity.exe(),
                'executable_sha256':file_hash(Path(identity.exe())),'launcher_pid':launcher.pid,
                'launcher_created_at':launcher.create_time(),'launcher_executable':launcher.exe(),
                'launcher_sha256':file_hash(executable),'args':args,'installation_id':self.id,'candidate_id':self.candidate['candidate_id'],
                'stop_file':str(stop)}
        self.children[name]=(process,record)
        self.persist()
        self.audit.append('owned_component_started',name=name,pid=process.pid,created_at=record['created_at'])

    def persist(self):
        import psutil
        write_json(inside(self.root,'state/issac-stream/application.json'),{'installation_id':self.id,'candidate_id':self.candidate['candidate_id'],
            'pid':os.getpid(),'created_at':psutil.Process().create_time(),'stage':self.stage,
            'processes':[record for _,record in self.children.values()],'public_broadcast_allowed':False,
            'error':self.error,'cleanup_faults':self.cleanup_faults})

    def wait_ready(self,name,url,timeout=180):
        deadline=time.monotonic()+timeout
        while not self.stop_event.wait(.5):
            process,_=self.children[name]
            if process.poll() is not None:
                raise AdmissionError('OWNED_COMPONENT_EXITED_'+name.upper())
            try:
                value=self.http(url)
            except Exception:value={}
            if (value.get('stage')=='failed' or value.get('initialization',{}).get('stage')=='failed'
                    or value.get('error') and not value.get('ready')):
                raise AdmissionError('COMPONENT_INITIALIZATION_FAILED_'+name.upper())
            if value.get('ready') or value.get('dsh_ready') or value.get('service')=='issac-native-game':return value
            if time.monotonic()>deadline:raise AdmissionError('COMPONENT_READY_DEADLINE_'+name.upper())
        raise AdmissionError('STARTUP_CANCELLED')

    def prepare(self):
        ports=(1235,3103,3104,8040,8062,9893,9528,9532,9533,9534)
        if not all(port_available(x) for x in ports):
            raise AdmissionError('ISOLATED_PORT_ALREADY_OWNED')
        relocate_native_environments(self.root)
        prepare_saves(self.root)
        self.persist()

    def start(self,components='all'):
        self.prepare()
        node=self.config['native_paths']['node']
        game_py=self.config['native_paths']['game_python']
        media_py=self.config['native_paths']['media_python']
        voice_py=self.config['native_paths']['voice_python']
        root_arg=['--root',str(self.root)]
        self.child('model-gateway',media_py,['-X','utf8','-B','-m','integration.issac.model_gateway',*root_arg],'gateway')
        self.wait_ready('model-gateway','http://127.0.0.1:1235/health',60)
        self.child('game-controller',game_py,['-X','utf8','-B','-m','integration.issac.strategy_host',*root_arg],'game')
        self.wait_ready('game-controller','http://127.0.0.1:9534/status',60)
        from .strategy_dsh import prepare as prepare_dsh
        command,env,dsh_cwd=prepare_dsh(self.root)
        self.child('strategy-dsh',str(Path(command[0]).relative_to(self.root)),command[1:],'game',
                   cwd=str(dsh_cwd.relative_to(self.root)),environment=env)
        dsh=self.wait_ready('strategy-dsh','http://127.0.0.1:9533/status',90)
        expected_model=read_json(inside(self.root,'private/issac/model.json'))['model']
        installed=read_json(inside(self.root,'.setup/isaac-strategy-plugin.json'))
        expected_files={r['name']:r['sha256'] for r in installed['files']}
        actual_files={r['name']:r['sha256'] for r in dsh.get('plugin',{}).get('files',[])}
        required_tools={'isaac_get_state','isaac_get_decision','isaac_lookup','isaac_submit_plan','isaac_wiki_query'}
        if (dsh.get('model')!=expected_model or dsh.get('provider')!='isaac-local' or dsh.get('dshVersion')!='0.2.2-rc.1'
                or dsh.get('pid')!=self.children['strategy-dsh'][1]['pid']
                or dsh.get('plugin',{}).get('version')!=installed['version'] or actual_files!=expected_files
                or dsh.get('prompt',{}).get('complete') is not True or dsh.get('prompt',{}).get('requested_edition')!='rep'
                or dsh.get('completePromptRegistered') is not True or set(dsh.get('restrictedTools',[]))!=required_tools
                or set(dsh.get('registeredTools',[]))!=required_tools):
            raise AdmissionError('ACTUAL_DSH_PLUGIN_PROMPT_TOOLS_OR_LOCAL_MODEL_DIFFER')
        self.audit.append('actual_strategy_host_bound',model=expected_model,plugin=dsh['plugin'],prompt=dsh['prompt'])
        installed.update(runtime_load_verified=True,actual_pid=dsh['pid'],actual_model=expected_model,
                         actual_provider=dsh['provider'],prompt=dsh['prompt'],registered_tools=dsh['registeredTools'])
        write_json(inside(self.root,'.setup/isaac-strategy-plugin.json'),installed)
        if components=='all':
            self.stage='waiting_for_ncm01_capacity_and_initialization';self.persist()
            self.child('voice',voice_py,['-X','utf8','-B','-m','integration.issac.voice',*root_arg],'voice')
            self.wait_ready('voice','http://127.0.0.1:9893/health',7200)
            self.stage='waiting_for_flashhead_capacity_and_compilation';self.persist()
            self.child('flashhead',media_py,['-X','utf8','-B','-m','integration.issac.engine_service',*root_arg],'engine')
            self.wait_ready('flashhead','http://127.0.0.1:8040/health',7200)
            self.child('studio',media_py,['-X','utf8','-B','-m','integration.issac.studio',*root_arg],'studio')
            self.wait_ready('studio','http://127.0.0.1:8062/health',120)
            self.child('narrator',node,['backend/dsh-bridge/issac.mjs',str(self.root)],'narrator')
        self.stage='running_candidate_not_accepted'
        self.persist()
        self.audit.append('stack_started',components=components,candidate_id=self.candidate['candidate_id'])

    def launch_game(self):
        from .saves import SaveProtection,GAME_SHA256
        SaveProtection(self.root).verify()
        path=inside(self.root,'game/isaac-ng.exe')
        if file_hash(path)!=GAME_SHA256:
            raise AdmissionError('PINNED_GAME_CHANGED')
        self.child('isaac-game','game/isaac-ng.exe',['--luadebug'],'game',cwd='game')
        return self.children['isaac-game'][1]

    def stop(self):
        self.stage='stopping';self.persist()
        controller=self.children.get('game-controller')
        if controller and controller[0].poll() is None:
            try:
                receipt=self.http('http://127.0.0.1:9534/control',{'action':'pause'},timeout=12)
                native=receipt.get('native_receipt',{})
                if not any(native.get(k) is True for k in ('normal_game_pause_acknowledged','no_active_run','not_attached','game_process_ended')):
                    raise AdmissionError('NATIVE_GAME_PAUSE_NOT_CONFIRMED')
                self.audit.append('pre_stop_pause',receipt=native)
            except Exception:
                self.stage='stop_blocked_game_pause_unconfirmed';self.error='GAME_PAUSE_ACK_REQUIRED';self.persist()
                raise AdmissionError('STOP_BLOCKED_GAME_PAUSE_UNCONFIRMED') from None
        # Terminate only this run's proven processes. Leave the normally paused
        # game window for inspection; never kill an unrelated pre-existing app.
        import psutil
        order=['narrator','studio','flashhead','voice','strategy-dsh','model-gateway','game-controller']
        for name in order:
            item=self.children.get(name)
            if not item:continue
            process,record=item
            if process.poll() is not None:
                if process.returncode and name not in self.cleanup_faults:self.cleanup_faults.append(name)
                continue
            self.stage='stopping_'+name;self.persist()
            try:current=psutil.Process(record['pid'])
            except psutil.NoSuchProcess:
                # A venv launcher can briefly outlive its actual interpreter.
                try:process.wait(5)
                except subprocess.TimeoutExpired:raise AdmissionError('NATIVE_LAUNCHER_EXIT_NOT_CONFIRMED') from None
                continue
            if (current.create_time()!=record['created_at'] or Path(current.exe()).resolve()!=Path(record['executable']).resolve()
                    or file_hash(Path(current.exe()))!=record['executable_sha256']):
                raise AdmissionError('OWNED_PROCESS_IDENTITY_CHANGED_DURING_STOP')
            Path(record['stop_file']).write_text(self.id,encoding='ascii')
            try:current.wait(45)
            except psutil.TimeoutExpired:
                self.stage='component_cleanup_not_confirmed';self.persist()
                raise AdmissionError('OWNED_COMPONENT_GRACEFUL_STOP_NOT_CONFIRMED_'+name.upper()) from None
            try:code=process.wait(5)
            except subprocess.TimeoutExpired:raise AdmissionError('NATIVE_LAUNCHER_EXIT_NOT_CONFIRMED') from None
            if code and name not in self.cleanup_faults:self.cleanup_faults.append(name)
            self.audit.append('owned_component_stopped',name=name,pid=record['pid'],exit_code=code,
                              clean=code==0,method='owned_stop_request')
        self.stage='stopped_game_preserved_paused'
        if self.cleanup_faults:self.stage='stopped_with_component_cleanup_faults'
        self.persist()

    def make_server(self):
        app=self
        class Handler(BaseHTTPRequestHandler):
            def reply(self,code,data):
                body=json.dumps(data,ensure_ascii=False).encode()
                self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                if self.path!='/status':self.reply(404,{'error':'NOT_FOUND'});return
                self.reply(200,{'stage':app.stage,'installation_id':app.id,'candidate_id':app.candidate['candidate_id'],
                     'error':app.error,'children':{name:{'pid':record['pid'],'alive':process.poll() is None} for name,(process,record) in app.children.items()}})
            def do_POST(self):
                if self.headers.get('Origin') or not hmac.compare_digest(self.headers.get('X-Isaac-Token',''),app.token):
                    self.reply(403,{'error':'LOCAL_APPLICATION_OWNER_REQUIRED'});return
                try:
                    length=int(self.headers.get('Content-Length',0))
                    if not 0<length<=4096:raise AdmissionError('BOUNDED_ACTION_REQUIRED')
                    body=json.loads(self.rfile.read(length))
                    if body=={'action':'stop'}:
                        app.stop_event.set();self.reply(202,{'stopping':True})
                    elif body=={'action':'launch_game'}:
                        self.reply(200,app.launch_game())
                    else:self.reply(400,{'error':'FIXED_APPLICATION_ACTION_REQUIRED'})
                except Exception:self.reply(409,{'error':'APPLICATION_ACTION_REJECTED'})
            def log_message(self,*_):pass
        return ThreadingHTTPServer(('127.0.0.1',9541),Handler)

    def run(self,components):
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.start(components)
        while not self.stop_event.wait(1):
            for name,(process,record) in self.children.items():
                if name=='isaac-game':continue
                if process.poll() is not None:
                    self.error='OWNED_COMPONENT_EXITED_'+name.upper();self.audit.append('owned_component_failed',name=name)
                    self.stop_event.set();break
        self.stop()
        if self.error or self.cleanup_faults:raise AdmissionError(self.error or 'STACK_COMPONENT_CLEANUP_FAILED')

    def close(self):
        self.server.shutdown();self.server.server_close()
        for handle in self.handles:handle.close()
        self.owner.close()


def run_owned(root,components='all'):
    app=Application(Path(root).resolve())
    signal.signal(signal.SIGINT,lambda *_:app.stop_event.set());signal.signal(signal.SIGTERM,lambda *_:app.stop_event.set())
    try:app.run(components)
    except Exception as error:
        app.error=str(error) if isinstance(error,AdmissionError) else 'APPLICATION_FAILED'
        app.audit.append('application_failed',code=app.error)
        while True:
            try:app.stop();break
            except Exception:
                app.stage='stop_requires_native_pause_or_component_cleanup';app.persist()
                time.sleep(2)
        raise
    finally:app.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--components',choices=['all','game'],default='all');args=parser.parse_args()
    run_owned(args.root,args.components)


if __name__=='__main__':main()
