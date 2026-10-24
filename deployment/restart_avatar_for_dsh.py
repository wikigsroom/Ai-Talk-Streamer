"""Restart verified project media, preserving the tested MuseTalk/MOSS load order."""
from pathlib import Path
import argparse
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    import psutil
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ordered-media', action='store_true', help='Restart registered MOSS too, then load avatar before MOSS')
    options = parser.parse_args()
    sys.path.insert(0, str(ROOT / 'scripts'))
    from launch import port_open, start_service, stop_services
    if port_open(3092):
        import urllib.request
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with client.open('http://127.0.0.1:3092/api/dsh/status', timeout=5) as response:
            if json.load(response).get('broadcast'):
                raise RuntimeError('End the active broadcast before restarting project media')
    config = json.loads((ROOT / 'configs/livetalking.yaml').read_text(encoding='utf-8-sig'))
    moss_running = config.get('tts') == 'moss-ttsd' and port_open(9880)
    if moss_running and not options.ordered_media:
        raise RuntimeError('Resident MOSS requires --ordered-media to preserve the validated GPU loading order')
    if moss_running:
        stop_services(only='tts')
        if port_open(9880):
            raise RuntimeError('Registered MOSS did not stop; no avatar process was changed')
    target = (ROOT / 'src/LiveTalking/app.py').resolve()
    listeners = {row.pid for row in psutil.net_connections('tcp') if row.laddr and row.laddr.port == 8010 and row.status == psutil.CONN_LISTEN}
    stopped = []
    for pid in listeners:
        process = psutil.Process(pid)
        command = process.cmdline()
        if not any(Path(arg).resolve() == target for arg in command if arg.lower().endswith('.py')):
            raise RuntimeError('Port 8010 belongs to an unrecognized application; no process was stopped')
        owned = []
        for child in process.children(recursive=True) + [process]:
            if Path(child.exe()).resolve() == Path(r'C:\Windows\System32\conhost.exe').resolve():
                continue
            if not Path(child.exe()).resolve().is_relative_to(ROOT):
                raise RuntimeError('Avatar tree contains an external executable; inspect before restarting')
            owned.append(child)
        for child in reversed(owned):
            try: child.terminate(); stopped.append(child.pid)
            except psutil.NoSuchProcess: pass
        _, alive = psutil.wait_procs(owned, timeout=5)
        for child in alive:
            try: child.kill()
            except psutil.NoSuchProcess: pass
        psutil.wait_procs(alive, timeout=5)
    if options.ordered_media:
        from start_studio import start
        start()
    else:
        start_service('avatar', minimum=0)
    print(json.dumps({'restarted_avatar': True, 'stopped_owned_pids': stopped, 'ordered_media': options.ordered_media}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'restart_error': type(error).__name__, 'message': str(error)}, ensure_ascii=False), flush=True)
        raise SystemExit(1)
