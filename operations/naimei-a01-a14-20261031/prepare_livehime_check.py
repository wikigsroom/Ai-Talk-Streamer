"""Prepare the native client and silent preview, without starting any platform output."""
from pathlib import Path
import json
import urllib.request
import urllib.error

root = Path(__file__).resolve().parents[2]
out = root / 'output/review/naimei-live-v1/browser'
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
result = {'public_broadcast_started': False, 'account_login_performed': False}
try:
    request = urllib.request.Request('http://127.0.0.1:8952/api/dsh/platforms/bilibili/prepare', data=b'{}', headers={'Content-Type': 'application/json'})
    with http.open(request, timeout=95) as response:
        result['prepare'] = json.load(response)
    with http.open('http://127.0.0.1:8952/api/dsh/platforms/bilibili/preflight', timeout=15) as response:
        result['preflight'] = json.load(response)
except urllib.error.HTTPError as error:
    result['failure'] = {'status': error.code, 'body': error.read().decode('utf-8', 'replace')}
finally:
    (out / 'native-livehime-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
print(json.dumps(result, ensure_ascii=False))
