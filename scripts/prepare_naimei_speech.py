"""Build and measure local phonetic tests and fixed programme cues."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import time
import urllib.request
import wave
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration.naimei_voice_contract import load_profile, cache_matches
from integration.naimei_text import spoken_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:9891')
    args = parser.parse_args()
    root = args.root.resolve()
    pack = root / 'assets/naimei/live-v1'
    profile = load_profile(root)
    speech_root = root / profile.get('speech_asset_root', 'assets/naimei/live-v1/voice')
    voice = next(v for v in profile['voices'] if v['id'] == profile['default_voice_id'])
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    tests = json.loads((pack / 'speech-tests.json').read_text('utf-8'))
    cues = json.loads((pack / 'programme-cues.json').read_text('utf-8'))
    results = []
    for item in tests + cues:
        aid = item['id']
        folder = speech_root / ('tests' if item in tests else 'cues')
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (aid + '.wav')
        metrics_path = folder / (aid + '.json')
        if target.exists() and metrics_path.exists():
            cached = json.loads(metrics_path.read_text('utf-8'))
            if cache_matches(cached, voice, spoken_text(item['text'])) and hashlib.sha256(target.read_bytes()).hexdigest() == cached.get('sha256'):
                results.append(cached)
                continue
        rid = 'asset-' + aid
        request = urllib.request.Request(args.url + '/tts', data=json.dumps({
            'text': item['text'], 'request_id': rid, 'voice_id': voice['id']}).encode(),
            headers={'Content-Type': 'application/json'})
        started = time.monotonic()
        with http.open(request, timeout=180) as response:
            body = response.read()
            engine = response.headers['X-TTS-Engine']
        with http.open(args.url + '/metrics/' + rid, timeout=10) as response:
            metrics = json.load(response)
        if not cache_matches(metrics, voice, spoken_text(item['text'])) or engine != voice['engine']:
            raise RuntimeError('UNAPPROVED_SPEECH_ASSET:' + aid)
        with wave.open(io.BytesIO(body)) as stream:
            rate, channels, width = stream.getframerate(), stream.getnchannels(), stream.getsampwidth()
            pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
        if (rate, channels, width) != (24000, 1, 2) or not len(pcm) or not np.isfinite(pcm).all():
            raise RuntimeError('INVALID_SPEECH_ASSET:' + aid)
        rms = float(np.sqrt(np.mean(pcm**2)))
        peak = float(np.max(np.abs(pcm)))
        if rms < .001 or peak > .99:
            raise RuntimeError('SILENT_OR_CLIPPED_SPEECH:' + aid)
        target.write_bytes(body)
        record = {**metrics, 'asset_id': aid, 'path': target.relative_to(root).as_posix(),
            'text': item['text'], 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'rms_dbfs': float(20 * np.log10(max(rms, 1e-12))), 'peak_dbfs': float(20 * np.log10(max(peak, 1e-12))),
            'clipped_samples': int((np.abs(pcm) >= .999).sum()), 'wall_seconds_with_http': time.monotonic() - started,
            'listening_review': 'pending', 'mouth_review': 'pending'}
        metrics_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        lines = []
        def stamp(sample):
            value = round(sample / 16)
            hours, rem = divmod(value, 3600000); minutes, rem = divmod(rem, 60000); seconds, ms = divmod(rem, 1000)
            return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'
        for index, part in enumerate(metrics['captions']):
            lines.extend([str(index + 1), stamp(part['sample_start']) + ' --> ' + stamp(part['sample_end']), part['text'], ''])
        target.with_suffix('.srt').write_text('\n'.join(lines), encoding='utf-8')
        results.append(record)
        status = {'completed': len(results), 'total': len(tests) + len(cues), 'last_asset': aid}
        (speech_root / 'preparation-status.json').write_text(json.dumps(status), encoding='utf-8')
        print(json.dumps(status), flush=True)
    report = {'character_id': 'naimei', 'voice_id': voice['id'], 'engine': voice['engine'],
        'reference_sha256': voice['sha256'],
        'test_count': len(tests), 'programme_cues': len(cues), 'assets': results,
        'new_model_weight_bytes': 0, 'cloud_inference_allowed': False, 'listening_acceptance': False}
    (speech_root / 'speech-library.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'complete': True, 'audio_assets': len(results)}), flush=True)


if __name__ == '__main__':
    main()
