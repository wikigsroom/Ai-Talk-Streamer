"""An application-owned stop file requests normal cleanup, never a foreign PID."""
import asyncio
import os
from pathlib import Path
import threading

from .common import AdmissionError, inside


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
    async def start(application):
        path = stop_path(root)
        if path is None:
            return
        async def poll():
            from aiohttp import web
            while not path.exists():
                await asyncio.sleep(.2)
            raise web.GracefulExit()
        application['issac_stop_task'] = asyncio.create_task(poll())
    async def cleanup(application):
        task = application.get('issac_stop_task')
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    app.on_startup.append(start)
    app.on_cleanup.append(cleanup)
