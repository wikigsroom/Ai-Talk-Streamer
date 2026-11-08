"""An application-owned stop file requests normal cleanup, never a foreign PID."""
import asyncio
import os
from pathlib import Path
import re
import threading

from .common import AdmissionError, inside


def media_rehearsal_stops(root, candidate_id):
    if not re.fullmatch(r'issac-[0-9a-f]{12}-[0-9a-f]{8}',candidate_id):
        raise AdmissionError('FROZEN_MEDIA_CANDIDATE_REQUIRED')
    parent=inside(root,'state/issac-stream/stop-requests')
    return (parent/('media30-'+candidate_id+'.stop'),parent/('media30-'+candidate_id+'-voice.stop'))


def stop_path(root):
    value = os.environ.get('ISSAC_STOP_FILE')
    if not value:
        return None
    path = Path(value).resolve()
    parent = inside(root, 'state/issac-stream/stop-requests').resolve()
    if path.parent != parent or path.suffix != '.stop':
        raise AdmissionError('OWNED_STOP_FILE_SCOPE_REQUIRED')
    return path


def watch(root, callback):
    path = stop_path(root)
    if path is None:
        return
    def run():
        while not path.exists():
            threading.Event().wait(.2)
        callback()
    threading.Thread(target=run, daemon=True, name='owned-stop-request').start()


def aiohttp_shutdown(app, root):
    # A background task raising GracefulExit can interrupt cleanup itself.
    # The runner below owns the stop condition and awaits cleanup normally.
    app['issac_owned_stop_root']=Path(root).resolve()


def run_web(app,root,*,host,port):
    async def serve():
        from aiohttp import web
        runner=web.AppRunner(app,access_log=None,shutdown_timeout=35)
        try:
            await runner.setup()
            await web.TCPSite(runner,host,port).start()
            path=stop_path(root)
            while path is None or not path.exists():await asyncio.sleep(.2)
        finally:
            await runner.cleanup()
    asyncio.run(serve())
