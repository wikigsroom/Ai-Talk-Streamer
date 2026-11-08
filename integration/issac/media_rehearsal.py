"""A bounded live media rehearsal; no game, strategy model or production approval.

The browser records its entire visible programme canvas and the same scheduled
audio it plays. FlashHead generates with bounded lookahead during that recording.
Unapproved body candidates remain review inputs; this never enables their bank.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import io
import json
from pathlib import Path
import queue
import struct
import subprocess
import threading
import time
import traceback
import uuid
import wave

from aiohttp import ClientSession, ClientTimeout, web
import cv2
import numpy as np

from .common import AdmissionError, FileLease, file_hash, inside, read_json, write_json
from .deployment import require_candidate
from .materials import MATERIAL_ROOT, OPEN_ANCHOR, OPEN_SHA, ffmpeg
from .mouth import MouthProjector

MODES = {'M01':'日光陪玩','M02':'暖夜陪玩','M03':'专注对局'}
TEXT = {
    'M01':['嗨，我是奶妹。先把手柄拿稳，咱们慢慢来。','喝口水回来啦，继续一起玩吧。'],
    'M02':['晚上好呀，我是奶妹。灯开得暖一点，慢慢玩。','水喝好了，大家也记得休息哦。'],
    'M03':['准备好了，我是奶妹。手柄握稳，先看清楚再动。','回来啦，咱们接着认真玩吧。'],
}
FRAMES, FPS, SAMPLES = 750, 25, 640
SOURCE_CANDIDATE = 'issac-c52202cff690-d0d3088d'
HEADER = struct.Struct('<III')


def decode_body(root, mode, action):
    """Use verified real frames for review without manufacturing approval."""
    base = inside(root, 'state/issac-materials/generations/'+SOURCE_CANDIDATE)
    clip_id = mode+'-'+action+'-take01'
    proof = read_json(base/'inspection'/clip_id/'inspection.json')
    path = inside(root, proof['path'])
    if (proof['candidate_id'] != SOURCE_CANDIDATE or proof['mode'] != mode
            or proof['endpoint_replacement'] is not False
            or proof['start_state'] != mode+'-G0' or proof['end_state'] != mode+'-G0'
            or file_hash(path) != proof['sha256']):
        raise AdmissionError('UNCHANGED_REAL_G0_BODY_CANDIDATE_REQUIRED')
    cap = cv2.VideoCapture(str(path)); frames = []
    try:
        if abs(cap.get(cv2.CAP_PROP_FPS)-25) > .01:
            raise AdmissionError('REAL_25FPS_BODY_REQUIRED')
        while True:
            ok, frame = cap.read()
            if not ok: break
            if frame.shape != (512,512,3): raise AdmissionError('BODY_SHAPE_CHANGED')
            frames.append(frame)
            if len(frames) > 375: raise AdmissionError('BOUNDED_BODY_REQUIRED')
    finally: cap.release()
    if len(frames) != proof['decoded_frames'] or len(frames) != 294:
        raise AdmissionError('COMPLETE_294_FRAME_BODY_REQUIRED')
    return frames, {'id':clip_id,'sha256':proof['sha256'],'frames':len(frames),
                    'source_candidate':SOURCE_CANDIDATE,'quality_approved':False}


def body_frame(index, controller, drink):
    if index < 294: return controller[index], False
    if index < 588: return drink[index-294], True
    return controller[index-588], False


class Rehearsal:
    def __init__(self, root):
        self.root = root
        self.candidate = require_candidate(root)
        self.owner = FileLease(inside(root,'state/issac-stream/media-rehearsal.lock')).acquire()
        self.folder = inside(root,'outputs/issac/media30')/uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.stage = 'preparing_ncm01'
        self.error = None
        self.engine = None
        self.audio = {}
        self.bodies = {}
        self.reference = {}
        self.completed = {}
        self.active = None
        self.stop = threading.Event()
        self.native_stop = inside(root,'state/issac-stream/media30.stop')
        self.constraints = {'upper_fangs':[
            {'path':MATERIAL_ROOT+f'/assets/naimei/production-freeze-v1/snapshots/mouth/original-upper-fang-{n}.png',
             'sha256':file_hash(inside(root,MATERIAL_ROOT+f'/assets/naimei/production-freeze-v1/snapshots/mouth/original-upper-fang-{n}.png'))}
            for n in (1,2)]}
        write_json(inside(root,'state/issac-stream/media30-current.json'),{'folder':self.folder.relative_to(root).as_posix(),**self.candidate})

    def status(self):
        return {**self.candidate,'stage':self.stage,'ready':self.stage=='ready','error':self.error,
                'active_mode':self.active,'completed':self.completed,'game_started':False,
                'strategy_model_loaded':False,'voice_id':'NCM01','mouth':'FlashHead Lite 512/25/4/batch1',
                'recording_scope':'entire visible browser programme canvas and its actual audio',
                'is_official_livehime_recording':False,'body_quality_approved':False}

    async def prepare(self):
        try:
            binding = read_json(inside(self.root,'configs/issac/character-inheritance.json'))
            async with ClientSession(timeout=ClientTimeout(total=120)) as http:
                for mode in MODES:
                    row = next(r for r in binding['modes'] if r['mode_id']==mode)
                    ref = inside(self.root,row['reference_image'])
                    if file_hash(ref)!=row['sha256']: raise AdmissionError('LOCKED_REFERENCE_CHANGED')
                    self.reference[mode] = cv2.resize(cv2.imdecode(np.fromfile(ref,np.uint8),cv2.IMREAD_COLOR),(512,512))
                    first, proof1 = await asyncio.to_thread(decode_body,self.root,mode,'V02-01')
                    drink, proof2 = await asyncio.to_thread(decode_body,self.root,mode,'V23-01')
                    self.bodies[mode] = (first,drink,[proof1,proof2])
                    pcm = np.zeros(FRAMES*SAMPLES,np.int16); captions=[]; metrics=[]
                    for slot, text in enumerate(TEXT[mode]):
                        rid = 'media30-'+self.folder.name+'-'+mode+'-'+str(slot)
                        async with http.post('http://127.0.0.1:9893/tts',json={'text':text,'request_id':rid,'voice_id':'NCM01'}) as response:
                            if response.status!=200: raise AdmissionError('NEW_NCM01_GENERATION_FAILED')
                            audio=await response.read()
                        path=self.folder/(mode+f'-speech-{slot}.wav');path.write_bytes(audio)
                        async with http.get('http://127.0.0.1:9893/metrics/'+rid) as response:
                            metric=await response.json()
                        if (metric.get('voice_id')!='NCM01' or metric.get('steps')!=32
                                or metric.get('reference_preprocess_prompt') is not False):
                            raise AdmissionError('FROZEN_VOICE_CONFIGURATION_REQUIRED')
                        with wave.open(io.BytesIO(audio),'rb') as wav:
                            seconds=wav.getnframes()/wav.getframerate()
                        start_frame=(18,604)[slot]
                        limit_frame=(286,746)[slot]
                        if start_frame+round(seconds*25)>limit_frame:
                            raise AdmissionError('SPEECH_EXCEEDS_NONDRINK_SLOT')
                        command=[ffmpeg(self.root),'-v','error','-i',str(path),'-f','s16le','-ac','1','-ar','16000','pipe:1']
                        raw=await asyncio.to_thread(subprocess.run,command,capture_output=True,check=True,timeout=60,creationflags=0x08000000)
                        values=np.frombuffer(raw.stdout,dtype='<i2')
                        offset=start_frame*SAMPLES;pcm[offset:offset+len(values)]=values
                        captions.append({'start':start_frame/25,'end':start_frame/25+seconds,'text':text})
                        metrics.append({k:metric[k] for k in ('voice_id','steps','precision','reference_preprocess_prompt','voice_freeze_id','audio_seconds','wall_seconds')})
                    self.audio[mode]=(pcm,captions,metrics)
            self.stage='warming_real_flashhead'
            self.engine=await asyncio.to_thread(self.load_engine)
            self.stage='ready'
            write_json(self.folder/'prepared.json',{'candidate':self.candidate,'voice':'NCM01',
                'body_inputs':{m:self.bodies[m][2] for m in MODES},'actual_loading':self.engine.loading,
                'new_model_download_bytes':0,'quality_approved':False})
        except Exception:
            self.stage='failed';self.error='MEDIA_REHEARSAL_PREPARATION_FAILED'
            (self.folder/'private-error.log').write_text(traceback.format_exc(),'utf8')

    def load_engine(self):
        from .flashhead import Engine
        from .resources import wait_for_capacity
        wait_for_capacity(self.stop,10000)
        class OralEngine(Engine):
            def configure(this,mode):
                ref=inside(this.root,MATERIAL_ROOT+'/'+OPEN_ANCHOR)
                if file_hash(ref)!=OPEN_SHA: raise AdmissionError('LOCKED_ORAL_ANCHOR_REQUIRED')
                with this.torch.inference_mode():
                    this.pipeline.prepare_params(str(ref),(512,512),this.frames,this.overlap,4,42,5.,1.,False)
                this.mode='media-rehearsal';this.reset()
        engine=OralEngine(self.root)
        for _ in range(4): engine.render(np.zeros(engine.samples,np.int16))
        engine.reset()
        return engine

    def produce(self,mode,output,cancel,receipt):
        """At most 48 prepared frames ahead; never render a whole movie first."""
        try:
            self.engine.reset()
            mouth=MouthProjector(self.root,mode,self.reference[mode],constraints=self.constraints)
            pcm,captions,_=self.audio[mode]
            controller,drink,_=self.bodies[mode]
            counters=Counter();timings=[];rows=[]
            receipt['generation_started_unix']=time.time()
            for offset in range(0,FRAMES,self.engine.new_frames):
                if cancel.is_set() or self.stop.is_set(): return
                samples=pcm[offset*SAMPLES:(offset+self.engine.new_frames)*SAMPLES]
                samples=np.pad(samples,(0,self.engine.samples-len(samples)))
                frames,timing=self.engine.render(samples);timings.append(timing)
                for j,model_rgb in enumerate(frames[:min(self.engine.new_frames,FRAMES-offset)]):
                    index=offset+j;body,drinking=body_frame(index,controller,drink)
                    paired=pcm[index*SAMPLES:(index+1)*SAMPLES].tobytes()
                    spoken=bool(np.any(np.frombuffer(paired,dtype='<i2')))
                    if drinking and spoken: raise AdmissionError('NO_SPEECH_WITH_CUP_OCCLUSION')
                    oral={'open':False,'drinking':drinking}
                    if spoken:
                        body,oral=mouth.project(body,model_rgb[...,::-1].copy(),paired)
                        counters['actual_audio_driven_mouth_frames']+=1
                        counters['oral_open_frames']+=int(oral.get('open',False))
                    else: mouth.reset()
                    counters['body_frames']+=1;counters['drink_frames']+=int(drinking)
                    rows.append({'frame':index,'at_unix':time.time(),**oral})
                    ok,jpg=cv2.imencode('.jpg',body,[cv2.IMWRITE_JPEG_QUALITY,95])
                    if not ok: raise AdmissionError('LIVE_FRAME_ENCODING_FAILED')
                    packet=HEADER.pack(index,len(jpg),SAMPLES)+paired+jpg.tobytes()
                    while not cancel.is_set() and not self.stop.is_set():
                        try: output.put(packet,timeout=.2);break
                        except queue.Full: pass
                    if cancel.is_set() or self.stop.is_set(): return
            receipt.update(counters=dict(counters),timings=timings,generation_finished_unix=time.time())
            write_json(self.folder/(mode+'-live-frame-evidence.json'),{'rows':rows,'receipt':receipt})
        except Exception:
            receipt['error']='LIVE_MEDIA_GENERATION_FAILED'
            (self.folder/(mode+'-private-error.log')).write_text(traceback.format_exc(),'utf8')
        finally:
            while not cancel.is_set() and not self.stop.is_set():
                try: output.put(None,timeout=.2);break
                except queue.Full: pass

    async def stream(self,request):
        mode=request.match_info['mode']
        if mode not in MODES or self.stage!='ready' or self.active:
            raise web.HTTPConflict(text='SINGLE_READY_MEDIA_REHEARSAL_REQUIRED')
        self.active=mode
        ws=web.WebSocketResponse(compress=False,max_msg_size=2048);await ws.prepare(request)
        output=queue.Queue(maxsize=48);cancel=threading.Event()
        receipt={'mode':mode,'candidate':self.candidate,'maximum_queued_frames':48,'source_fps':25,
                 'raw_mouth_is_live':True,'game_started':False,'strategy_model_loaded':False}
        producer=threading.Thread(target=self.produce,args=(mode,output,cancel,receipt),daemon=True)
        producer.start();sent=0;late=[]
        try:
            await ws.send_json({'type':'begin','mode':mode,'name':MODES[mode],'frames':750,'fps':25,
                                'captions':self.audio[mode][1],'voice_id':'NCM01'})
            first=await asyncio.to_thread(output.get,True,180)
            if first is None: raise AdmissionError('LIVE_GENERATION_FAILED_BEFORE_FIRST_FRAME')
            started=time.perf_counter();receipt['delivery_started_unix']=time.time()
            item=first
            while item is not None:
                due=started+sent/25;await asyncio.sleep(max(0,due-time.perf_counter()))
                late.append(max(0,time.perf_counter()-due));await ws.send_bytes(item);sent+=1
                item=await asyncio.to_thread(output.get,True,30)
            if sent!=750 or receipt.get('error'): raise AdmissionError('ALL_750_REAL_FRAMES_REQUIRED')
            receipt.update(delivered_frames=sent,delivery_seconds=time.perf_counter()-started,
                max_delivery_lateness_seconds=max(late),late_over_40ms=sum(x>.04 for x in late),
                delivery_finished_unix=time.time(),voice_generation_metrics=self.audio[mode][2])
            write_json(self.folder/(mode+'-live-receipt.json'),receipt)
            await ws.send_json({'type':'complete','receipt':{k:receipt[k] for k in ('delivered_frames','max_delivery_lateness_seconds')}})
        except Exception:
            write_json(self.folder/(mode+'-delivery-error.json'),{'frames':sent,'error':receipt.get('error','LIVE_DELIVERY_FAILED')})
            await ws.send_json({'type':'error','error':'LIVE_MEDIA_DELIVERY_FAILED'})
        finally:
            cancel.set();await asyncio.to_thread(producer.join,30)
            self.active=None;await ws.close()
        return ws

    async def upload(self,request):
        mode=request.match_info['mode']
        if mode not in MODES or mode in self.completed: raise web.HTTPConflict()
        receipt=read_json(self.folder/(mode+'-live-receipt.json'))
        if receipt['delivered_frames']!=750: raise web.HTTPConflict()
        raw=self.folder/(mode+'-whole-page.webm')
        if raw.exists(): raise web.HTTPConflict(text='RECORDING_ALREADY_EXISTS')
        with raw.open('xb') as stream:
            async for chunk in request.content.iter_chunked(1024*1024): stream.write(chunk)
        final=self.folder/(mode+'-30s.mp4')
        command=[ffmpeg(self.root),'-v','error','-n','-i',str(raw),'-t','30','-c:v','libx264','-preset','fast','-crf','17',
                 '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(final)]
        result=await asyncio.to_thread(subprocess.run,command,capture_output=True,timeout=120,creationflags=0x08000000)
        if result.returncode: raise AdmissionError('LIVE_BROWSER_RECORDING_TRANSCODE_FAILED')
        self.completed[mode]={'file':final.name,'sha256':file_hash(final),'bytes':final.stat().st_size,
                              'raw_file':raw.name,'raw_sha256':file_hash(raw)}
        write_json(self.folder/'recordings.json',self.status())
        return web.json_response(self.completed[mode])


async def serve(root):
    rehearsal=Rehearsal(root)
    async def page(_):return web.FileResponse(inside(root,'web/issac/media-rehearsal.html'))
    async def status(_):return web.json_response(rehearsal.status())
    async def metrics(request):
        value=await request.json()
        if value.get('mode') not in MODES: raise web.HTTPBadRequest()
        write_json(rehearsal.folder/(value['mode']+'-browser-metrics.json'),value)
        return web.json_response({'saved':True})
    app=web.Application(client_max_size=100*1024**2)
    app.add_routes([web.get('/',page),web.get('/health',status),web.get('/status',status),
                    web.get('/stream/{mode}',rehearsal.stream),web.post('/recording/{mode}',rehearsal.upload),
                    web.post('/browser-metrics',metrics)])
    runner=web.AppRunner(app,access_log=None)
    try:
        await runner.setup();await web.TCPSite(runner,'127.0.0.1',8072).start()
        preparation=asyncio.create_task(rehearsal.prepare())
        while not rehearsal.native_stop.exists():await asyncio.sleep(.5)
        rehearsal.stop.set()
        await preparation
    finally:
        rehearsal.stop.set();await runner.cleanup();rehearsal.owner.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    asyncio.run(serve(args.root.resolve()))
