"""Validate the A01-A14 pack and export a reviewable, versioned content index."""
from pathlib import Path
import csv
import hashlib
import json
import wave
import sys
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integration.naimei_voice_contract import load_profile, cache_matches
from integration.naimei_text import spoken_text
PACK = ROOT / 'assets/naimei/live-v1'


def read(name):
    return json.loads((PACK / name).read_text('utf-8'))


def verified(relative, expected):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(PACK) or not path.is_file():
        raise RuntimeError('ASSET_OUTSIDE_PACK_OR_MISSING:' + relative)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError('ASSET_CHECKSUM_MISMATCH:' + relative)
    return path


def main():
    pack = read('pack.json')
    assert pack['character_id'] == 'naimei' and pack['native_size'] == [512, 512] and pack['fps'] == 25
    assert Image.open(PACK / 'reference/closed.png').size == (512, 512)
    enabled = [x for x in pack['actions'] if x['runtime_enabled']]
    assert len(enabled) == 15 and len(pack['actions']) == 20
    assert len({x['id'] for x in pack['actions']}) == len(pack['actions'])
    for item in pack['actions']:
        verified(item['path'], item['sha256'])
        assert item['size'] == [512, 512] and item['fps'] == 25
        assert item['silent_only'] and not item['may_overlay_arbitrary_speech']
        if item['runtime_enabled']:
            assert item['review_status'] == 'silent_motion_visual_review_passed'
    profile = load_profile(ROOT)
    primary = next(v for v in profile['voices'] if v['id'] == 'O07')
    assert len(profile['voices']) == 2
    for item in profile['voices']:
        verified(item['reference'], item['sha256'])
        audition_path = ROOT / item['audition']
        audition = json.loads(audition_path.with_suffix('.json').read_text('utf-8'))
        verified(item['audition'], audition['sha256'])
        assert cache_matches(audition, item, spoken_text(audition['text']))
        assert audition['voice_id'] in {'O07', 'F07'} and '奶妹' in audition['spoken_text']
        assert not audition['human_listening_accepted']
        with wave.open(str(audition_path), 'rb') as stream:
            assert (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) == (24000, 1, 2)
            assert stream.getnframes() > 2400
    assert not list((PACK / 'voice').glob('NMV*'))
    speech = read('voice/speech-library.json')['assets']
    assert len(speech) == 25
    for item in speech:
        assert cache_matches(item, primary, spoken_text(item['text']))
        path = verified(item['path'], item['sha256'])
        assert path.with_suffix('.json').is_file() and path.with_suffix('.srt').is_file()
        with wave.open(str(path), 'rb') as stream:
            assert (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) == (24000, 1, 2)
            samples = stream.getnframes()
            pcm = np.frombuffer(stream.readframes(samples), dtype='<i2').astype(np.float32) / 32768
        assert abs(samples / 24000 - item['audio_seconds']) < 1 / 24000
        assert np.sqrt(np.mean(pcm ** 2)) > .001 and np.abs(pcm).max() < .99
        captions = item['captions']
        assert captions and captions[0]['sample_start'] == 0
        assert all(a['sample_end'] <= b['sample_start'] for a, b in zip(captions, captions[1:]))
        assert abs(captions[-1]['sample_end'] - samples * 2 / 3) <= 2
    for scene in ('main', 'backup'):
        assert Image.open(PACK / 'scenes' / (scene + '.jpg')).width > 0
    layouts = read('layouts.json')
    for name in ('portrait', 'landscape'):
        width, height = layouts[name]['canvas']
        for rect in ('character', 'title', 'captions'):
            x, y, w, h = layouts[name][rect]
            assert min(x, y, w, h) >= 0 and x + w <= width and y + h <= height
    audio = []
    for path in sorted((PACK / 'audio').glob('*.wav')):
        with wave.open(str(path), 'rb') as stream:
            data = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
            assert np.isfinite(data).all() and np.abs(data).max() < .99 and np.sqrt(np.mean(data ** 2)) > .0001
            audio.append({'path': path.relative_to(ROOT).as_posix(), 'channels': stream.getnchannels(), 'sample_rate': stream.getframerate()})
    assert len(audio) == 4
    fallback = read('voice/fallback/F07-f5-check.json')
    fallback_path = verified('assets/naimei/live-v1/voice/fallback/F07-f5-check.wav', fallback['sha256'])
    assert fallback['binding_and_pcm_verified'] and not fallback['human_listening_accepted']
    assert cache_matches(fallback, next(v for v in profile['voices'] if v['id'] == 'F07'), spoken_text(fallback['text']))
    with wave.open(str(fallback_path), 'rb') as stream:
        assert (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) == (24000, 1, 2)
        assert stream.getnframes() > 2400
    failover = read('voice/fallback/O07-to-F07-check.json')
    verified('assets/naimei/live-v1/voice/fallback/O07-to-F07-check.wav', failover['sha256'])
    assert cache_matches(failover, next(v for v in profile['voices'] if v['id'] == 'F07'), spoken_text(failover['text']))
    assert failover['busy_primary_blocks_fallback'] and failover['fallback_inference_real']
    assert len(list((PACK / 'programme').glob('*.png'))) == 10
    records = []
    for path in sorted(PACK.rglob('*')):
        if not path.is_file() or path.name in {'content-index.csv', 'integrity-review.json'}:
            continue
        records.append({'角色': '奶妹', '版本': 'live-v1/O01', '分类': path.relative_to(PACK).parts[0],
                        '文件': path.relative_to(ROOT).as_posix(), '字节': path.stat().st_size,
                        'SHA256': hashlib.sha256(path.read_bytes()).hexdigest()})
    with (PACK / 'content-index.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    result = {'character_id': 'naimei', 'source_branch': 'naimei', 'scope': 'A01-A14',
              'files': len(records), 'bytes': sum(x['字节'] for x in records), 'enabled_silent_actions': len(enabled),
              'rejected_actions_preserved': len(pack['actions']) - len(enabled), 'voice_references': 1,
              'voice_ids': [v['id'] for v in profile['voices']], 'voice_auditions': 2,
              'voice_reference_sha256': profile['reference_sha256'],
              'speech_wavs': len(speech), 'speech_seconds': sum(x['audio_seconds'] for x in speech),
              'fallback_speech_wavs': 2, 'fallback_speech_seconds': fallback['audio_seconds'] + failover['audio_seconds'],
              'speech_clipped_samples': 0, 'audio': audio, 'additional_model_weights_bytes': 0,
              'integrity_passed': True, 'live_speech_quality_accepted': False,
              'voice_user_audition_confirmed': profile['user_audition_confirmed'],
              'naimei_voice_user_audition_confirmed': profile['naimei_audition_confirmed'],
              'note': 'Original voice choice is retained. Integrity does not imply new role pronunciation or lip/fang acceptance.'}
    (PACK / 'integrity-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
