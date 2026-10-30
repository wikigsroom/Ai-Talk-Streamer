"""Stage explicitly named source updates; validate each digest on the native GPU host."""
from pathlib import Path
import hashlib
import json
import sys
import urllib.parse
import urllib.request
import uuid

root = Path(__file__).resolve().parents[2]
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
commands = ["$ErrorActionPreference='Stop'", "$root='C:\\dev\\虚拟数字人直播\\naimei'"]
records = []
for name in sys.argv[1:]:
    relative = Path(name)
    source = (root / relative).resolve()
    if not source.is_relative_to(root) or relative.parts[0] not in {'web', 'backend', 'integration', 'scripts', 'assets'}:
        raise RuntimeError('SOURCE_SYNC_OUTSIDE_SCOPE')
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    boundary = '----NaimeiSource' + uuid.uuid4().hex
    body = b''
    for key, value in [('type', 'input'), ('subfolder', 'naimei-release'), ('overwrite', 'false')]:
        body += ('--' + boundary + '\r\nContent-Disposition: form-data; name="' + key + '"\r\n\r\n' + value + '\r\n').encode()
    body += ('--' + boundary + '\r\nContent-Disposition: form-data; name="image"; filename="' + digest[:16] + '-' + source.name + '"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + data
    body += ('\r\n--' + boundary + '--\r\n').encode()
    with http.open(urllib.request.Request('http://192.168.196.209:8188/upload/image', data=body,
                                         headers={'Content-Type': 'multipart/form-data; boundary=' + boundary}), timeout=30) as response:
        item = json.load(response)
    url = 'http://127.0.0.1:8188/view?' + urllib.parse.urlencode({'type': 'input', 'subfolder': item['subfolder'], 'filename': item['name']})
    target = relative.as_posix().replace('/', '\\')
    commands += ["$target=Join-Path $root '" + target + "'", "Invoke-WebRequest -UseBasicParsing -Uri '" + url + "' -OutFile $target",
                 "if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower() -ne '" + digest + "') {throw 'Naimei source checksum mismatch'}"]
    records.append({'path': relative.as_posix(), 'sha256': digest})
commands.append("@{updated=" + str(len(records)) + ";public_broadcast=$false}|ConvertTo-Json -Compress")
(root / 'operations/naimei-a01-a14-20261031/sync-review-files.ps1').write_text('\n'.join(commands), 'utf-8')
print(json.dumps(records))
