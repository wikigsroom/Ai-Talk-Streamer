"""Manage one local avatar broadcast for the studio and OBS."""
import asyncio
from aiohttp import web
from server.rtc_manager import RTCManager
from server.session_manager import session_manager
from server.local_broadcast import LocalBroadcast

class StudioRTCManager(RTCManager):
    def __init__(self,opt):
        super().__init__(opt);self.lock=asyncio.Lock();self.broadcast=None;self.sessionid='studio';self.max_viewers=6
    async def ensure_session(self):
        async with self.lock:
            if not session_manager.has_session(self.sessionid):
                await session_manager.create_session({},sessionid=self.sessionid)
                self.broadcast=LocalBroadcast(session_manager.get_session(self.sessionid))
        return self.sessionid
    async def handle_local_stream(self,request):
        if self.broadcast and len(self.broadcast.viewers)>=self.max_viewers:return web.json_response({'error':'观看连接已满。'},status=409)
        await self.ensure_session();return await self.broadcast.handle(request)
    async def handle_offer(self,request):
        return web.json_response({'msg':'请使用演播台或 OBS 页面连接本地音视频。'},status=409)
    async def shutdown(self):
        if self.broadcast:await self.broadcast.close()
