"""Use the installed remote4090 client; keep this task's evidence in naimei.

The shared device lock stays in the installed controller directory so other
sessions cannot operate this device concurrently. No credentials are copied.
"""
import importlib.util
from pathlib import Path
import sys

source = Path(r'C:\Users\carzy\.codex\skills\remote-4090\scripts\windows_mcp.py')
spec = importlib.util.spec_from_file_location('naimei_asset_remote', source)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
original_read = client.read_json
original_lock = client.device_lock
config = original_read(client.SKILL_ROOT / 'device.json')


def read(path):
    value = original_read(path)
    if Path(path).resolve() == (client.SKILL_ROOT / 'device.json').resolve():
        value['controller_root'] = str(Path(__file__).resolve().parent)
    return value


client.read_json = read
client.device_lock = lambda root, name: original_lock(Path(config['controller_root']), name)
sys.stdout.reconfigure(encoding='utf-8')
raise SystemExit(client.main())
