"""Start the controller's native relay without leaving a terminal window open."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import time
import urllib.request

root = Path(__file__).resolve().parents[1]
state = root / 'state/naimei/relay'
config = json.loads((state / 'config.json').read_text('utf-8'))
url = 'http://127.0.0.1:' + str(config['port'])
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def status():
    try:
        with http.open(url + '/_bridge/status', timeout=2) as response:
            value = json.load(response)
        if value.get('character_id') != 'naimei':
            raise RuntimeError('PORT_OWNED_BY_ANOTHER_SERVICE')
        return value
    except urllib.error.URLError:
        return None


value = status()
if value is None:
    node = shutil.which('node') or str(Path(r'C:\Users\carzy\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'))
    if os.name != 'nt' or not Path(node).is_file():
        raise RuntimeError('NATIVE_WINDOWS_NODE_REQUIRED')
    with (state / 'stdout.log').open('ab') as out, (state / 'stderr.log').open('ab') as err:
        child = subprocess.Popen([node, str(root / 'scripts/naimei-lan-relay.cjs')], cwd=root,
            stdin=subprocess.DEVNULL, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(20):
        if child.poll() is not None:
            raise RuntimeError('NAIMEI_RELAY_EXITED_SEE_OWN_LOG')
        value = status()
        if value:
            break
        time.sleep(.25)
    if not value:
        raise RuntimeError('NAIMEI_RELAY_START_TIMEOUT')
print(json.dumps({'url': url + '/', **value}, ensure_ascii=False))
