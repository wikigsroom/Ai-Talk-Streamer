"""Start the native studio without overlapping large model-loading peaks."""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import webbrowser
from launch import port_open, start_service
from native_operation import operation

ROOT = Path(__file__).resolve().parents[1]


class StudioStartError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def start(progress=None):
    with operation(ROOT,'start-studio'):
        return _start(progress)


def _start(progress=None):
    mark = progress or (lambda stage: None)
    mark('studio_guard')
    from deployment_target import validate_target
    validate_target(ROOT)
    config = json.loads((ROOT / 'configs/livetalking.yaml').read_text(encoding='utf-8-sig'))
    moss = config.get('tts') == 'moss-ttsd'
    resident = config.get('tts') == 'resident-local'
    if (moss or resident) and port_open(9880) and not port_open(8010):
        raise StudioStartError('STUDIO_AVATAR_FIRST_REQUIRED')
    # MuseTalk has a large FP32-to-FP16 conversion peak. Return its startup
    # allocator cache before loading MOSS alongside the final FP16 renderer.
    services = [('avatar', 8010), ('tts', 9880)] if moss or resident else [('tts', 9880), ('avatar', 8010)]
    new_processes = []
    def ensure_starting_alive():
        if any(process.poll() is not None for process in new_processes):
            raise StudioStartError('STUDIO_NEW_SERVICE_EXITED')
    for name, port in services:
        process = None
        if not port_open(port):
            mark('studio_spawn_' + name)
            process = start_service(name)
            new_processes.append(process)
        # Importing CUDA libraries and reading the full 10,000-frame bank from
        # a cold Windows filesystem can exceed three minutes. Keep startup
        # serialized; a timeout must never trigger a duplicate avatar process.
        mark('studio_wait_' + name)
        for attempt in range(900 if name == 'avatar' else 180):
            ensure_starting_alive()
            if port_open(port):
                break
            time.sleep(1)
        else:
            raise StudioStartError('STUDIO_' + name.upper() + '_PORT_TIMEOUT')
    if resident:
        mark('studio_verify_resident_tts')
        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic()+360
        while time.monotonic()<deadline:
            ensure_starting_alive()
            try:
                with http.open('http://127.0.0.1:9880/health',timeout=5) as response:
                    current = json.load(response)
                if current.get('error') and not current.get('initializing'):
                    raise StudioStartError('STUDIO_RESIDENT_TTS_WORKER_FAILED')
                if current.get('ready') and all(current.get('workers',{}).get(v,{}).get('ready') for v in ('O07','F07')):
                    if current.get('service')!='resident-tts' or current.get('reference_sha256')!=config.get('TTS_REFERENCE_SHA256'):
                        raise StudioStartError('STUDIO_RESIDENT_TTS_IDENTITY_MISMATCH')
                    break
            except (urllib.error.URLError,TimeoutError):
                pass
            time.sleep(1)
        else:
            raise StudioStartError('STUDIO_RESIDENT_TTS_READY_TIMEOUT')
    if moss:
        mark('studio_verify_moss')
        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            ensure_starting_alive()
            try:
                with http.open('http://127.0.0.1:9880/health', timeout=5) as response:
                    state = json.load(response)
            except (urllib.error.URLError, TimeoutError):
                time.sleep(1)
                continue
            if state.get('error'):
                raise StudioStartError('STUDIO_MOSS_WORKER_FAILED')
            if state.get('ready'):
                if state.get('engine') != 'MOSS-TTSD-v1.0' or state.get('voice_id') != config.get('MOSS_VOICE_ID', 'v04'):
                    raise StudioStartError('STUDIO_MOSS_IDENTITY_MISMATCH')
                break
            time.sleep(1)
        else:
            raise StudioStartError('STUDIO_MOSS_READY_TIMEOUT')
    mark('studio_ready')
    print('Studio is ready: http://127.0.0.1:8010/\nRemote access: http://<your-host>:8010/')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    start()
    if not args.no_browser:
        webbrowser.open('http://127.0.0.1:8010/')


if __name__ == '__main__':
    main()
