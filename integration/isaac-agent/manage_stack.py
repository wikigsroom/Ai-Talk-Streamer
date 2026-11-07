"""Native Windows lifecycle for this isolated DSH build. Start never arms gameplay."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import psutil

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from stack_control import native_state, pause, arm
from native_request import request
from build_native_controller import build


def read(path):
    try: return json.loads((ROOT/path).read_text(encoding='utf8'))
    except (OSError, ValueError): return {}


def get(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/status', timeout=1) as response: return json.load(response)
    except (OSError, ValueError): return None


def match(pid, script, cwd=ROOT):
    try:
        p = psutil.Process(pid)
        arguments = p.cmdline()
        ok = Path(p.cwd()) == cwd and any(Path(a).name == script for a in arguments)
        if script == 'bin.js':
            ok = ok and str(ROOT/'dsh-host/node_modules/@deepseek-ai/dsh/lib/bin.js') in arguments and '--profile' in arguments and 'isaac' in arguments
        return p if ok else None
    except (psutil.Error, OSError, TypeError): return None


def hidden(script, args=()):
    stamp = str(time.time_ns())
    folder = ROOT/'logs/services'; folder.mkdir(parents=True, exist_ok=True)
    arguments = [sys.executable, '-B', '-X', 'utf8', script, *map(str, args)]
    # Give the child real file handles, not PowerShell's asynchronously drained
    # redirect pipes. A short-lived PowerShell pipe owner can block Node's
    # event loop at its first console write after readiness.
    with (folder/(script+'-'+stamp+'.out.log')).open('ab',buffering=0) as out, (folder/(script+'-'+stamp+'.err.log')).open('ab',buffering=0) as err:
        child=subprocess.Popen(arguments,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                               close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    pid = child.pid
    return {'pid': pid, 'created': psutil.Process(pid).create_time(), 'script': script}


def wait_for(check, seconds=30):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        result = check()
        if result: return result
        time.sleep(.2)
    raise RuntimeError('Service readiness timed out; inspect logs/services, no gameplay was armed')


def verify_owner(port, script, cwd=ROOT):
    listeners = [x for x in psutil.net_connections(kind='tcp') if x.status == psutil.CONN_LISTEN and x.laddr.port == port]
    if listeners and not all(match(x.pid, script, cwd) for x in listeners):
        raise RuntimeError(f'Port {port} belongs to another process; it was left untouched')


def game():
    install = read('game-install.json'); expected = Path(install['game_root'])/install['executable']
    found = []
    for p in psutil.process_iter(['name']):
        if (p.info['name'] or '').lower() == expected.name.lower():
            if Path(p.exe()) != expected: raise RuntimeError('Another Isaac installation is running')
            found.append(p)
    if len(found)>1: raise RuntimeError('More than one game is running')
    return found[0] if found else None


def attach():
    p = game()
    if not p: return {'attached': False, 'reason': 'game_not_running_use_launch_game.py_then_slot_3'}
    record = read('native-bridge-process.json')
    if not (record.get('game_pid') == p.pid and record.get('game_created_at') == p.create_time()
            and match(record.get('bridge_pid'), 'native_bridge.py')):
        hidden('native_bridge.py', ['--pid', p.pid])
        wait_for(lambda: read('native-bridge-process.json').get('game_pid') == p.pid
                 and match(read('native-bridge-process.json').get('bridge_pid'), 'native_bridge.py'), 15)
    # The slot/progress gate is checked again at arm; this operation only installs normal-input callbacks.
    state = native_state()
    if not state.get('players') or state.get('hp', 0)<=0: return {'attached': True, 'installed': False, 'reason': 'enter_living_slot_3_run_first'}
    pause()
    result = request(build().read_text(encoding='utf8'), timeout=6)
    request('return _G.__NativeIsaacController:NativeResume()', timeout=4)
    return {'attached': True, 'installed': result, 'paused': native_state()['paused']}


def start():
    verify_owner(9532, 'run_strategy.py')
    verify_owner(9528, 'run_strategy.py')
    verify_owner(9529, 'run_strategy.py')
    verify_owner(9533, 'bin.js', ROOT/'dsh-host')
    records = read('logs/services/managed.json')
    (ROOT/'logs/services').mkdir(parents=True, exist_ok=True)
    def save(): (ROOT/'logs/services/managed.json').write_text(json.dumps(records, indent=2), encoding='utf8')
    if not get(9532): records['controller'] = hidden('run_strategy.py'); save()
    wait_for(lambda: get(9532))
    native = attach()
    if not get(9533):
        starting = any(match(p.pid, 'bin.js', ROOT/'dsh-host') for p in psutil.process_iter(['name']) if p.info['name']=='node.exe')
        if not starting: records['dsh_launcher'] = hidden('start_dsh.py'); save()
    def dsh_ready():
        result=get(9533)
        if result and result.get('ready'):return result
        launcher=records.get('dsh_launcher',{})
        if launcher and not match(launcher.get('pid'),'start_dsh.py') and not any(
                match(p.pid,'bin.js',ROOT/'dsh-host') for p in psutil.process_iter(['name']) if p.info['name']=='node.exe'):
            raise RuntimeError('DSH exited before readiness; inspect logs/services. Game remains paused and unarmed')
    wait_for(dsh_ready, 300)
    return {'started': True, 'model': get(9533).get('model'), 'native': native, 'gameplay_armed': False}


def stop_process(pid, script, cwd=ROOT):
    p = match(pid, script, cwd)
    if p:
        p.terminate()
        try: p.wait(timeout=5)
        except psutil.TimeoutExpired: raise RuntimeError(f'Verified process {pid} did not stop; no unrelated process was touched')


def stop(controller_only=False):
    if game(): pause()  # Stable engine ACK is required before stopping a live controller.
    record = read('strategy-process.json')
    stop_process(record.get('pid'), 'run_strategy.py')
    if not controller_only:
        host = read('logs/dsh/host-ready.json') | (get(9533) or {})
        stop_process(host.get('pid'), 'bin.js', ROOT/'dsh-host')
        for p in psutil.process_iter(['name']):
            if p.info['name']=='node.exe': stop_process(p.pid, 'bin.js', ROOT/'dsh-host')
        records = read('logs/services/managed.json')
        launcher = records.get('dsh_launcher', {})
        stop_process(launcher.get('pid'), 'start_dsh.py')
        stop_process(read('native-bridge-process.json').get('bridge_pid'), 'native_bridge.py')
    return {'stopped': True, 'controller_only': controller_only, 'game_left_paused': bool(game())}


def status():
    c, d = get(9532), get(9533)
    value = {'controller': c and {k:c.get(k) for k in ('enabled','live','connected','frame','pending','executing','state_age_ms')},
             'dsh': d and {k:d.get(k) for k in ('pid','ready','model','automatic','busy','turns','lastError')},
             'monitor': 'http://127.0.0.1:9532/'}
    if game() and match(read('native-bridge-process.json').get('bridge_pid'), 'native_bridge.py'):
        value['native'] = native_state(); value['progress'] = request(op='progress', timeout=4)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start','status','pause','arm','arm-local','stop','restart','restart-controller'])
    args=parser.parse_args()
    os.chdir(ROOT)
    # Operator lifecycle commands are serialized, independently of native RPC's own lock.
    import msvcrt
    with (ROOT/'.stack-operation.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError: raise RuntimeError('Another lifecycle operation is running')
        try:
            if args.action=='start': value=start()
            elif args.action=='status': value=status()
            elif args.action=='pause': value=pause()
            elif args.action=='arm': value=arm()
            elif args.action=='arm-local': value=arm(local_only=True)
            elif args.action=='stop': value=stop()
            else:
                stop(controller_only=args.action=='restart-controller');value=start()
            print(json.dumps(value, ensure_ascii=False))
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__=='__main__': main()
