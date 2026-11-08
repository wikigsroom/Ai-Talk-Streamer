"""MC rev04 programme with genuine NCM01/FlashHead and separate body motion."""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import uuid

import cv2
import numpy as np
from aiohttp import web,ClientSession,ClientTimeout,WSMsgType

from integration.naimei_studio import Studio as NaimeiStudio
from integration.naimei_media import packet,SILENCE
from integration.naimei_voice_contract import worker_matches
from .body import BodyBank
from .common import AdmissionError,Audit,inside,read_json,write_json
from .mouth import MouthProjector
from .media_protocol import MediaProfile,stream_request_error
from .stream_encoder import H264Encoder
from .media_clock import MediaTimer
from .readiness import verified_drink_pause
from .strategy_dsh import bridge_token


WEB_FILES=frozenset({'mc-programme.html','mc-programme.css','mc-programme.js','mc-programme-overlay.js',
    'mc-chat-position.js','issac-game-client.js','local-stream.js','dsh-playback.js','room-audio.js',
    'room-client.js','browser-id.js','director.html','director.css','director.js'})


def programme_revision(root):
    digest=hashlib.sha256()
    for name in sorted(WEB_FILES):
        if name.startswith('director'):continue
        data=inside(root,'web/issac/'+name).read_bytes()
        digest.update(name.encode()+b'\0'+hashlib.sha256(data).digest())
    digest.update(inside(root,'configs/issac/programme-layout.json').read_bytes())
    return digest.hexdigest()


class IsaacStudio(NaimeiStudio):
    def __init__(self, root):
        root=Path(root).resolve()
        runtime=read_json(inside(root,'configs/issac/runtime.json'))
        mode_path=inside(root,'state/issac-stream/current-mode.json')
        mode=read_json(mode_path)['mode'] if mode_path.is_file() else runtime['media']['default_mode']
        self.body=BodyBank(root,mode)
        super().__init__(root,config_path='configs/issac/studio.json',reference_image=f'assets/issac/references/{mode}.png')
        self.config['shared_installation_root']=str(root)
        self.mode=mode
        self.runtime=runtime
        self.encoder=H264Encoder(512,512,1500000)
        self.media=MediaProfile()
        self.keyframe=True
        self.web_revision=programme_revision(root)
        self.audit=Audit(inside(root,'state/issac-stream/studio-events.jsonl'))
        self.native_token=bridge_token(root)
        self.game_state={'connected':False,'freshness':'unavailable','mode':'PAUSED','screen':'unavailable'}
        self.last_body_event=None
        self.players={}
        self.frames={}
        self.last_telemetry=0
        self.mouth=MouthProjector(root,mode,self.body.reference)
        self.media_fault=False
        self.media_error=None
        self.changing_mode=False
        self.pending_mode=None
        self.pending_body=None
        self.pending_mouth=None
        self.game_event_tasks=set()
        self.stopping=False
        self.cleanup_started=False
        self.auto_drink=None
        self.command_lock=asyncio.Lock()
        self.command_tasks=set()
        self.media_timer=MediaTimer()
        self.last_auto_drink=time.monotonic()
        self.sample_mouth=None

    def load_actions(self):
        # BodyBank is the sole source of accepted decoded loops. Inherited
        # endpoint substitution and old outfit clips are deliberately bypassed.
        return None

    def blend_to_closed(self, source=None):
        self.transitions.clear()

    async def refresh_health(self):
        while True:
            for name,url in [('engine_health',self.config['engine_url']),('tts_health',self.config['tts_primary_url'])]:
                try:
                    async with self.http.get(url+'/health',timeout=ClientTimeout(total=2)) as response:
                        value=await response.json();setattr(self,name,value if response.status==200 else {'ready':False})
                except Exception:setattr(self,name,{'ready':False})
            if not self.media_fault:
                self.stage='changing_mode' if self.changing_mode else 'ready' if self.engine_health.get('ready') and self.voice_ready() else 'waiting_for_local_services'
            await asyncio.sleep(2)

    def voice_ready(self):
        return worker_matches(self.voice_profile,self.tts_health,'NCM01')

    async def game_monitor(self):
        while True:
            try:
                async with self.http.get('http://127.0.0.1:9532/query?topic=state',timeout=ClientTimeout(total=1)) as response:
                    value=await response.json()
                native=value.get('data') or {}
                room=native.get('room') or {}
                self.game_state={'connected':value.get('connected') is True,'freshness':'fresh' if value.get('connected') and value.get('age_ms',9999)<1500 else 'stale',
                    'mode':'AUTO' if self.game_state.get('armed') else 'PAUSED','screen':'gameplay' if native else 'unavailable',
                    'clear':bool(room.get('clear')),'paused':bool(room.get('paused')),'dead':bool(room.get('dead')),
                    'identity':value.get('identity'),'frame':native.get('frame'),'inventory_revision':native.get('inventory_revision')}
                async with self.http.get('http://127.0.0.1:9534/status',timeout=ClientTimeout(total=1)) as response:
                    status=await response.json()
                self.game_state['armed']=status.get('armed') is True
                self.game_state['mode']='AUTO' if self.game_state['armed'] else 'PAUSED'
            except Exception:
                self.game_state={'connected':False,'freshness':'unavailable','mode':'PAUSED','screen':'unavailable'}
            await asyncio.sleep(.4)

    async def speech(self, command):
        # Complete a cup action before admitting a speech generation.
        deadline=time.monotonic()+18
        while self.body.drinking:
            if time.monotonic()>deadline:
                await self.fail(command['request_id'],'DRINK_CHAIN_DID_NOT_COMPLETE');return
            await asyncio.sleep(.04)
        if self.changing_mode or self.media_fault:
            await self.fail(command['request_id'],'MEDIA_NOT_IDLE_READY');return
        if not self.fence.matches(command):return
        self.mouth.reset()
        await super().speech(command)

    async def dsh_command(self, request):
        # A delayed old cancel must not clear a newer speech mapping/engine.
        async with self.command_lock:
            return await super().dsh_command(request)

    async def discard_cancelled_frame(self, metadata, receipt):
        barrier=receipt.get('barrier') or {}
        if (receipt.get('persisted') is not False or receipt.get('cancelled') is not True
                or barrier.get('request_id')!=metadata['request_id']
                or barrier.get('runtime_epoch')!=metadata['runtime_epoch']
                or barrier.get('generation')!=metadata['generation']
                or not isinstance(barrier.get('barrier_id'),str)
                or type(barrier.get('new_generation')) is not int
                or barrier['new_generation']<=metadata['generation']):
            raise AdmissionError('MEDIA_CANCEL_RECEIPT_INVALID')
        # Another handler may already be draining an older generator while
        # holding the command lock. Its advanced fence is sufficient to drop
        # this frame immediately, without waiting on network cleanup.
        if self.fence.matches(metadata):
            async with self.command_lock:
                if self.fence.matches(metadata) and self.fence.cancel(barrier):
                    self.mapping=None
                    self.pending.clear()
                    await self.broadcast_control(barrier)
                    self.state='idle'
                    task=asyncio.create_task(self.retire_cancelled_source(metadata['request_id'],barrier))
                    self.command_tasks.add(task);task.add_done_callback(self.command_tasks.discard)
        self.stats['cancelled_frames_discarded']+=1
        self.audit.append('cancelled_frame_discarded',request_id=metadata['request_id'],barrier_id=barrier['barrier_id'])

    async def retire_cancelled_source(self,request_id,barrier):
        async with self.command_lock:
            if self.fence.current==(barrier['runtime_epoch'],barrier['new_generation']):
                await self.cancel_source(request_id)

    async def emit(self, jpeg, pcm=SILENCE, metadata=None):
        if metadata:
            if not self.fence.matches(metadata):return
            started=time.perf_counter()
            receipt=await self.api('/internal/media-map',metadata)
            elapsed=round((time.perf_counter()-started)*1e6)
            self.stats['media_map_max_us']=max(self.stats['media_map_max_us'],elapsed)
            if receipt.get('cancelled'):
                await self.discard_cancelled_frame(metadata,receipt)
                return
            if receipt.get('persisted') is not True:
                raise AdmissionError('MEDIA_MAP_NOT_PERSISTED')
            if not self.fence.matches(metadata):
                return
            metadata={'type':'media.map','protocol':2,**metadata,'map_revision':receipt['map_revision']}
        image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
        started=time.perf_counter()
        encoded,_=self.encoder.encode(image,self.sequence,keyframe=self.keyframe or self.sequence%50==0)
        elapsed=round((time.perf_counter()-started)*1e6)
        self.stats['encoder_max_us']=max(self.stats['encoder_max_us'],elapsed)
        self.keyframe=False
        avcc,init=self.media.packet(encoded,512,512)
        init={**init,'programme_revision':self.web_revision}
        body=packet(self.sequence,avcc,pcm)
        self.sequence+=1
        for ws,q in list(self.viewers.items()):
            try:
                q.put_nowait(({'init':init,'map':metadata},body))
            except asyncio.QueueFull:
                self.viewers.pop(ws,None)
                self.stats['slow_viewer_disconnects']+=1
                asyncio.create_task(ws.close(code=1013,message=b'slow media consumer'))
        now=time.perf_counter()
        if self.sent_at is not None:self.intervals.append(now-self.sent_at)
        self.sent_at=now
        self.stats['output_frames']+=1
        self.last_jpeg=jpeg

    async def pump(self):
        due=time.perf_counter()+.12
        while True:
            await asyncio.sleep(max(0,due-time.perf_counter()));due+=.04
            source=None
            try:source=self.source_queue.get_nowait()
            except asyncio.QueueEmpty:
                if self.mapping:self.stats['source_underflows_during_speech']+=1
            metadata=None
            pcm=SILENCE
            speaking=bool(source and self.mapping and source.epoch==self.mapping.source_epoch and source.flags&1
                          and source.sample_offset<self.mapping.total_samples)
            try:
                if self.pending_mode and self.body.at_boundary:
                    self.body=self.pending_body
                    self.mode=self.pending_mode
                    self.mouth=self.pending_mouth
                    self.pending_mode=None
                    self.pending_body=self.pending_mouth=None
                    self.sample_mouth=None
                    self.media=MediaProfile();self.keyframe=True
                    write_json(inside(self.root,'state/issac-stream/current-mode.json'),{'mode':self.mode})
                    self.audit.append('same_mode_bank_changed',mode=self.mode,real_loop_boundary=True)
                reserved=bool(self.mapping or self.speech_task and not self.speech_task.done())
                body=self.body.next(speaking=speaking,safe=not reserved and self.game_state.get('freshness')=='fresh' and self.game_state.get('paused') is True)
                if self.body.event!=self.last_body_event:
                    self.last_body_event=self.body.event.copy()
                    self.audit.append('body_clip_started',body_event=self.last_body_event)
                if speaking:
                    metadata=self.mapping.range_for(source,self.sequence,self.transport_id)
                    if metadata:
                        face=cv2.imdecode(np.frombuffer(source.jpeg,np.uint8),cv2.IMREAD_COLOR)
                        started=time.perf_counter()
                        body,oral=self.mouth.project(body,face,source.pcm)
                        elapsed=round((time.perf_counter()-started)*1e6)
                        self.stats['mouth_projection_max_us']=max(self.stats['mouth_projection_max_us'],elapsed)
                        self.sample_mouth=oral
                        self.stats['actual_model_oral_open_frames']+=int(oral.get('open',False))
                        pcm=source.pcm
                        self.stats['actual_audio_driven_mouth_frames']+=1
                        self.state='speaking'
                        if metadata['final']:
                            self.mapping=None;self.state='idle';self.stats['utterances_generated']+=1
                else:self.stats['body_only_frames']+=1
                await self.emit(self.jpeg(body),pcm,metadata)
            except Exception as error:
                self.media_fault=True
                self.media_error='MEDIA_CONTINUITY_OR_MAPPING_REJECTED'
                self.stage='media_quality_or_protocol_fault'
                self.stats['media_faults']+=1
                failed_id=self.mapping.command['request_id'] if self.mapping else metadata.get('request_id') if metadata else None
                if failed_id:
                    try:await self.fail(failed_id,'MEDIA_CONTINUITY_OR_MAPPING_REJECTED')
                    except Exception:self.audit.append('media_failure_callback_unavailable')
                # Keep a bounded protocol reason, never arbitrary exception text
                # that might contain a private endpoint or request body.
                reason=str(error)
                self.audit.append('media_frame_rejected',code=self.media_error,error_type=type(error).__name__,
                                  reason=reason if re.fullmatch('[A-Z][A-Z0-9_]{0,99}',reason) else 'UNCLASSIFIED_MEDIA_FAILURE')
                # No static substitute is advertised as a successful live frame.
                for ws in list(self.viewers):
                    try:await ws.close(code=1011,message=b'media validation failed')
                    except Exception:self.audit.append('media_consumer_close_unconfirmed')
                try:
                    receipt=await self.native_call({'action':'pause'})
                    self.audit.append('media_fault_normal_pause',native_receipt=receipt.get('native_receipt',{}))
                except Exception:
                    self.audit.append('media_fault_pause_unconfirmed',code='NORMAL_GAME_PAUSE_NOT_CONFIRMED')
                return
            if time.perf_counter()-due>.2:
                self.stats['pump_stalls']+=1;due=time.perf_counter()+.04
            if time.monotonic()-self.last_telemetry>=1:
                self.last_telemetry=time.monotonic()
                self.audit.append('media_clock',sequence=self.sequence,counters=dict(self.stats),body=self.body.status(),mouth=self.sample_mouth)

    async def stream(self,request):
        if stream_request_error(request.query) or request.query.get('v')!='3':raise web.HTTPBadRequest(text='MEDIA_V3_H264_REQUIRED')
        if request.query.get('programme_revision')!=self.web_revision:raise web.HTTPConflict(text='PROGRAMME_SOURCE_RELOAD_REQUIRED')
        if len(self.viewers)>=6:raise web.HTTPServiceUnavailable(text='MEDIA_VIEWER_LIMIT')
        ws=web.WebSocketResponse(heartbeat=20,compress=False,max_msg_size=2048,timeout=2)
        await ws.prepare(request)
        q=asyncio.Queue(maxsize=64);self.viewers[ws]=q;self.keyframe=True
        async def send():
            profile=None
            while not ws.closed:
                metadata,body=await q.get()
                if metadata and 'init' in metadata:
                    init=metadata['init']
                    if profile!=init['stream_id']:
                        if profile:await ws.send_json({'type':'media.reset','stream_id':profile,'reason':'new_source_profile'})
                        await ws.send_json(init);profile=init['stream_id']
                    if metadata['map']:await ws.send_json(metadata['map'])
                elif metadata:await ws.send_json(metadata)
                if body is not None:await ws.send_bytes(body)
        sender=asyncio.create_task(send())
        try:
            async for message in ws:
                if message.type==WSMsgType.TEXT:
                    try:
                        if json.loads(message.data)=={'type':'video.keyframe'}:self.keyframe=True
                    except ValueError:pass
        finally:
            self.viewers.pop(ws,None);sender.cancel();await asyncio.gather(sender,return_exceptions=True)
        return ws

    async def programme_page(self, request):
        html=inside(self.root,'web/issac/mc-programme.html').read_text('utf-8')
        html=html.replace('</head>',f'<meta name="mc-programme-revision" content="{self.web_revision}"></head>')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def layout(self,request):
        return web.json_response(read_json(inside(self.root,'configs/issac/programme-layout.json')))

    async def game_view(self,request):
        return web.json_response(self.game_state,headers={'Cache-Control':'no-store'})

    async def game_events(self,request):
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream','Cache-Control':'no-store'})
        await response.prepare(request)
        task=asyncio.current_task();self.game_event_tasks.add(task)
        try:
            while not self.stopping:
                payload=json.dumps(self.game_state,ensure_ascii=False)
                await asyncio.wait_for(response.write(('event: state\ndata: '+payload+'\n\n').encode()),2)
                await asyncio.sleep(.5)
        except (OSError,asyncio.TimeoutError):pass
        finally:self.game_event_tasks.discard(task)
        return response

    async def native_action(self,request):
        body=await request.json()
        if not isinstance(body,dict):raise web.HTTPBadRequest()
        async with self.http.post('http://127.0.0.1:9534/control',json=body,headers={'X-Isaac-Token':self.native_token},timeout=ClientTimeout(total=12)) as response:
            return web.json_response(await response.json(),status=response.status)

    async def native_call(self,body):
        async with self.http.post('http://127.0.0.1:9534/control',json=body,
                headers={'X-Isaac-Token':self.native_token},timeout=ClientTimeout(total=12)) as response:
            value=await response.json()
            if response.status!=200:raise AdmissionError('NATIVE_ACTION_NOT_ACKNOWLEDGED')
            return value

    async def change_mode(self,request):
        body=await request.json();mode=body.get('mode')
        if set(body)!={'mode'} or mode not in {'M01','M02','M03'}:raise web.HTTPBadRequest()
        if self.changing_mode or self.mapping or self.body.drinking or self.speech_task and not self.speech_task.done():
            return web.json_response({'error':'WAIT_FOR_SPEECH_AND_NATURAL_ACTION'},status=409)
        if mode==self.mode:return web.json_response({'mode':mode,'unchanged':True})
        self.changing_mode=True
        started=time.monotonic()
        try:
            def prepare_body():
                bank=BodyBank(self.root,mode);bank.preload()
                return bank,MouthProjector(self.root,mode,bank.reference)
            bank,mouth=await asyncio.to_thread(prepare_body)
            async with self.http.post(self.config['engine_url']+'/api/mode',json={'mode':mode},timeout=ClientTimeout(total=95)) as response:
                result=await response.json()
                if response.status!=200 or result.get('mode')!=mode or not result.get('ready'):
                    raise AdmissionError('SAME_MODE_ENGINE_SWITCH_NOT_CONFIRMED')
            self.pending_body,self.pending_mouth=bank,mouth
            self.pending_mode=mode
            deadline=time.monotonic()+20
            while self.pending_mode and time.monotonic()<deadline:await asyncio.sleep(.04)
            if self.mode!=mode:raise AdmissionError('REAL_G0_BOUNDARY_NOT_REACHED')
            return web.json_response({'mode':mode,'same_mode_bank':True,'game_control_changed':False,'seconds':time.monotonic()-started})
        except Exception as error:
            self.media_fault=True;self.media_error='MODE_SWITCH_NOT_CONFIRMED';self.stage='mode_switch_not_confirmed'
            reason=str(error) if isinstance(error,AdmissionError) else type(error).__name__
            self.audit.append('mode_switch_failed',mode=mode,seconds=time.monotonic()-started,reason=reason)
            return web.json_response({'error':'MODE_SWITCH_NOT_CONFIRMED'},status=503)
        finally:self.changing_mode=False

    async def natural_events(self):
        # Pause only at an observed cleared room. A revision fence prevents an
        # automatic resume from undoing a later operator pause or recovery.
        while True:
            try:
                now=time.monotonic()
                if self.auto_drink:
                    action=self.auto_drink
                    if self.body.drinking:action['started']=True
                    done=action['started'] and not self.body.drinking
                    if done or now>action['deadline']:
                        self.body.request_drink=False
                        if done and not self.media_fault and not self.changing_mode:
                            sample=await self.drink_sample()
                            if not verified_drink_pause(sample):raise AdmissionError('DRINK_PAUSE_OWNERSHIP_CHANGED')
                            await self.native_call({'action':'resume','expected_revision':action['control_revision']})
                            self.audit.append('natural_drink_completed',identity=action['identity'],control_revision=action['control_revision'])
                        elif not done:
                            self.audit.append('natural_drink_deadline_exceeded',automatic_resume=False)
                        self.auto_drink=None
                        self.last_auto_drink=now
                elif (not self.media_fault and not self.changing_mode and not self.mapping
                      and (self.speech_task is None or self.speech_task.done())
                      and now-self.last_auto_drink>=300 and self.game_state.get('freshness')=='fresh'
                      and self.game_state.get('armed') and self.game_state.get('clear')
                      and any(c.get('runtime_enabled') and c['mode']==self.mode for c in self.body.registry.get('drink_chains',[]))):
                    async with self.http.get('http://127.0.0.1:9534/status',timeout=ClientTimeout(total=2)) as response:status=await response.json()
                    result=await self.native_call({'action':'pause','expected_revision':status['control_revision']})
                    if result.get('native_receipt',{}).get('normal_game_pause_acknowledged'):
                        native=result['native_receipt'];created=time.time()
                        async with self.http.get('http://127.0.0.1:9532/query?topic=state',timeout=ClientTimeout(total=2)) as response:view=await response.json()
                        self.auto_drink={'kind':'drink','control_revision':result['control_revision'],
                            'native_receipt':native,'identity':view.get('identity'),'started':False,
                            'created_unix':created,'expires_unix':created+60,'deadline':time.monotonic()+60}
                        sample=await self.drink_sample()
                        if not verified_drink_pause(sample):raise AdmissionError('FRESH_SAFE_DRINK_PAUSE_REQUIRED')
                        self.body.request_drink=True
                        self.audit.append('natural_drink_pause_confirmed',control_revision=result['control_revision'],identity=view['identity'],stable_frame=native['stable_frame'])
            except Exception as error:
                reason=str(error) if isinstance(error,AdmissionError) else 'NATURAL_ACTION_NOT_CONFIRMED'
                self.audit.append('natural_action_stopped',reason=reason,automatic_resume=False)
                self.body.request_drink=False;self.auto_drink=None;self.last_auto_drink=time.monotonic()
            await asyncio.sleep(1)

    def natural_action(self):
        return {k:v for k,v in self.auto_drink.items() if k!='deadline'} if self.auto_drink else None

    async def drink_sample(self):
        values={}
        for key,port,path in (('state',9532,'/query?topic=state'),('game',9534,'/status')):
            async with self.http.get(f'http://127.0.0.1:{port}'+path,timeout=ClientTimeout(total=2)) as response:
                if response.status!=200:raise AdmissionError('DRINK_PAUSE_OBSERVATION_UNAVAILABLE')
                values[key]=await response.json()
        values['studio']={'natural_action':self.natural_action(),'ready':not self.media_fault}
        return values

    async def static(self,request):
        name=request.match_info['name']
        if name not in WEB_FILES:raise web.HTTPNotFound()
        return web.FileResponse(inside(self.root,'web/issac/'+name),headers={'Cache-Control':'no-store'})

    async def application_action(self,request):
        body=await request.json()
        if body!={'action':'launch_game'}:raise web.HTTPBadRequest()
        async with self.http.post('http://127.0.0.1:9541/action',json=body,
                headers={'X-Isaac-Token':self.native_token},timeout=ClientTimeout(total=20)) as response:
            result=await response.json()
            if response.status!=200:return web.json_response(result,status=response.status)
        deadline=time.monotonic()+30
        while True:
            try:
                receipt=await self.native_call({'action':'attach','pid':result['pid']})
                return web.json_response({'pid':result['pid'],'attached':True,'native':receipt})
            except AdmissionError:
                if time.monotonic()>=deadline:
                    return web.json_response({'pid':result['pid'],'attached':False,'error':'GAME_STARTED_BRIDGE_NOT_READY'},status=409)
                await asyncio.sleep(.5)

    async def status(self,request):
        return web.json_response({'service':'issac-studio','character_id':'naimei','ready':self.stage=='ready',
            'stage':self.stage,'error':self.media_error,'tts_ready':self.voice_ready(),'avatar_ready':self.engine_health.get('ready',False),
            'speaking':self.state=='speaking','state':self.state,'viewers':len(self.viewers),'mode':self.mode,
            'size':512,'fps':25,'steps':4,'voice_id':'NCM01','voice_freeze_id':self.voice_profile.get('freeze_id'),
            'programme':{'title':'奶妹 · 以撒的结合','width':1920,'height':1080,'fps':30,'revision':self.web_revision},
            'game':self.game_state,'body':self.body.status(),'natural_action':self.natural_action(),'counters':dict(self.stats),'engine':self.engine_health,
            'mouth_postprocess':'actual_flashhead_oral_pixels_with_two_original_upper_fangs','mouth_diagnostic':self.sample_mouth,
            'output_fps_measured':len(self.intervals)/sum(self.intervals) if self.intervals else 0,
            'source_queue_frames':self.source_queue.qsize(),'quality_accepted':False,'cloud_fallback':False})

    async def startup(self,app):
        self.media_timer.start()
        cv2.setNumThreads(1)
        try:await asyncio.to_thread(self.body.preload)
        except BaseException:
            self.media_timer.close()
            raise
        self.http=ClientSession(trust_env=False)
        self.tasks=[asyncio.create_task(fn()) for fn in (self.source_reader,self.refresh_health,self.game_monitor,self.natural_events,self.pump)]

    async def cleanup(self,app):
        if self.cleanup_started:return
        self.cleanup_started=True;self.stopping=True
        tasks=[*self.game_event_tasks,*getattr(self,'command_tasks',set())]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        # Close the upstream client first so its WebSocket context cannot keep
        # a cancelled reader waiting for the remote close handshake.
        if self.http:await self.http.close()
        try:await super().cleanup(app)
        finally:
            if getattr(self,'media_timer',None):self.media_timer.close()

    def application(self):
        app=web.Application(client_max_size=1024*1024)
        app.add_routes([web.get('/',lambda _:web.FileResponse(inside(self.root,'web/issac/director.html'))),
            web.get('/issac/programme',self.programme_page),web.get('/issac/preview',self.programme_page),web.get('/issac/layout.json',self.layout),
            web.get('/api/studio/status',self.status),web.get('/health',self.status),web.get('/api/studio/stream',self.stream),
            web.post('/internal/dsh/{action}',self.dsh_command),web.get('/api/naimei/captions/{request_id}',self.caption_data),
            web.get('/api/dsh/game/state',self.game_view),web.get('/api/dsh/game/events',self.game_events),
            web.post('/api/issac/native',self.native_action),web.route('*','/api/dsh/{tail:.*}',self.proxy),
            web.post('/api/issac/mode',self.change_mode),
            web.post('/api/issac/application',self.application_action),
            web.get('/{name}',self.static)])
        app.on_startup.append(self.startup);app.on_cleanup.append(self.cleanup)
        # Close media sockets before AppRunner waits for active handlers. Waiting
        # until on_cleanup leaves WebSocket consumers holding shutdown open.
        app.on_shutdown.append(self.cleanup)
        from .shutdown import aiohttp_shutdown
        aiohttp_shutdown(app,self.root)
        return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    from .deployment import require_candidate
    require_candidate(args.root)
    studio=IsaacStudio(args.root.resolve())
    from .shutdown import run_web
    run_web(studio.application(),args.root,host=studio.config['host'],port=studio.config['port'])
