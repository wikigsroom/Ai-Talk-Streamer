"""One audio producer; actual generated frames and their 640-sample audio spans."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter,deque
import io
from pathlib import Path
import queue
import struct
import subprocess
import threading
import time
import uuid
import wave

from aiohttp import web
import cv2
import numpy as np

from .common import AdmissionError, Audit, FileLease, inside, read_json


HEADER=struct.Struct('<4sIIIdIII')


class EngineService:
    def __init__(self, root):
        self.root=Path(root).resolve()
        self.config=read_json(inside(root,'configs/issac/runtime.json'))
        self.mode=self.config['media']['default_mode']
        self.lease=FileLease(inside(root,'state/issac-stream/flashhead.lock')).acquire()
        self.audit=Audit(inside(root,'state/issac-stream/flashhead-events.jsonl'))
        self.stop=threading.Event()
        self.lock=threading.RLock()
        self.input=queue.Queue(maxsize=3)
        self.output=queue.Queue(maxsize=48)
        self.ready=False
        self.stage='waiting_for_gpu'
        self.error=None
        self.epoch=0
        self.active=None
        self.ended=False
        self.drained=False
        self.viewers={}
        self.stats=Counter()
        self.timings=deque(maxlen=1024)
        self.feed_task=None
        self.mode_request=None
        self.mode_completed=None
        image=cv2.imdecode(np.fromfile(inside(root,f'assets/issac/references/{self.mode}.png'),np.uint8),cv2.IMREAD_COLOR)
        image=cv2.resize(image,(512,512),interpolation=cv2.INTER_AREA)
        self.idle=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,85])[1].tobytes()

    def cancel(self, reason):
        with self.lock:
            self.epoch+=1
            self.active=None
            self.ended=False
            self.drained=False
            for q in (self.input,self.output):
                while not q.empty():
                    try:q.get_nowait()
                    except queue.Empty:break
            self.stats['interrupts']+=1
            self.audit.append('generation_cancelled',reason=reason,epoch=self.epoch)
            return self.epoch

    def worker(self):
        try:
            while not self.stop.is_set():
                raw=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'],
                                            timeout=10,text=True,creationflags=0x08000000)
                free,utilization=[int(x.strip()) for x in raw.strip().split(',')]
                if free>=10000 and utilization<35:break
                self.stage='waiting_for_existing_gpu_tasks'
                self.stop.wait(2)
            if self.stop.is_set():return
            self.stage='loading'
            from .flashhead import Engine
            engine=Engine(self.root,self.mode)
            self.stage='warming_up'
            for _ in range(4):engine.render(np.zeros(engine.samples,np.int16))
            engine.reset()
            self.ready=True
            self.stage='ready'
            previous=-1
            while not self.stop.is_set():
                with self.lock:
                    requested=self.mode_request
                    self.mode_request=None
                if requested:
                    engine.configure(requested)
                    engine.reset()
                    with self.lock:
                        self.mode=requested
                        self.mode_completed=requested
                        self.ready=True
                        self.stage='ready'
                try:epoch,offset,pcm,valid=self.input.get(timeout=.1)
                except queue.Empty:
                    if self.ended and self.input.empty():self.drained=True
                    continue
                if epoch!=self.epoch:continue
                if previous!=epoch:engine.reset();previous=epoch
                frames,timing=engine.render(pcm)
                self.timings.append(timing['seconds'])
                if epoch!=self.epoch:
                    self.stats['discarded_stale_chunks']+=1;continue
                for i,frame in enumerate(frames[:(valid+639)//640]):
                    jpeg=cv2.imencode('.jpg',cv2.cvtColor(frame,cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,85])[1].tobytes()
                    samples=pcm[i*640:(i+1)*640].astype('<i2',copy=False).tobytes()
                    item=(epoch,offset+i*640,jpeg,samples)
                    while not self.stop.is_set() and epoch==self.epoch:
                        try:self.output.put(item,timeout=.1);break
                        except queue.Full:continue
                self.stats['actual_generated_frames']+=len(frames)
                if self.ended and self.input.empty():self.drained=True
        except Exception:
            self.ready=False
            self.stage='failed'
            self.error='NATIVE_FLASHHEAD_FAILED'
            import traceback
            self.audit.append('engine_exception',private_diagnostic=traceback.format_exc())

    async def utterance(self, request):
        if request.remote!='127.0.0.1':raise web.HTTPForbidden()
        with self.lock:
            if not self.ready:return web.json_response({'error':'ENGINE_NOT_READY'},status=503)
            if self.active is not None:return web.json_response({'error':'SINGLE_AUDIO_PRODUCER_REQUIRED'},status=409)
        data=await request.read()
        try:
            with wave.open(io.BytesIO(data),'rb') as stream:
                if stream.getframerate()!=16000 or stream.getsampwidth()!=2 or stream.getnchannels()!=1:
                    raise ValueError()
                n=stream.getnframes()
                if not 1<=n<=16000*40:raise ValueError()
                pcm=np.frombuffer(stream.readframes(n),dtype='<i2').copy()
                if len(pcm)!=n:raise ValueError()
        except (ValueError,wave.Error,EOFError):
            return web.json_response({'error':'ACTUAL_MONO_PCM16_16KHZ_REQUIRED'},status=400)
        with self.lock:
            if self.active is not None:return web.json_response({'error':'SINGLE_AUDIO_PRODUCER_REQUIRED'},status=409)
            epoch=self.cancel('new_utterance')
            self.active=uuid.uuid4().hex
            self.stats['accepted_pcm_samples']+=n
        async def feed():
            offset=0
            try:
                while offset<n and epoch==self.epoch:
                    valid=min(15360,n-offset)
                    block=np.zeros(15360,np.int16);block[:valid]=pcm[offset:offset+valid]
                    await asyncio.to_thread(self.input.put,(epoch,offset,block,valid),True,3)
                    offset+=valid
                if epoch==self.epoch:self.ended=True
            except (queue.Full,asyncio.CancelledError):
                if epoch==self.epoch:self.cancel('input_feed_incomplete')
        self.feed_task=asyncio.create_task(feed())
        return web.json_response({'accepted':True,'epoch':epoch,'valid_samples':n,'sample_rate':16000})

    async def pump(self):
        seq=0
        due=time.monotonic()
        playout=None
        playout_epoch=-1
        while not self.stop.is_set():
            await asyncio.sleep(max(0,due-time.monotonic()))
            due+=.04
            if playout_epoch!=self.epoch:
                playout=None
                playout_epoch=self.epoch
            item=None
            if self.active and playout is None and self.output.qsize()>=6:playout=time.monotonic()+.24
            if self.active and self.drained and self.output.qsize() and playout is None:playout=time.monotonic()+.24
            if playout is not None and time.monotonic()>=playout:
                while not self.output.empty():
                    candidate=self.output.get_nowait()
                    if candidate[0]==self.epoch:item=candidate;break
                if item is None:
                    if self.drained:self.active=None;playout=None;self.stats['utterances_generated']+=1
                    elif self.active:self.stats['speech_underflows']+=1
            if not self.active:playout=None
            if item:
                epoch,offset,jpeg,pcm=item;flags=1
                self.stats['actual_model_frames_delivered']+=1
            else:
                epoch,offset,jpeg,pcm,flags=self.epoch,0xffffffff,self.idle,bytes(1280),4
                self.stats['idle_frames']+=1
            packet=HEADER.pack(b'NML1',seq,len(jpeg),16000,seq/25,epoch,flags,offset)+jpeg+pcm
            for ws,q in list(self.viewers.items()):
                if q.full():
                    self.viewers.pop(ws,None);asyncio.create_task(ws.close(code=1013,message=b'slow consumer'))
                    self.stats['slow_consumer_disconnects']+=1
                else:q.put_nowait(packet)
            seq=(seq+1)&0xffffffff
            if time.monotonic()-due>.2:
                self.stats['scheduler_stalls']+=1;due=time.monotonic()+.04

    async def output_stream(self,request):
        if request.remote!='127.0.0.1':raise web.HTTPForbidden()
        if len(self.viewers)>=2:raise web.HTTPServiceUnavailable(text='VIEWER_LIMIT')
        ws=web.WebSocketResponse(heartbeat=20,compress=False,max_msg_size=1024)
        await ws.prepare(request)
        q=asyncio.Queue(maxsize=12);self.viewers[ws]=q
        async def send():
            while not ws.closed:await asyncio.wait_for(ws.send_bytes(await q.get()),2)
        task=asyncio.create_task(send())
        try:
            async for _ in ws:pass
        finally:
            self.viewers.pop(ws,None);task.cancel();await asyncio.gather(task,return_exceptions=True)
        return ws

    async def health(self,request):
        values=list(self.timings)
        return web.json_response({'service':'issac-flashhead-lite','ready':self.ready,'stage':self.stage,'error':self.error,
            'size':512,'fps':25,'steps':4,'batch_size':1,'mode':self.mode,'epoch':self.epoch,'active':bool(self.active),
            'actual_generation_fps':24*len(values)/sum(values) if values else None,'counters':dict(self.stats),
            'quality_accepted':False,'diagnostic_output_is_production_acceptance':False})

    async def interrupt(self,request):
        if request.remote!='127.0.0.1':raise web.HTTPForbidden()
        return web.json_response({'ok':True,'epoch':self.cancel('operator_or_generation_cancel')})

    async def change_mode(self,request):
        if request.remote!='127.0.0.1':raise web.HTTPForbidden()
        body=await request.json()
        mode=body.get('mode')
        if mode not in {'M01','M02','M03'}:raise web.HTTPBadRequest()
        with self.lock:
            if self.active or self.mode_request or not self.ready:
                return web.json_response({'error':'MODE_SWITCH_REQUIRES_IDLE_ENGINE'},status=409)
            self.cancel('mode_switch')
            self.ready=False
            self.stage='changing_mode'
            self.mode_completed=None
            self.mode_request=mode
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            if self.stage=='failed':break
            if self.mode_completed==mode:return web.json_response({'mode':mode,'ready':True,'epoch':self.epoch})
            await asyncio.sleep(.1)
        return web.json_response({'error':'MODE_SWITCH_NOT_CONFIRMED'},status=503)

    async def startup(self,app):
        cv2.setNumThreads(1)
        self.thread=threading.Thread(target=self.worker,daemon=True);self.thread.start()
        self.pump_task=asyncio.create_task(self.pump())

    async def cleanup(self,app):
        self.cancel('shutdown');self.stop.set()
        if self.feed_task:self.feed_task.cancel()
        self.pump_task.cancel();await asyncio.gather(self.pump_task,return_exceptions=True)
        for ws in list(self.viewers):await ws.close()
        await asyncio.to_thread(self.thread.join,20)
        if self.thread.is_alive():
            raise AdmissionError('ENGINE_WORKER_SHUTDOWN_NOT_CONFIRMED')
        self.lease.close()

    def application(self):
        app=web.Application(client_max_size=2*1024*1024)
        app.add_routes([web.get('/health',self.health),web.get('/api/output',self.output_stream),
                        web.post('/api/utterance',self.utterance),web.post('/api/interrupt',self.interrupt),
                        web.post('/api/mode',self.change_mode)])
        app.on_startup.append(self.startup);app.on_cleanup.append(self.cleanup)
        from .shutdown import aiohttp_shutdown
        aiohttp_shutdown(app,self.root)
        return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    from .deployment import require_candidate
    require_candidate(args.root)
    server=EngineService(args.root.resolve())
    web.run_app(server.application(),host='127.0.0.1',port=server.config['media']['engine_port'],access_log=None)
