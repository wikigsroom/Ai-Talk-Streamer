"""Owned real HTTP/SQLite console with a fixture application; never MC, models or broadcast."""
from pathlib import Path
import json
import os
import shutil
import random
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_mc_application_console import FixtureApplication, RuntimeService, ConsoleHost, ConsoleServer

application = FixtureApplication()
mode = os.environ.get('MC_RUNTIME_BROWSER_MODE', 'normal')
if mode == 'broadcast':
    application.broadcast = True
    application.running = True
delay = None
if mode == 'slow-start':
    application.release.clear()
    original = application.start
    def delayed_start(timeout=1800):
        global delay
        delay = threading.Timer(2, application.release.set)
        delay.start()
        return original(timeout)
    application.start = delayed_start

with tempfile.TemporaryDirectory(prefix='mc-runtime-browser-原生 ') as temporary:
    root = Path(temporary)
    for name in ('mc-runtime.html', 'mc-runtime.js', 'mc-runtime.css', 'mc-control.css'):
        destination = root / 'web' / name; destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'web' / name, destination)
    runtime = RuntimeService(root, {'root': str(root), 'source': 'browser-fixture-only'}, lambda: None,
        application_factory=lambda root, check: application,
        preflight=lambda: {'ok': False, 'checks': [{'name': 'device', 'ok': False, 'code': 'MC_DEVICE_UNAVAILABLE'},
                                                  {'name': 'source', 'ok': True}]})
    host = ConsoleHost(root, runtime)
    # Windows may allocate port 5060 for port=0; Chromium deliberately blocks it.
    # Bind an available high port directly, without weakening browser port checks.
    for candidate in random.SystemRandom().sample(range(30000, 60000), 32):
        try:
            server = ConsoleServer(('127.0.0.1', candidate), host)
            break
        except OSError:
            continue
    else:
        host.close()
        raise RuntimeError('No owned browser fixture port available')
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02})
    thread.start()
    print(json.dumps({'ready': True, 'base': 'http://127.0.0.1:' + str(server.server_port)}), flush=True)
    try:
        sys.stdin.readline()
    finally:
        application.release.set()
        if delay is not None:
            delay.cancel(); delay.join(timeout=5)
        server.shutdown(); server.server_close(); thread.join(timeout=10)
        host.close()
        proof = {'fixture_only': True, 'mode': mode, 'calls': application.calls,
                 'application_running': application.running, 'server_closed': not thread.is_alive(),
                 'worker_closed': not runtime.worker.is_alive(), 'real_minecraft': False,
                 'real_models': False, 'public_broadcast': False}
        destination = Path(os.environ['MC_RUNTIME_BROWSER_PROOF'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', 'utf-8')
