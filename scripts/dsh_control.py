"""Start/stop only this project's native DSH process; never touch GPU services."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / '.setup/dsh-process.json'


def status():
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:3092/health', timeout=3) as reply:
            return json.load(reply)
    except OSError:
        return {'process_alive': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    if args.action == 'status':
        print(json.dumps(status(), ensure_ascii=False)); return
    if args.action == 'start':
        if status()['process_alive']:
            raise RuntimeError('DSH is already running; no duplicate was started')
        node = ROOT / 'tools/node/node-v24.22.1-win-x64/node.exe'
        command = [str(node), str(ROOT / 'backend/dsh-bridge/server.mjs'), str(ROOT)]
        pointer = ROOT / 'configs/dsh-active-policy.json'
        if pointer.exists():
            policy_file = json.loads(pointer.read_text(encoding='utf-8'))['policy_file']
            target = (ROOT / policy_file).resolve()
            if not target.is_relative_to(ROOT):
                raise RuntimeError('Active policy must remain inside the project')
            command += ['tools/dsh', str(target)]
        (ROOT / 'logs').mkdir(exist_ok=True)
        env = dict(os.environ, STREAM_PROJECT_ROOT=str(ROOT), STREAM_LIVE_MODE='1')
        with (ROOT / 'logs/dsh.stdout.log').open('a', encoding='utf-8') as stdout, (ROOT / 'logs/dsh.stderr.log').open('a', encoding='utf-8') as stderr:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
        RECORD.write_text(json.dumps({'pid': process.pid, 'command': command, 'started': time.time()}, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'started': True, 'pid': process.pid, 'port': 3092})); return
    if not status()['process_alive']:
        print(json.dumps({'stopped': True, 'already_stopped': True})); return
    # Graceful shutdown is refused while a broadcast is open. End it in the UI first.
    request = urllib.request.Request('http://127.0.0.1:3092/api/dsh/shutdown', data=b'{}',
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as reply:
        print(reply.read().decode('utf-8'))


if __name__ == '__main__':
    main()
