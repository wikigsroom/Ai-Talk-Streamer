"""Start the native studio without overlapping large model-loading peaks."""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import webbrowser
from launch import port_open, start_service

ROOT = Path(__file__).resolve().parents[1]


def start():
    from deployment_target import validate_target
    validate_target(ROOT)
    config = json.loads((ROOT / 'configs/livetalking.yaml').read_text(encoding='utf-8-sig'))
    moss = config.get('tts') == 'moss-ttsd'
    resident = config.get('tts') == 'resident-local'
    if (moss or resident) and port_open(9880) and not port_open(8010):
        raise RuntimeError('Stop both project services first: MuseTalk must initialize before the MOSS model loads')
    # MuseTalk has a large FP32-to-FP16 conversion peak. Return its startup
    # allocator cache before loading MOSS alongside the final FP16 renderer.
    services = [('avatar', 8010), ('tts', 9880)] if moss or resident else [('tts', 9880), ('avatar', 8010)]
    for name, port in services:
        if not port_open(port):
            start_service(name)
        # Importing CUDA libraries and reading the full 10,000-frame bank from
        # a cold Windows filesystem can exceed three minutes. Keep startup
        # serialized; a timeout must never trigger a duplicate avatar process.
        for attempt in range(900 if name == 'avatar' else 180):
            if port_open(port):
                break
            time.sleep(1)
        else:
            raise RuntimeError(name + ' did not become ready; inspect project logs')
    if resident:
        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic()+360
        while time.monotonic()<deadline:
            try:
                with http.open('http://127.0.0.1:9880/health',timeout=5) as response:
                    current = json.load(response)
                if current.get('error') and not current.get('initializing'):
                    raise RuntimeError('O07/F07 startup failed; inspect logs/resident-tts.runtime.stderr.log')
                if current.get('ready') and all(current.get('workers',{}).get(v,{}).get('ready') for v in ('O07','F07')):
                    if current.get('service')!='resident-tts' or current.get('reference_sha256')!=config.get('TTS_REFERENCE_SHA256'):
                        raise RuntimeError('Running speech service does not match the approved voice pair')
                    break
            except (urllib.error.URLError,TimeoutError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError('O07/F07 models did not become ready within six minutes')
    if moss:
        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                with http.open('http://127.0.0.1:9880/health', timeout=5) as response:
                    state = json.load(response)
            except (urllib.error.URLError, TimeoutError):
                time.sleep(1)
                continue
            if state.get('error'):
                raise RuntimeError('MOSS failed to load; inspect logs/moss.runtime.stderr.log')
            if state.get('ready'):
                if state.get('engine') != 'MOSS-TTSD-v1.0' or state.get('voice_id') != config.get('MOSS_VOICE_ID', 'v04'):
                    raise RuntimeError('The running speech service does not match the selected MOSS engine and voice')
                break
            time.sleep(1)
        else:
            raise RuntimeError('MOSS model did not finish loading within four minutes')
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
