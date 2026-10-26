"""Paced H264/JPEG plus PCM broadcasting, sharing one native avatar render."""
import asyncio,json,queue,struct,threading,time,uuid
import cv2,numpy as np
from aiohttp import web
from utils.logger import logger
from server.viewer_buffer import ViewerBuffer
from server.stream_encoder import H264Encoder

class LocalBroadcast:
    def __init__(self,avatar):
        self.avatar=avatar;self.queue=queue.Queue(maxsize=32);self.viewers={};self.quit=threading.Event()
        self.pending=None;self.audio=[];self.events=[];self.sequence=0;self.started=time.perf_counter();self.frames=0
        self.transport_instance_id='transport-'+uuid.uuid4().hex
        self.encoder=None;self.force_keyframe=False
        avatar.output._player=self
        cv2.setNumThreads(1)
        self.thread=threading.Thread(target=avatar.render,args=(self.quit,),name='local-avatar-render',daemon=True)
        self.thread.start();self.task=asyncio.create_task(self.pump())
    def push_video(self,frame):self.pending=frame.copy();self.audio=[];self.events=[]
    def push_audio(self,frame,eventpoint=None):
        self.audio.append(np.asarray(frame,dtype=np.int16))
        if eventpoint:self.events.append((len(self.audio)-1,eventpoint))
        if len(self.audio)==2:
            self.queue.put((self.pending,np.concatenate(self.audio),self.events));self.pending=None
    def get_buffer_size(self):return self.queue.qsize()
    async def pump(self):
        # Python 3.10's Windows event-loop clock can have coarse ticks. Keep the
        # media deadline on the high-resolution clock used by our arrival probes.
        due=time.perf_counter()
        while not self.quit.is_set():
            try:item=await asyncio.to_thread(self.queue.get,True,1)
            except queue.Empty:due=time.perf_counter();continue
            frame,audio,events=item
            work_started=time.perf_counter()
            jpeg=b'';h264=None;keyframe=False
            if any(not viewer.preserve_video for viewer in self.viewers.values()):
                try:success,encoded=await asyncio.to_thread(cv2.imencode,'.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,86])
                except cv2.error:success=False;encoded=None
                jpeg=encoded.tobytes() if success else b''
            if any(viewer.preserve_video for viewer in self.viewers.values()):
                force,self.force_keyframe=self.force_keyframe,False
                try:
                    if self.encoder is None:self.encoder=H264Encoder()
                    h264,keyframe=await asyncio.to_thread(self.encoder.encode,frame,self.sequence,force)
                except Exception:
                    logger.exception('H264 transport encoder failed')
                    for ws,viewer in list(self.viewers.items()):
                        if viewer.preserve_video:self.viewers.pop(ws,None);asyncio.create_task(ws.close(code=1011,message=b'H264 encoder unavailable'))
            control=None
            media=[(index,event) for index,event in events if event.get('dsh') and event.get('valid_samples',0)>0]
            if media:
                info=media[0][1]
                if info['generation']!=getattr(self.avatar,'_studio_generation',None) or info['runtime_epoch']!=getattr(self.avatar,'_dsh_runtime_epoch',None):
                    audio=np.zeros_like(audio)
                else:
                    ranges=[{'packet_seq':self.sequence,'packet_offset':index*320,'sample_start':event['sample_offset'],'sample_count':event['valid_samples']} for index,event in media]
                    data={key:info[key] for key in ('request_id','utterance_id','runtime_epoch','generation','valid_sample_count')}
                    data.update(transport_instance_id=self.transport_instance_id,ranges=ranges,final=any(event.get('sample_final') for _,event in media))
                    try:
                        from server.dsh_bridge import async_media
                        receipt=await async_media('media-map',data)
                        if info['generation']==getattr(self.avatar,'_studio_generation',None) and info['runtime_epoch']==getattr(self.avatar,'_dsh_runtime_epoch',None):
                            control={'type':'media.map','protocol':2,**data,'map_revision':receipt['map_revision']}
                        else:
                            audio=np.zeros_like(audio)
                    except Exception:
                        logger.warning('DSH media mapping not persisted; suppressing this utterance')
                        audio=np.zeros_like(audio)
                        self.avatar.flush_talk()
                        try:await async_media('failed',{'request_id':info['request_id']})
                        except Exception:pass
            audio_bytes=audio.tobytes()
            packet=struct.pack('<III',self.sequence,len(jpeg),16000)+jpeg+audio_bytes
            encoded_packet=struct.pack('<III',self.sequence,len(h264),16000)+h264+audio_bytes if h264 is not None else None
            self.sequence+=1;self.frames+=1
            for ws,viewer in list(self.viewers.items()):
                if viewer.preserve_video and viewer.needs_keyframe:
                    if not keyframe:continue
                    viewer.needs_keyframe=False
                if not viewer.put(encoded_packet if viewer.preserve_video else packet,control):
                    # A connection behind by five seconds must reconnect; never cut
                    # words out of queued PCM merely to keep its pictures current.
                    self.viewers.pop(ws,None)
                    asyncio.create_task(ws.close(code=1013,message=b'Viewing connection too slow; reconnect'))
            for _,event in events:self.avatar.notify(event)
            elapsed=time.perf_counter()-work_started
            if elapsed>.2:logger.warning('Media packet %s processing delayed %.3fs (mapped=%s)',self.sequence-1,elapsed,bool(media))
            due+=.04
            if due<time.perf_counter()-.2:due=time.perf_counter()
            await asyncio.sleep(max(.001,due-time.perf_counter()))
    async def handle(self,request):
        # JPEG is already compressed; per-message deflate wastes CPU for every viewer.
        ws=web.WebSocketResponse(heartbeat=20,max_msg_size=1024,compress=False);await ws.prepare(request)
        h264=request.query.get('codec')=='h264'
        packets=ViewerBuffer(preserve_video=h264);packets.needs_keyframe=h264;self.viewers[ws]=packets
        if h264:self.force_keyframe=True
        async def sender():
            while not ws.closed:
                item=await packets.get()
                if isinstance(item,dict):await asyncio.wait_for(ws.send_json(item),5)
                elif isinstance(item,tuple):
                    control,packet=item
                    await asyncio.wait_for(ws.send_json(control),5)
                    await asyncio.wait_for(ws.send_bytes(packet),5)
                else:await asyncio.wait_for(ws.send_bytes(item),5)
        task=asyncio.create_task(sender())
        try:
            async for message in ws:
                if message.type==web.WSMsgType.ERROR:break
                if h264 and message.type==web.WSMsgType.TEXT:
                    try:
                        if json.loads(message.data).get('type')=='video.keyframe':self.force_keyframe=True
                    except (ValueError,AttributeError):pass
        finally:
            self.viewers.pop(ws,None);task.cancel();await asyncio.gather(task,return_exceptions=True)
        return ws
    def cancel(self,barrier):
        with self.queue.mutex:self.queue.queue.clear()
        for viewer in self.viewers.values():viewer.clear({'type':'playback.cancel',**barrier})
    async def close(self):
        self.quit.set()
        for ws in list(self.viewers):await ws.close()
        self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
