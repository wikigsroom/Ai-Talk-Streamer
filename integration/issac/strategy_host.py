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
from .core_model import current_core_channel_matches
from .game_policy import FairPolicy, RunGoal, attach_upstream, strategy_class
from .native_game import NativeGame
from .strategy_dsh import bridge_token
from .wiki import WikiService
from .live_cycle import LiveCycle
from .continuity import uninterrupted


def controller_class(root, service, facts):
    attach_upstream(root)
    from isaac_jev.runtime import Controller
    from isaac_jev.providers import DecisionProviderConfig, ProviderSettings
    from isaac_jev.observation_cache import observation_scope

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
            self.packet_processing={'stage':'idle'}
            self.last_packet_timing=None
            self.terminal_receipt=None

        def update_provider_config(self, raw):
            raise AdmissionError('REALTIME_PROVIDER_IS_FIXED_LOCAL_CODE')

        def check_provider(self, name):
            if name!='local':
                raise AdmissionError('CLOUD_AND_SHADOW_PROVIDERS_DISABLED')
            return {'provider':'local','ready':True,'implementation':'native-policy'}

        def receive_state(self, message):
            started=time.monotonic();mark=started;timing={}
            self.packet_processing={'stage':'filter','frame':message.get('frame'),'started_monotonic':started}
            try:
                with observation_scope():
                    filtered=self.fair.filter(message)
                    timing['filter_ms']=(time.monotonic()-mark)*1000;mark=time.monotonic()
                    self.packet_processing={**self.packet_processing,'stage':'rules_and_strategy'}
                    response=super().receive_state(filtered)
                    timing['rules_and_strategy_ms']=(time.monotonic()-mark)*1000;mark=time.monotonic()
                    self.packet_processing={**self.packet_processing,'stage':'facts'}
                    with service.lock:
                        snapshot=deepcopy(service.snapshot)
                        batch=service.read_events(self.event_cursor)
                        self.event_cursor=batch['cursor']
                    facts.ingest(snapshot,batch['events'])
                    timing['facts_ms']=(time.monotonic()-mark)*1000
                    return response
            finally:
                timing['total_ms']=(time.monotonic()-started)*1000
                self.last_packet_timing={'frame':message.get('frame'),**timing}
                self.packet_processing={'stage':'idle'}

        def packet_status(self):
            current=dict(self.packet_processing)
            if 'started_monotonic' in current:
                current['elapsed_ms']=(time.monotonic()-current.pop('started_monotonic'))*1000
            return {'current':current,'last':self.last_packet_timing}

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
            self.terminal_receipt=deepcopy(message)
            service.configure(enabled=False,live=False)
            self.set_autopilot(False)

    return FairController


class StrategyHost:
    def __init__(self, root):
        native_only()
        self.root=Path(root).resolve()
        self.uninterrupted_gameplay=uninterrupted(root)
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
        self.service.wiki_verifier=self.wiki.verify
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
        self.pause_pending=False
        self.lifecycle=LiveCycle(self)
        self.server=self.make_server()

    def core_status(self):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:3104/api/dsh/issac/core/status',timeout=.75) as response:
            return json.load(response)

    def approved_core(self, core):
        return (core.get('actor_id')=='naimei' and core.get('strategic_owner')=='naimei_core_dsh'
                and current_core_channel_matches(self.root,core)
                and core.get('candidate_id')==read_json(inside(self.root,'.setup/candidate.json')).get('id'))

    def live_media_ready(self):
        """Ready models and the actual single audible player, not process liveness."""
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for url in ('http://127.0.0.1:9893/health','http://127.0.0.1:8040/health',
                        'http://127.0.0.1:8062/health'):
                with opener.open(url,timeout=.75) as response:value=json.load(response)
                if value.get('ready') is not True:return False
            with opener.open('http://127.0.0.1:3104/api/dsh/platforms',timeout=.75) as response:value=json.load(response)
            player=value.get('output_player') or {}
            return player.get('connected') is True and player.get('audio_state')=='running'
        except Exception:
            return False

    def watchdog_stop(self, reason):
        """Suspend immediately; only this live owner's exact pause can recover."""
        self.last_fault=reason
        lifecycle=getattr(self,'lifecycle',None)
        if getattr(self,'uninterrupted_gameplay',False):
            if lifecycle:lifecycle.attention(reason)
            self.audit.append('game_preserved_during_service_fault',reason=reason,game_pause_requested=False)
            return {'armed':self.armed,'game_pause_requested':False,'component_repair_requested':True}
        receipt=None
        try:
            if lifecycle:
                result=self.control({'enabled':False,'live':False},origin='lifecycle')
                receipt=result.get('native_receipt')
            else:
                self.control({'enabled':False,'live':False})
        except Exception:
            self.last_fault=reason+'_PAUSE_ACK_PENDING'
            self.pause_pending=True
        if lifecycle:lifecycle.fault(reason,receipt)
        return {'armed':self.armed,'native_receipt':receipt or {},'pause_confirmation_pending':self.pause_pending}

    def control(self, body, *, origin='operator'):
        if set(body)-{'enabled','live'}:
            raise AdmissionError('FIXED_CONTROL_FIELDS_REQUIRED')
        with self.action_lock:
            lifecycle=getattr(self,'lifecycle',None)
            # Cancel intent before reverse HTTP/native operations can block.
            if lifecycle and origin=='operator':lifecycle.stop()
            self.control_revision+=1
            enabled=body['enabled']
            live=body.get('live',False)
            if not enabled and origin!='operator' and getattr(self,'uninterrupted_gameplay',False):
                raise AdmissionError('AUTOMATIC_GAME_INTERRUPTION_FORBIDDEN')
            if enabled and live:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open('http://127.0.0.1:3104/api/dsh/issac/core/status',timeout=3) as response:
                    core=json.load(response)
                if (core.get('ready') is not True or core.get('actor_id')!='naimei'
                    or core.get('strategic_owner')!='naimei_core_dsh'
                    or not current_core_channel_matches(self.root,core)
                    or core.get('candidate_id')!=read_json(inside(self.root,'.setup/candidate.json')).get('id')):
                    raise AdmissionError('CURRENT_APPROVED_NAIMEI_CORE_CHANNEL_REQUIRED')
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
                self.pause_pending=False
                self.last_fault=None
                self.audit.append('autopilot_resumed',receipt=receipt)
                if lifecycle and origin=='operator':lifecycle.start()
            else:
                # Withdraw local authority before any reverse HTTP request or
                # native observation can wait. Keep failed pause confirmation
                # pending; a transition's IsPaused is not a normal pause menu.
                self.runtime.controller.set_autopilot(False)
                self.service.configure(enabled=False,live=False)
                self.armed=False
                self.pause_pending=bool(self.native.session)
                self.audit.append('local_authority_withdrawn',control_revision=self.control_revision)
                try:
                    receipt=(self.native.pause(origin='operator') if getattr(self,'uninterrupted_gameplay',False)
                             else self.native.pause()) if self.native.session else {'not_attached':True}
                    self.pause_pending=False
                finally:
                    self.strategy_automatic(False,required=False)
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
                'pause_confirmation_pending':self.pause_pending,
                'manual_override':self.service.raw.get('strategy',{}).get('manual_override',False),
                'native_engine_hold_grace':self.service.native_engine_hold_grace(),
                'game_audio':self.audio.status(),
                'packet_processing':getattr(self.runtime.controller,'packet_status',lambda:None)(),
                'live_cycle':self.lifecycle.status(),
                'last_fault':self.last_fault,'only_ordinary_inputs':True,'save_slot':3}

    def action(self, body):
        with self.action_lock:
            revision_checked='expected_revision' in body
            if 'expected_revision' in body:
                if type(body['expected_revision']) is not int or body['expected_revision']!=self.control_revision:
                    raise AdmissionError('OPERATOR_CONTROL_REVISION_CHANGED')
                body={k:v for k,v in body.items() if k!='expected_revision'}
            action=body.get('action')
            if getattr(self,'uninterrupted_gameplay',False) and action in {'pause','natural_pause','natural_resume','recovery_pause'}:
                raise AdmissionError('AUTOMATIC_GAME_INTERRUPTION_FORBIDDEN')
            if getattr(self,'uninterrupted_gameplay',False) and body=={'action':'components_ready'}:
                if not self.service.fresh() or not self.approved_core(self.core_status()) or not self.live_media_ready():
                    raise AdmissionError('ACTUAL_COMPONENT_RECOVERY_REQUIRED')
                self.last_fault=None;self.lifecycle.alert=None
                return {'game_control_changed':False,'components_ready':True}
            if (getattr(self,'uninterrupted_gameplay',False) and action=='adopt_live'
                    and set(body)=={'action','pid'} and type(body['pid']) is int):
                if self.service.raw.get('strategy',{}).get('manual_override'):
                    raise AdmissionError('EXPLICIT_OPERATOR_CONTROL_PRESERVED')
                self.native.attach(body['pid'])
                self.native.configure_continuity_options()
                manual=self.native.rpc('evaluate','local m=_G.__NativeIsaacController;return tostring(m and m.strategyControl and m.strategyControl.manualOverride==true)')
                if str(manual).lower()=='true':raise AdmissionError('EXPLICIT_OPERATOR_CONTROL_PRESERVED')
                state=self.native.observe()
                if state['paused'] or state['players']!=1:
                    raise AdmissionError('LIVING_UNPAUSED_GAME_REQUIRED')
                self.native.install_controller(allow_terminal=True) if state['dead'] else self.native.install_controller()
                if state['dead']:
                    self.lifecycle.stop('adopt_real_terminal')
                    self.lifecycle.alert=None
                    self.lifecycle.hold_terminal({},observed_dead=True)
                    return {'armed':False,'live_cycle':self.lifecycle.status(),'game_control_changed':False}
                deadline=time.monotonic()+5
                while not self.service.fresh() and time.monotonic()<deadline:time.sleep(.05)
                result=self.control({'enabled':True,'live':True},origin='lifecycle')
                self.lifecycle.start()
                return result
            if action=='media_fault' and set(body)=={'action'}:
                if (self.lifecycle.phase=='operator_paused'
                    or self.service.raw.get('strategy',{}).get('manual_override')):
                    return {'armed':self.armed,'operator_pause_preserved':True}
                result=self.watchdog_stop('LIVE_MEDIA_UNAVAILABLE')
                # A failed frame pipeline cannot become ready inside the same
                # studio process. Request independent replacement immediately.
                self.lifecycle.attention('LIVE_MEDIA_UNAVAILABLE')
                return result
            if action in {'natural_pause','natural_resume'} and set(body)=={'action'}:
                if (not revision_checked or self.service.raw.get('strategy',{}).get('manual_override')
                    or (action=='natural_pause' and (not self.armed or not self.lifecycle.enabled or self.lifecycle.phase!='playing'))
                    or (action=='natural_resume' and (self.armed or self.lifecycle.enabled or self.lifecycle.phase!='natural_paused'))):
                    raise AdmissionError('CURRENT_NATURAL_PAUSE_OWNERSHIP_REQUIRED')
                enabled=action=='natural_resume'
                result=self.control({'enabled':enabled,'live':enabled},origin='lifecycle')
                if enabled:self.lifecycle.start()
                else:
                    self.lifecycle.enabled=False
                    self.lifecycle.change('natural_paused','studio_drink')
                return result
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
            if action in {'recovery_pause','recovery_live'} and set(body)=={'action'}:
                if (self.armed or self.lifecycle.enabled or self.lifecycle.phase!='observation_only'
                    or self.service.raw.get('strategy',{}).get('manual_override')):
                    raise AdmissionError('FRESH_OBSERVATION_ONLY_RECOVERY_REQUIRED')
                enabled=action=='recovery_live'
                result=self.control({'enabled':enabled,'live':enabled},origin='lifecycle')
                if enabled:self.lifecycle.start()
                return result
            if action in {'resume','pause','observe'} and set(body)=={'action'}:
                if action=='observe':
                    return {'observation':self.native.observe(),'progress':self.native.progress()}
                return self.control({'enabled':action=='resume','live':action=='resume'})
            if action=='live' and set(body)=={'action'}:
                # Explicitly adopt the real dead run left by an older process.
                # A service restart alone never enables this session.
                state=self.native.observe()
                if state['dead']:
                    self.control_revision+=1
                    self.native.protection.admit_current(self.native.process,self.native.progress())
                    self.native.install_controller(allow_terminal=True)
                    self.lifecycle.stop('explicit_live_start')
                    self.lifecycle.alert=None
                    self.lifecycle.hold_terminal({},observed_dead=True)
                    return {'armed':False,'live_cycle':self.lifecycle.status()}
                return self.control({'enabled':True,'live':True})
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
                    elif url.path=='/performance':
                        result=host.native.performance() if host.native.session else {'attached':False}
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

    def refresh_quiet_observation(self):
        # The engine can keep presenting while suspending update/render Mod
        # callbacks (notably around a boss clear). Ask the pinned native owner
        # for its normal full observation before the existing stale deadline.
        # Only a real packet through receive_state may change freshness. A
        # successful RPC or a live process never substitutes for that packet.
        if not self.armed:return
        received=getattr(self.service,'received',None)
        if type(received) not in (int,float) or not received:return
        age=self.service.clock()-received
        now=time.monotonic()
        if not .75<=age<1.25 or now-getattr(self,'last_observation_pulse',0)<.4:return
        self.last_observation_pulse=now
        try:self.native.refresh_observation()
        except Exception as error:
            self.audit.append('native_observation_pulse_failed',exception_type=type(error).__name__)

    def watchdog(self):
        while not self.stop_event.wait(.25):
            lifecycle=getattr(self,'lifecycle',None)
            if self.pause_pending and not self.armed and not getattr(self,'uninterrupted_gameplay',False):
                try:
                    with self.action_lock:
                        # A guarded explicit resume may have acquired this lock
                        # first and withdrawn the pending request. Recheck here
                        # so an old waiter cannot pause the newly resumed run.
                        if self.pause_pending and not self.armed:
                            receipt=self.native.pause()
                            self.pause_pending=False
                            if lifecycle and lifecycle.phase=='recovering':lifecycle.recovery_receipt=receipt
                            self.audit.append('pending_normal_pause_confirmed',receipt=receipt)
                except Exception:
                    with self.action_lock:
                        if self.pause_pending and not self.armed:self.last_fault='NORMAL_PAUSE_ACK_PENDING'
            if lifecycle:
                with self.action_lock:
                    if lifecycle.tick():continue
            if self.armed and time.monotonic()-self.last_core_check>=1:
                observed_revision=self.control_revision
                self.last_core_check=time.monotonic()
                core_check_started=time.monotonic();core={};core_error=None
                try:
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open('http://127.0.0.1:3104/api/dsh/issac/core/status',timeout=.75) as response:
                        core=json.load(response)
                    healthy=core.get('ready') is True and core.get('automatic') is True and core.get('actor_id')=='naimei'
                except Exception as error:
                    healthy=False;core_error=type(error).__name__
                if not healthy:
                    with self.action_lock:
                        # A health response can describe the explicit pause
                        # that completed while this check was in flight.
                        if self.armed and self.control_revision==observed_revision:
                            self.audit.append('core_loss_stop',control_revision=observed_revision,
                                elapsed_ms=(time.monotonic()-core_check_started)*1000,
                                check_error=core_error,
                                core={key:core.get(key) for key in ('ready','automatic','actor_id','failures','last_error')})
                            self.watchdog_stop('NAIMEI_CORE_UNAVAILABLE')
            observed_revision=self.control_revision
            if self.armed and not self.runtime.controller.autopilot_enabled:
                with self.action_lock:
                    # set_autopilot(False) precedes armed=False in an explicit
                    # pause. Never turn that transient observation into a
                    # second pause/revision after the owner has finished.
                    if (self.armed and self.control_revision==observed_revision
                            and not self.runtime.controller.autopilot_enabled):
                        if getattr(self,'uninterrupted_gameplay',False):
                            self.watchdog_stop('LOCAL_CONTROLLER_REPAIR_REQUIRED')
                        else:
                            try:self.control({'enabled':False,'live':False})
                            except Exception:self.last_fault='TERMINAL_PAUSE_ACK_PENDING'
            self.refresh_quiet_observation()
            if (self.armed and not self.service.fresh()
                    and not self.service.native_engine_hold_grace()):
                with self.action_lock:
                    # The packet or an explicit control may complete while
                    # this waiter is acquiring the control lock.
                    if (not self.armed or self.service.fresh()
                            or self.service.native_engine_hold_grace()):continue
                    packet=getattr(self.runtime.controller,'packet_status',lambda:None)()
                    stale_age_ms=(self.service.clock()-self.service.received)*1000
                    self.last_fault='GAME_BRIDGE_STALE'
                    if getattr(self,'uninterrupted_gameplay',False):
                        self.watchdog_stop('GAME_BRIDGE_STALE')
                        continue
                    self.runtime.controller.set_autopilot(False)
                    self.service.configure(enabled=False,live=False)
                    self.armed=False
                    self.pause_pending=True
                    try:
                        receipt=self.native.pause()
                        self.pause_pending=False
                    except Exception:
                        receipt={'normal_pause_confirmed':False,'native_controller_lease_still_required':True}
                    finally:self.strategy_automatic(False,required=False)
                    if lifecycle:lifecycle.fault('GAME_BRIDGE_STALE',receipt)
                    self.audit.append('bridge_loss_stop',receipt=receipt,packet_processing=packet,
                        observation_age_ms=stale_age_ms,
                        last_observation_pulse=getattr(self,'last_observation_pulse',None))
            if self.armed:
                observed_revision=self.control_revision
                try:
                    self.native.protection.admit_current(self.native.process,self.native.progress())
                except Exception:
                    with self.action_lock:
                        if self.armed and self.control_revision==observed_revision:
                            if getattr(self,'uninterrupted_gameplay',False):
                                self.runtime.controller.set_autopilot(False)
                                self.armed=False
                            else:
                                try:self.control({'enabled':False,'live':False})
                                except Exception:pass
                            self.last_fault='SLOT_OR_NATIVE_IDENTITY_CHANGED'
                            if lifecycle:lifecycle.attention(self.last_fault)

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
        if getattr(self,'uninterrupted_gameplay',False):
            self.runtime.controller.set_autopilot(False)
            self.armed=False
        else:self.control({'enabled':False,'live':False})
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
