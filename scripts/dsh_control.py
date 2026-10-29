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


def owned_processes():
    """Match this exact server and root, including an old closing owner."""
    import psutil
    expected_server = str(ROOT/'backend/dsh-bridge/server.mjs').casefold()
    expected_root = str(ROOT).casefold()
    result = []
    for process in psutil.process_iter(['cmdline']):
        try:
            args = [str(arg).replace('/', '\\').casefold() for arg in (process.info['cmdline'] or [])]
            if expected_server in args and expected_root in args:
                result.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


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
        if owned_processes():
            raise RuntimeError('A project DSH owner is still starting or closing; stop it before restarting')
        import runpy
        runpy.run_path(str(ROOT/'scripts/deployment_target.py'))['validate_target'](ROOT)
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
                                       close_fds=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
        RECORD.write_text(json.dumps({'pid': process.pid, 'command': command, 'started': time.time()}, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'started': True, 'pid': process.pid, 'port': 3092})); return
    owned = owned_processes()
    if not owned:
        print(json.dumps({'stopped': True, 'already_stopped': True})); return
    # Graceful shutdown is refused while a broadcast is open. End it in the UI first.
    if status()['process_alive']:
        request = urllib.request.Request('http://127.0.0.1:3092/api/dsh/shutdown', data=b'{}',
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as reply:
            json.load(reply)
    import psutil
    _, alive = psutil.wait_procs(owned, timeout=30)
    # A closed HTTP port does not prove that the SQLite owner has exited.
    # After the graceful deadline, finish only those exact project processes.
    for process in alive:
        try: process.terminate()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(alive, timeout=10)
    if alive: raise RuntimeError('Project DSH owner has not exited; no replacement may start')
    print(json.dumps({'stopped': True, 'owned_processes': len(owned)}))


if __name__ == '__main__':
    main()
