"""One NCM01 worker, using retained OmniVoice and graceful owned shutdown."""
import argparse
import asyncio
from pathlib import Path
import threading
import time

from aiohttp import web
from integration.naimei_voice_worker import VoiceWorker
from integration.naimei_text import spoken_text
from .common import AdmissionError, Audit, FileLease, inside
from .deployment import require_candidate
from .shutdown import stop_path


async def serve(root):
    require_candidate(root)
    owner=FileLease(inside(root,'state/issac-stream/voice.lock')).acquire()
    audit=Audit(inside(root,'state/issac-stream/voice-events.jsonl'))
    stopping=threading.Event()
    initialization={'stage':'waiting_for_existing_gpu_tasks','error':None}
    worker=VoiceWorker(root,root,'OmniVoice')
    if worker.voice_id!='NCM01':raise AdmissionError('FROZEN_NCM01_REQUIRED')
    app=web.Application(client_max_size=32*1024)
    async def health(_):return web.json_response({**worker.health(),'initialization':initialization})
    async def tts(request):
        body=await request.json();rid=body.get('request_id')
        if not isinstance(rid,str) or not 1<=len(rid)<=160 or body.get('voice_id')!='NCM01':
            return web.json_response({'error':'CURRENT_NCM01_REQUEST_REQUIRED'},status=400)
        if not worker.ready or worker.active:return web.json_response({'error':'VOICE_NOT_IDLE_READY'},status=409)
        try:
            audio,metrics=await asyncio.to_thread(worker.synthesize,spoken_text(body.get('text','')),rid,'NCM01')
            return web.Response(body=audio,content_type='audio/wav',headers={'X-TTS-Engine':'OmniVoice',
                'X-TTS-Voice':'NCM01','X-TTS-Character':'naimei','X-TTS-Reference-SHA256':metrics['reference_sha256']})
        except (RuntimeError,ValueError):return web.json_response({'error':'NCM01_GENERATION_REJECTED'},status=503)
    async def cancel(request):
        body=await request.json()
        with worker.guard:worker.cancelled.add(str(body.get('request_id','')))
        return web.json_response({'accepted':True})
    async def metrics(request):
        result=next((x for x in reversed(worker.recent) if x['request_id']==request.match_info['id']),None)
        return web.json_response(result or {'error':'NOT_FOUND'},status=200 if result else 404)
    app.add_routes([web.get('/health',health),web.post('/tts',tts),web.post('/cancel',cancel),web.get('/metrics/{id}',metrics)])
    runner=web.AppRunner(app,access_log=None,shutdown_timeout=40)
    def initialize():
        from .resources import wait_for_capacity
        try:
            wait_for_capacity(stopping,11000,lambda row:audit.append('waiting_for_capacity',observed=row))
            initialization['stage']='loading_ncm01'
            worker.initialize()
            initialization['stage']='ready' if worker.ready else 'failed'
        except Exception as error:
            initialization.update(stage='cancelled' if stopping.is_set() else 'failed',error=type(error).__name__)
            audit.append('initialization_failed',private_diagnostic=str(error)[:1500])
    thread=threading.Thread(target=initialize,daemon=True,name='issac-ncm01-initialize')
    try:
        await runner.setup();await web.TCPSite(runner,'127.0.0.1',9893).start();thread.start()
        stop=stop_path(root)
        while stop is None or not stop.exists():await asyncio.sleep(.2)
        stopping.set()
        with worker.guard:
            if worker.active:worker.cancelled.add(worker.active)
        deadline=time.monotonic()+35
        while worker.active and time.monotonic()<deadline:await asyncio.sleep(.1)
        if worker.active:raise AdmissionError('VOICE_COMPUTATION_CLEANUP_NOT_CONFIRMED')
        await asyncio.to_thread(thread.join,35)
        if thread.is_alive():raise AdmissionError('VOICE_INITIALIZATION_CLEANUP_NOT_CONFIRMED')
    finally:
        stopping.set()
        await runner.cleanup();owner.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    asyncio.run(serve(args.root.resolve()))
