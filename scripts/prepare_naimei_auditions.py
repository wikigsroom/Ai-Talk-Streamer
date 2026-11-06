"""Generate a new audition take without overwriting the approved frozen audio."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import sys
import urllib.request
import uuid
import wave
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integration.naimei_voice_contract import load_profile, cache_matches, worker_matches
from integration.naimei_text import spoken_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    profile = load_profile(root)
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    text = '大家好，我是奶妹。今天也想陪你，慢慢聊一会儿。'
    records = []
    for voice in profile['voices']:
        url = 'http://127.0.0.1:' + ('9891' if voice['id'] == profile['default_voice_id'] else '9892')
        with http.open(url + '/health', timeout=5) as response:
            health = json.load(response)
        if not worker_matches(profile, health, voice['id']) or health.get('busy'):
            raise RuntimeError('APPROVED_VOICE_NOT_READY:' + voice['id'])
        rid = 'approved-audition-' + uuid.uuid4().hex
        request = urllib.request.Request(url + '/tts', data=json.dumps({
            'request_id': rid, 'text': text, 'voice_id': voice['id']}).encode(),
            headers={'Content-Type': 'application/json'})
        with http.open(request, timeout=180) as response:
            body = response.read()
            assert response.headers['X-TTS-Voice'] == voice['id']
            assert response.headers['X-TTS-Engine'] == voice['engine']
            assert response.headers['X-TTS-Reference-SHA256'] == voice['sha256']
        with http.open(url + '/metrics/' + rid, timeout=5) as response:
            metrics = json.load(response)
        if not cache_matches(metrics, voice, spoken_text(text)):
            raise RuntimeError('AUDITION_VOICE_BINDING_MISMATCH')
        with wave.open(io.BytesIO(body), 'rb') as stream:
            assert (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) == (24000, 1, 2)
            pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
        assert len(pcm) and np.isfinite(pcm).all() and np.sqrt(np.mean(pcm ** 2)) > .001 and np.abs(pcm).max() < .99
        target = root / voice['audition']
        if profile.get('voice_frozen'):
            target = root / profile['speech_asset_root'] / 'auditions' / (rid + '.wav')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        record = {**metrics, 'text': text, 'sha256': hashlib.sha256(body).hexdigest(),
                  'binding_and_pcm_verified': True, 'human_listening_accepted': False}
        target.with_suffix('.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), 'utf-8')
        records.append({'voice_id': voice['id'], 'audio_seconds': metrics['audio_seconds'],
                        'reference_sha256': metrics['reference_sha256'], 'path': target.relative_to(root).as_posix()})
    print(json.dumps({'auditions': records, 'cloud_inference_allowed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
