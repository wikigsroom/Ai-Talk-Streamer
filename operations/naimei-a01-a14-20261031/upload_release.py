from pathlib import Path
import hashlib
import json
import re
import urllib.parse
import urllib.request
import uuid

root = Path(__file__).resolve().parents[2]
folder = root / 'output/derived/naimei-live-v1/transfer'
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
results = {}
for filename in ['naimei-source.zip', 'install_naimei.py']:
    data = (folder / filename).read_bytes()
    upload_name = hashlib.sha256(data).hexdigest()[:16] + '-' + filename
    boundary = '----NaimeiRelease' + uuid.uuid4().hex
    body = b''
    for key, value in [('type', 'input'), ('subfolder', 'naimei-release'), ('overwrite', 'false')]:
        body += ('--' + boundary + '\r\nContent-Disposition: form-data; name="' + key + '"\r\n\r\n' + value + '\r\n').encode()
    body += ('--' + boundary + '\r\nContent-Disposition: form-data; name="image"; filename="' + upload_name + '"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + data
    body += ('\r\n--' + boundary + '--\r\n').encode()
    request = urllib.request.Request('http://192.168.196.209:8188/upload/image', data=body,
        headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with http.open(request, timeout=180) as response:
        result = json.load(response)
    results[filename] = 'http://127.0.0.1:8188/view?' + urllib.parse.urlencode({'type': 'input', 'subfolder': result['subfolder'], 'filename': result['name']})
(folder / 'upload-receipts.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
command = (root / 'operations/naimei-a01-a14-20261031/install-4090.ps1').read_text('utf-8')
release = json.loads((folder / 'release.json').read_text('utf-8'))
command = re.sub(r"--sha256 '[a-f0-9]{64}'", "--sha256 '" + release['sha256'] + "'", command)
for filename, url in results.items():
    command = command.replace('http://192.168.196.87:8951/' + filename, url)
(root / 'operations/naimei-a01-a14-20261031/install-4090-local-transfer.ps1').write_text(command, encoding='utf-8')
print(json.dumps({'uploaded': list(results), 'bytes': (folder / 'naimei-source.zip').stat().st_size}))
