"""Fetch only the reviewed voice pack from its native-host transfer receipt."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
result_file = Path(sys.argv[1])
raw = json.loads(result_file.read_text('utf-8'))['structuredContent']['result']
receipt, _ = json.JSONDecoder().raw_decode(raw.removeprefix('Response: ').lstrip())
if not receipt.get('complete') or receipt.get('failure'):
    raise RuntimeError('APPROVED_VOICE_ASSETS_NOT_COMPLETE')
if not receipt['url'].startswith('http://192.168.196.209:8188/view?'):
    raise RuntimeError('UNEXPECTED_VOICE_TRANSFER_HOST')
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with http.open(receipt['url'], timeout=45) as response:
    data = response.read()
if len(data) != receipt['bytes'] or hashlib.sha256(data).hexdigest() != receipt['sha256']:
    raise RuntimeError('VOICE_TRANSFER_ARCHIVE_MISMATCH')
with zipfile.ZipFile(io.BytesIO(data)) as bundle:
    records = json.loads(bundle.read('_voice-transfer-manifest.json'))
    allowed = {r['path'] for r in records} | {'_voice-transfer-manifest.json'}
    if len(records) != receipt['files'] or set(bundle.namelist()) != allowed:
        raise RuntimeError('VOICE_TRANSFER_MANIFEST_MISMATCH')
    verified = []
    for item in records:
        relative = PurePosixPath(item['path'])
        target = (ROOT / relative).resolve()
        if '..' in relative.parts or not target.is_relative_to(ROOT / 'assets/naimei/live-v1/voice'):
            raise RuntimeError('VOICE_TRANSFER_OUTSIDE_PACK')
        content = bundle.read(item['path'])
        if len(content) != item['bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
            raise RuntimeError('VOICE_ASSET_CHECKSUM_MISMATCH')
        verified.append((target, content))
    for target, content in verified:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
out = ROOT / 'output/review/naimei-approved-voice-20261031'
(out / 'voice-transfer.json').write_text(json.dumps({k:v for k,v in receipt.items() if k!='url'},indent=2),'utf-8')
print(json.dumps({'verified_voice_files': len(records), 'bytes': len(data)}))
