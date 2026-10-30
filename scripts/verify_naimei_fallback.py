"""Exercise the resident native F5 fallback against Naimei's own reference."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import urllib.request
import uuid
import wave
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
root = args.root.resolve()
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for port in (9891, 9892):
    with http.open(f'http://127.0.0.1:{port}/health', timeout=5) as response:
        health = json.load(response)
    if not health.get('ready') or health.get('busy'):
        raise RuntimeError('VOICE_SERVICE_NOT_QUIET_AND_READY')
request_id = 'naimei-fallback-' + uuid.uuid4().hex
text = '你好，我是奶妹。这是备用声音的本地检查。'
request = urllib.request.Request('http://127.0.0.1:9892/tts',
    data=json.dumps({'request_id': request_id, 'text': text, 'voice_id': 'NMV01'}).encode(),
    headers={'Content-Type': 'application/json'})
with http.open(request, timeout=180) as response:
    body = response.read()
    engine = response.headers.get('X-TTS-Engine')
with http.open('http://127.0.0.1:9892/metrics/' + request_id, timeout=5) as response:
    metrics = json.load(response)
profile = json.loads((root / 'assets/naimei/live-v1/voice/profile.json').read_text('utf-8'))
reference = next(x for x in profile['voices'] if x['id'] == 'NMV01')
assert metrics['reference_sha256'] == reference['sha256'] and metrics['voice_id'] == 'NMV01'
with wave.open(io.BytesIO(body), 'rb') as stream:
    assert (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) == (24000, 1, 2)
    pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
assert len(pcm) and np.sqrt(np.mean(pcm ** 2)) > .001 and np.abs(pcm).max() < .99
folder = root / 'assets/naimei/live-v1/voice/fallback'
folder.mkdir(exist_ok=True)
(folder / 'NMV01-f5-check.wav').write_bytes(body)
result = {**metrics, 'text': text, 'engine_header': engine, 'sha256': hashlib.sha256(body).hexdigest(),
          'binding_and_pcm_verified': True, 'human_listening_accepted': False}
(folder / 'NMV01-f5-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
print(json.dumps(result, ensure_ascii=False))
