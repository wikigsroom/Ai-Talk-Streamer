"""Native Isaac process bridge; does not edit the executable or persistent data."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import threading
import time
import asyncio
import frida
import psutil
from native_ipc import atomic_json

ROOT = Path(__file__).resolve().parent
TAIPEI = timezone(timedelta(hours=8))

def rpc(script, method, *args, timeout=4):
    async def invoke():
        return await asyncio.wait_for(getattr(script.exports_async,method)(*args),timeout)
    return asyncio.run(invoke())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--spawn', action='store_true')
    parser.add_argument('--pid', type=int)
    args = parser.parse_args()
    install = json.loads((ROOT/'game-install.json').read_text(encoding='utf-8'))
    (ROOT/'screenshots').mkdir(exist_ok=True)
    folder = ROOT/'logs'/('satan_'+datetime.now(TAIPEI).strftime('%Y%m%d_%H%M%S'))
    folder.mkdir(parents=True, exist_ok=False)
    game_exe = Path(install['game_root'])/install['executable']
    if args.spawn:
        if any((p.info['name'] or '').lower() == 'isaac-ng.exe' for p in psutil.process_iter(['name'])):
            raise RuntimeError('A game is already running; no second game started')
        pid = frida.spawn([str(game_exe), *install['launch_arguments']], cwd=install['game_root'])
    else:
        pid = args.pid
        if not pid or Path(psutil.Process(pid).exe()) != game_exe:
            raise RuntimeError('Selected game process identity is required')
    session = frida.attach(pid)
    script = session.create_script((ROOT/'native_bridge.js').read_text(encoding='utf-8'))
    captured = {}
    def on_message(message, data):
        payload=message.get('payload',{})
        if message.get('type')=='send' and payload.get('event')=='native_frame' and data:
            from PIL import Image
            identity=payload['id']
            if len(identity)==32 and all(c in '0123456789abcdef' for c in identity):
                output=ROOT/'screenshots'/('native-frame-'+identity+'.png')
                Image.frombytes('RGBA',(payload['width'],payload['height']),data).transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert('RGB').save(output)
                captured[identity]=str(output)
        with (folder/'bridge-events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'at':datetime.now(TAIPEI).isoformat(), **message})+'\n')
    script.on('message', on_message)
    script.load()
    if args.spawn: frida.resume(pid)
    record = {'game_pid':pid, 'bridge_pid':__import__('os').getpid(), 'log_directory':str(folder),
              'game_created_at':psutil.Process(pid).create_time(), 'mode':'native_process_input'}
    (ROOT/'native-bridge-process.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record),flush=True)
    request_path = ROOT/'native-request.json'
    response_path = ROOT/'native-response.json'
    try: last_id=json.loads(request_path.read_text(encoding='utf-8')).get('id')
    except (OSError,json.JSONDecodeError): last_id=None
    try:
        while psutil.pid_exists(pid):
            if request_path.exists():
                try: request = json.loads(request_path.read_text(encoding='utf-8'))
                except (OSError,json.JSONDecodeError): time.sleep(.05); continue
                if request.get('id') != last_id:
                    last_id = request['id']
                    try:
                        if request.get('op') == 'reload_bridge':
                            script.unload()
                            script = session.create_script((ROOT/'native_bridge.js').read_text(encoding='utf-8'))
                            script.on('message', on_message)
                            script.load()
                            value = rpc(script,'status')
                        else:
                            if request.get('op') == 'status': value = rpc(script,'status')
                            elif request.get('op') == 'key': value = rpc(script,'key',request['name'], request['hwnd'])
                            elif request.get('op') == 'progress': value = rpc(script,'progress')
                            elif request.get('op') == 'capture':
                                value=rpc(script,'capture',last_id)
                                deadline=time.monotonic()+3
                                while last_id not in captured and time.monotonic()<deadline: time.sleep(.01)
                                value['path']=captured.pop(last_id,None)
                            else: value = rpc(script,'evaluate',request['source'])
                        response = {'id':last_id,'ok':True,'result':value}
                    except Exception as exc: response = {'id':last_id,'ok':False,'error':str(exc)}
                    atomic_json(response_path,response)
            time.sleep(.05)
    finally:
        session.detach()

if __name__ == '__main__': main()
