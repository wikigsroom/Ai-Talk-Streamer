"""Single native game/controller owner and guarded loopback operator surface."""
from __future__ import annotations

import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import signal
import threading
import time
import urllib.request

from .common import AdmissionError, Audit, FileLease, inside, native_only, read_json, write_json
from .events import GameEvents
from .game_policy import FairPolicy, RunGoal, attach_upstream, strategy_class
from .native_game import NativeGame
from .strategy_dsh import bridge_token
from .wiki import WikiService


def controller_class(root, service, facts):
    attach_upstream(root)
    from isaac_jev.runtime import Controller
    from isaac_jev.providers import DecisionProviderConfig, ProviderSettings

    class FairController(Controller):
        def __init__(self, **kwargs):
            kwargs['provider_config_path']=str(inside(root,'state/isaac-strategy/realtime-provider.json'))
            super().__init__(**kwargs)
            # The real-time policy is native local code. Neither fallback nor
            # shadow inference may send frames to an inherited cloud provider.
            self._provider_config=DecisionProviderConfig(providers={'local':ProviderSettings(model='native-policy')})
            self._pending_provider_config=self._provider_config
            self._active_provider_name='local'
            self._active_provider_model='native-policy'
            self.strategy_service=service
            self.fair=FairPolicy(RunGoal(read_json(inside(root,'configs/issac/runtime.json'))['game']['run_goal']))
            self.event_cursor=0

        def update_provider_config(self, raw):
            raise AdmissionError('REALTIME_PROVIDER_IS_FIXED_LOCAL_CODE')

        def check_provider(self, name):
            if name!='local':
                raise AdmissionError('CLOUD_AND_SHADOW_PROVIDERS_DISABLED')
            return {'provider':'local','ready':True,'implementation':'native-policy'}

        def receive_state(self, message):
            filtered=self.fair.filter(message)
            response=super().receive_state(filtered)
            with service.lock:
                snapshot=deepcopy(service.snapshot)
                batch=service.read_events(self.event_cursor)
                self.event_cursor=batch['cursor']
            facts.ingest(snapshot,batch['events'])
            return response

        def receive_game_event(self, message):
            # Require the current bridge incarnation and restart as well as
            # seed. A terminal callback from a prior run is not current proof.
            with service.lock:
                current=deepcopy(service.snapshot)
            identity=current.get('identity') or {}
            if (message.get('callback')!='MC_POST_GAME_END'
                    or type(message.get('is_game_over')) is not bool
                    or message.get('start_seed')!=identity.get('seed')
                    or message.get('bridge_generation')!=identity.get('bridge')
                    or message.get('restart_count')!=identity.get('restart')):
                return
            super().receive_game_event(message)
            facts.emit(current,'run_ended',{'result':'death' if message['is_game_over'] else 'ending',
                       'ending_id':message.get('ending_id'),'callback':'MC_POST_GAME_END'},
                       priority=1,ttl=20,proof=message)
            service.configure(enabled=False,live=False)
            self.set_autopilot(False)

    return FairController


class StrategyHost:
    def __init__(self, root):
        native_only()
        self.root=Path(root).resolve()
        self.config=read_json(inside(root,'configs/issac/runtime.json'))
        self.owner=FileLease(inside(root,'state/isaac-strategy/host.lock')).acquire()
        attach_upstream(root)
        from isaac_jev.runtime import BridgeRuntime
        from isaac_jev.strategy_server import StrategyServer
        self.audit=Audit(inside(root,'state/isaac-strategy/operator-events.jsonl'))
        self.facts=GameEvents(root)
        self.service=strategy_class(root)(inside(root,'state/isaac-strategy/logs'),
                        decision_seconds=self.config['game']['decision_deadline_seconds'])
        self.service.core_actor_required=self.config['game'].get('strategic_owner')=='naimei_core_dsh'
        self.native=NativeGame(root)
        from .native_audio import ScopedAudioEnvelope
        self.audio=ScopedAudioEnvelope(root,self.native)
        self.wiki=WikiService(root,inside(root,self.config['native_paths']['game_python']),self.service.wiki_context)
        self.wiki.prepare()
        self.runtime=BridgeRuntime(port=self.config['game']['bridge_port'],autopilot=False,
                        log_dir=str(inside(root,'state/isaac-strategy/logs')),
                        controller_class=controller_class(root,self.service,self.facts))
        self.runtime.controller.decision_hz=self.config['game']['decision_hz']
        self.token=bridge_token(root)
        self.api=StrategyServer(self.service,self.token,self.config['game']['strategy_api_port'],
                                wiki=self.wiki,control=self.control)
        self.stop_event=threading.Event()
        self.action_lock=threading.RLock()
        self.armed=False
        self.last_fault=None
        self.last_core_check=0
        self.control_revision=0
        self.server=self.make_server()

    def control(self, body):
        if set(body)-{'enabled','live'}:
            raise AdmissionError('FIXED_CONTROL_FIELDS_REQUIRED')
        with self.action_lock:
            self.control_revision+=1
            enabled=body['enabled']
            live=body.get('live',False)
            if enabled and live:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open('http://127.0.0.1:3104/api/dsh/issac/core/status',timeout=3) as response:
                    core=json.load(response)
                if (core.get('ready') is not True or core.get('actor_id')!='naimei'
                    or core.get('strategic_owner')!='naimei_core_dsh'
                    or core.get('model')!='gpt-6-luna' or core.get('protocol')!='responses'
                    or core.get('candidate_id')!=read_json(inside(self.root,'.setup/candidate.json')).get('id')):
                    raise AdmissionError('CURRENT_ORIGINAL_NAIMEI_CORE_CHANNEL_REQUIRED')
                self.native.protection.admit_current(self.native.process,self.native.progress())
                if not self.service.fresh():
                    raise AdmissionError('FRESH_NATIVE_STATE_REQUIRED')
                self.strategy_automatic(True)
                self.service.configure(enabled=True,live=True)
                self.runtime.controller.set_autopilot(True)
                try:
                    receipt=self.native.resume()
                except Exception:
                    self.strategy_automatic(False,required=False)
                    self.service.configure(enabled=False,live=False)
                    self.runtime.controller.set_autopilot(False)
                    raise
                self.armed=True
                self.last_fault=None
                self.audit.append('autopilot_resumed',receipt=receipt)
            else:
                self.strategy_automatic(False,required=False)
                self.runtime.controller.set_autopilot(False)
                self.service.configure(enabled=False,live=False)
                self.armed=False
                receipt=self.native.pause() if self.native.session else {'not_attached':True}
                if enabled:
                    self.service.configure(enabled=True,live=False)
                self.audit.append('autopilot_paused',receipt=receipt)
            return {'armed':self.armed,'strategy':self.service.status(),'native_receipt':receipt,'control_revision':self.control_revision}

    def strategy_automatic(self,enabled,required=True):
        try:
            request=urllib.request.Request('http://127.0.0.1:3104/api/dsh/issac/core/control',
                data=json.dumps({'automatic':enabled}).encode(),
                headers={'Content-Type':'application/json','X-Isaac-Token':self.token})
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request,timeout=2) as response:value=json.load(response)
            if value.get('automatic') is not enabled or value.get('strategic_owner')!='naimei_core_dsh':raise AdmissionError('NAIMEI_CORE_CONTROL_NOT_ACKNOWLEDGED')
        except Exception:
            if required:raise AdmissionError('NAIMEI_CORE_NOT_READY') from None

    def status(self):
        return {'service':'issac-native-game','armed':self.armed,'pid':os.getpid(),
                'strategy':self.service.status(),'native_attached':self.native.session is not None,
                'control_revision':self.control_revision,
                'game_audio':self.audio.status(),
                'last_fault':self.last_fault,'only_ordinary_inputs':True,'save_slot':3}

    def action(self, body):
        with self.action_lock:
            if 'expected_revision' in body:
                if type(body['expected_revision']) is not int or body['expected_revision']!=self.control_revision:
                    raise AdmissionError('OPERATOR_CONTROL_REVISION_CHANGED')
                body={k:v for k,v in body.items() if k!='expected_revision'}
            action=body.get('action')
            if action=='attach' and set(body)=={'action','pid'} and type(body['pid']) is int:
                return self.native.attach(body['pid'])
            if action=='menu' and set(body)=={'action','key'}:
                if self.armed:
                    raise AdmissionError('PAUSE_AUTOPILOT_BEFORE_MENU_INPUT')
                return self.native.menu_key(body['key'])
            if action=='install' and set(body)=={'action'}:
                if self.armed:
                    raise AdmissionError('PAUSE_BEFORE_CONTROLLER_INSTALL')
                return self.native.install_controller(RunGoal(self.config['game']['run_goal']))
            if action=='modules' and set(body)=={'action'}:
                if self.armed:raise AdmissionError('PAUSE_BEFORE_MODULE_ADMISSION')
                self.native.bootstrap_modules()
                return {'modules_ready':True,'autopilot':False}
            if action in {'resume','pause','observe'} and set(body)=={'action'}:
                if action=='observe':
                    return {'observation':self.native.observe(),'progress':self.native.progress()}
                return self.control({'enabled':action=='resume','live':action=='resume'})
            raise AdmissionError('FIXED_NATIVE_ACTION_REQUIRED')

    def make_server(self):
        host=self
        class Handler(BaseHTTPRequestHandler):
            def send(self, code, body):
                data=json.dumps(body,ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                from urllib.parse import urlsplit,parse_qs
                url=urlsplit(self.path)
                try:
                    if url.path=='/frame.jpg':
                        data=host.native.capture_jpeg();self.send_response(200)
                        self.send_header('Content-Type','image/jpeg');self.send_header('Cache-Control','no-store')
                        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
                    elif url.path=='/status':
                        result=host.status()
                    elif url.path=='/events':
                        result=host.facts.read(int(parse_qs(url.query).get('after',['0'])[0]))
                    else:
                        self.send(404,{'error':'not_found'});return
                    self.send(200,result)
                except (ValueError,KeyError,TypeError):
                    self.send(400,{'error':'INVALID_READ_REQUEST'})

            def do_POST(self):
                if self.headers.get('Origin') or not hmac.compare_digest(self.headers.get('X-Isaac-Token',''),host.token):
                    self.send(403,{'error':'LOCAL_OPERATOR_REQUIRED'});return
                try:
                    n=int(self.headers.get('Content-Length',0))
                    if not 0<n<=8192:
                        raise AdmissionError('BOUNDED_BODY_REQUIRED')
                    body=json.loads(self.rfile.read(n))
                    if not isinstance(body,dict):
                        raise AdmissionError('JSON_OBJECT_REQUIRED')
                    if self.path=='/control':
                        result=host.action(body)
                    elif self.path=='/game-audio':
                        result=host.audio.update(body)
                    elif self.path=='/narration/reserve' and not body:
                        result=host.facts.reserve() or {'pending':False}
                    elif self.path=='/narration/accepted' and set(body)=={'nonce','request_id'}:
                        host.facts.accepted(body['nonce'],body['request_id']);result={'accepted':True}
                    elif self.path=='/narration/abandon' and set(body)=={'nonce'}:
                        host.facts.abandon(body['nonce']);result={'cancelled':True}
                    elif self.path=='/narration/receipt' and set(body)=={'request_id','receipt'}:
                        host.facts.playback_receipt(body['request_id'],body['receipt']);result={'recorded':True}
                    else:
                        self.send(404,{'error':'not_found'});return
                    self.send(200,result)
                except AdmissionError as error:
                    self.send(409,{'error':str(error)})
                except Exception:
                    host.audit.append('native_action_failed',code='NATIVE_ACTION_REJECTED')
                    self.send(409,{'error':'NATIVE_ACTION_REJECTED'})

            def log_message(self,*_):
                pass
        return ThreadingHTTPServer(('127.0.0.1',self.config['game']['native_control_port']),Handler)

    def watchdog(self):
        while not self.stop_event.wait(.25):
            if self.armed and time.monotonic()-self.last_core_check>=1:
                self.last_core_check=time.monotonic()
                try:
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open('http://127.0.0.1:3104/api/dsh/issac/core/status',timeout=.75) as response:
                        core=json.load(response)
                    healthy=core.get('ready') is True and core.get('automatic') is True and core.get('actor_id')=='naimei'
                except Exception:healthy=False
                if not healthy:
                    self.last_fault='NAIMEI_CORE_UNAVAILABLE'
                    try:self.control({'enabled':False,'live':False})
                    except Exception:self.last_fault='NAIMEI_CORE_LOSS_PAUSE_ACK_PENDING'
            if self.armed and not self.runtime.controller.autopilot_enabled:
                try:self.control({'enabled':False,'live':False})
                except Exception:self.last_fault='TERMINAL_PAUSE_ACK_PENDING'
            if self.armed and not self.service.fresh():
                with self.action_lock:
                    self.last_fault='GAME_BRIDGE_STALE'
                    self.runtime.controller.set_autopilot(False)
                    self.service.configure(enabled=False,live=False)
                    self.armed=False
                    try:
                        receipt=self.native.pause()
                    except Exception:
                        receipt={'normal_pause_confirmed':False,'native_controller_lease_still_required':True}
                    self.audit.append('bridge_loss_stop',receipt=receipt)
            if self.armed:
                try:
                    self.native.protection.admit_current(self.native.process,self.native.progress())
                except Exception:
                    try:
                        self.control({'enabled':False,'live':False})
                    except Exception:
                        pass
                    self.last_fault='SLOT_OR_NATIVE_IDENTITY_CHANGED'

    def run(self):
        from .shutdown import watch
        watch(self.root,self.stop_event.set)
        self.runtime.start()
        self.api.start()
        threading.Thread(target=self.watchdog,daemon=True).start()
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.audit.append('ready',pid=os.getpid(),wiki=self.wiki.snapshot_hash)
        self.stop_event.wait()

    def close(self):
        self.control({'enabled':False,'live':False})
        self.audio.close()
        self.native.close()
        self.stop_event.set()
        self.server.shutdown()
        self.server.server_close()
        self.api.close()
        self.runtime.stop()
        self.service.close()
        self.facts.close()
        self.owner.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    from .deployment import require_candidate
    require_candidate(args.root)
    host=StrategyHost(args.root)
    signal.signal(signal.SIGINT,lambda *_:host.stop_event.set())
    signal.signal(signal.SIGTERM,lambda *_:host.stop_event.set())
    try:
        host.run()
    finally:
        while True:
            try:host.close();break
            except Exception:
                host.last_fault='CLEANUP_UNCONFIRMED_OWNER_RETAINED'
                host.audit.append('cleanup_pending',code=host.last_fault)
                time.sleep(2)


if __name__=='__main__':
    main()
