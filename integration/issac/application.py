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
        identity=psutil.Process(process.pid)
        record={'name':name,'pid':process.pid,'created_at':identity.create_time(),'executable':identity.exe(),
                'executable_sha256':file_hash(executable),'args':args,'installation_id':self.id,'candidate_id':self.candidate['candidate_id'],
                'stop_file':str(stop)}
        self.children[name]=(process,record)
        self.persist()
        self.audit.append('owned_component_started',name=name,pid=process.pid,created_at=record['created_at'])

    def persist(self):
        import psutil
        write_json(inside(self.root,'state/issac-stream/application.json'),{'installation_id':self.id,'candidate_id':self.candidate['candidate_id'],
            'pid':os.getpid(),'created_at':psutil.Process().create_time(),'stage':self.stage,
            'processes':[record for _,record in self.children.values()],'public_broadcast_allowed':False})

    def wait_ready(self,name,url,timeout=180):
        deadline=time.monotonic()+timeout
        while not self.stop_event.wait(.5):
            process,_=self.children[name]
            if process.poll() is not None:
                raise AdmissionError('OWNED_COMPONENT_EXITED_'+name.upper())
            try:
                value=self.http(url)
                if value.get('ready') or value.get('dsh_ready') or value.get('service')=='issac-native-game':return value
            except Exception:pass
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
        self.child('game-controller',game_py,['-X','utf8','-B','-m','integration.issac.strategy_host',*root_arg],'game')
        self.wait_ready('game-controller','http://127.0.0.1:9534/status',60)
        from .strategy_dsh import prepare as prepare_dsh
        command,env,dsh_cwd=prepare_dsh(self.root)
        self.child('strategy-dsh',str(Path(command[0]).relative_to(self.root)),command[1:],'game',
                   cwd=str(dsh_cwd.relative_to(self.root)),environment=env)
        if components=='all':
            self.child('voice',voice_py,['-X','utf8','-B','-m','integration.issac.voice',*root_arg],'voice')
            self.child('flashhead',media_py,['-X','utf8','-B','-m','integration.issac.engine_service',*root_arg],'engine')
            self.child('studio',media_py,['-X','utf8','-B','-m','integration.issac.studio',*root_arg],'studio')
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
            if process.poll() is not None:continue
            current=psutil.Process(record['pid'])
            if current.create_time()!=record['created_at'] or Path(current.exe()).resolve()!=Path(record['executable']).resolve():
                raise AdmissionError('OWNED_PROCESS_IDENTITY_CHANGED_DURING_STOP')
            Path(record['stop_file']).write_text(self.id,encoding='ascii')
            try:current.wait(45)
            except psutil.TimeoutExpired:
                self.stage='component_cleanup_not_confirmed';self.persist()
                raise AdmissionError('OWNED_COMPONENT_GRACEFUL_STOP_NOT_CONFIRMED_'+name.upper()) from None
            self.audit.append('owned_component_stopped',name=name,pid=record['pid'],method='owned_stop_request_normal_cleanup')
        self.stage='stopped_game_preserved_paused'
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
