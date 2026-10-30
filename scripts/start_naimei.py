"""Start only the isolated native Naimei services, with the branch/GPU guard."""
from pathlib import Path
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from deployment_target import validate_target

ROOT = Path(__file__).resolve().parents[1]
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def health(port, path='/health'):
    try:
        with HTTP.open(f'http://127.0.0.1:{port}' + path, timeout=3) as response:
            return json.load(response)
    except (OSError, ValueError):
        return {}


def wait_ready(port, timeout, path='/health'):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = health(port, path)
        if value.get('ready') or value.get('health', {}).get('dsh_ready'):
            return value
        if value.get('error'):
            raise RuntimeError(str(value['error']))
        time.sleep(2)
    raise TimeoutError(f'Naimei service {port} is still preparing; inspect its own logs before retrying')


def occupied(port):
    with socket.socket() as probe:
        return probe.connect_ex(('127.0.0.1', port)) == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--voice-only', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    result = validate_target(root, expected_target='naimei-rtx4090')
    if os.name != 'nt':
        raise RuntimeError('NAIMEI_REQUIRES_NATIVE_WINDOWS')
    config = json.loads((root / 'configs/naimei/live-runtime.json').read_text('utf-8'))
    shared = Path(config['shared_installation_root'])
    python = shared / 'runtime/tts-benchmark/omnivoice/Scripts/python.exe'
    f5_python = shared / 'runtime/tts-benchmark/f5/Scripts/python.exe'
    studio_python = shared / 'runtime/livetalking/Scripts/python.exe'
    node = Path('C:/Program Files/nodejs/node.exe')
    state = root / 'state/naimei/processes'
    state.mkdir(parents=True, exist_ok=True)
    registry = state / 'services.json'
    previous = json.loads(registry.read_text('utf-8')) if registry.exists() else {}
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1',
               AVATAR_CHARACTER_ID='naimei', STREAM_PROJECT_ROOT=str(root), DSH_DISABLE_TELEMETRY='1')

    def start(name, command, port, path='/health', timeout=240):
        if occupied(port):
            value = health(port, path)
            owned = previous.get(name, {}).get('root') == str(root)
            if not owned or value.get('character_id', value.get('character', {}).get('id')) != 'naimei':
                # DSH exposes identity inside its health object.
                if not (owned and value.get('health', {}).get('character_id') == 'naimei'):
                    raise RuntimeError(f'Port {port} is occupied by an unverified service; nothing was stopped')
        else:
            with (state / (name + '.stdout.log')).open('ab') as out, (state / (name + '.stderr.log')).open('ab') as err:
                child = subprocess.Popen([str(x) for x in command], cwd=root, env=env,
                    stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=0x08000000)
            previous[name] = {'pid': child.pid, 'port': port, 'root': str(root), 'started_at': time.time()}
            registry.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding='utf-8')
        return wait_ready(port, timeout, path)

    start('voice-primary', [python, '-X', 'utf8', '-B', '-m', 'integration.naimei_voice_worker',
          '--root', root, '--shared-root', shared, '--port', '9891'], 9891, timeout=900)
    start('voice-fallback', [f5_python, '-X', 'utf8', '-B', '-m', 'integration.naimei_voice_worker',
          '--root', root, '--shared-root', shared, '--engine', 'F5-TTS-v1', '--port', '9892'], 9892, timeout=240)
    if args.voice_only:
        print(json.dumps({**result, 'voices_ready': True}, ensure_ascii=False))
        return
    # Existing FlashHead is reused; this launcher never restarts it.
    engine = health(8030)
    if not engine.get('ready') or engine.get('size') != 512:
        raise RuntimeError('The existing 512x512 FlashHead service must be ready before starting Naimei')
    start('studio', [studio_python, '-X', 'utf8', '-B', '-m', 'integration.naimei_studio', '--root', root], 8052)
    start('bridge', [node, root / 'backend/dsh-bridge/server.mjs', root, 'tools/dsh',
          'configs/naimei/bridge-policy.json', 'http://127.0.0.1:8052'], 3094, '/api/dsh/status')
    print(json.dumps({**result, 'ready': True, 'studio_url': 'http://192.168.196.209:8052/',
          'public_broadcast_started': False, 'cloud_inference_allowed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
