"""Paced local JPEG/PCM broadcasting, sharing one native avatar render."""
import asyncio,queue,struct,threading,time
import cv2,numpy as np
from aiohttp import web
from utils.logger import logger
from server.viewer_buffer import ViewerBuffer

class LocalBroadcast:
    def __init__(self,avatar):
        self.avatar=avatar;self.queue=queue.Queue(maxsize=32);self.viewers={};self.quit=threading.Event()
        self.pending=None;self.audio=[];self.events=[];self.sequence=0;self.started=time.perf_counter();self.frames=0
        avatar.output._player=self
        cv2.setNumThreads(1)
        self.thread=threading.Thread(target=avatar.render,args=(self.quit,),name='local-avatar-render',daemon=True)
        self.thread.start();self.task=asyncio.create_task(self.pump())
    def push_video(self,frame):self.pending=frame.copy();self.audio=[];self.events=[]
    def push_audio(self,frame,eventpoint=None):
        self.audio.append(np.asarray(frame,dtype=np.int16))
        if eventpoint:self.events.append(eventpoint)
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
            success,encoded=await asyncio.to_thread(cv2.imencode,'.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,86])
            if not success:continue
            jpeg=encoded.tobytes();packet=struct.pack('<III',self.sequence,len(jpeg),16000)+jpeg+audio.tobytes()
            self.sequence+=1;self.frames+=1
            for ws,viewer in list(self.viewers.items()):
                if not viewer.put(packet):
                    # A connection behind by five seconds must reconnect; never cut
                    # words out of queued PCM merely to keep its pictures current.
                    self.viewers.pop(ws,None)
                    asyncio.create_task(ws.close(code=1013,message=b'Viewing connection too slow; reconnect'))
            for event in events:self.avatar.notify(event)
            due+=.04
            if due<time.perf_counter()-.2:due=time.perf_counter()
            await asyncio.sleep(max(.001,due-time.perf_counter()))
    async def handle(self,request):
        # JPEG is already compressed; per-message deflate wastes CPU for every viewer.
        ws=web.WebSocketResponse(heartbeat=20,max_msg_size=1024,compress=False);await ws.prepare(request)
        packets=ViewerBuffer();self.viewers[ws]=packets
        async def sender():
            while not ws.closed:
                packet=await packets.get();await asyncio.wait_for(ws.send_bytes(packet),5)
        task=asyncio.create_task(sender())
        try:
            async for message in ws:
                if message.type==web.WSMsgType.ERROR:break
        finally:
            self.viewers.pop(ws,None);task.cancel();await asyncio.gather(task,return_exceptions=True)
        return ws
    async def close(self):
        self.quit.set()
        for ws in list(self.viewers):await ws.close()
        self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
