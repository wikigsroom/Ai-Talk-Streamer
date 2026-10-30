"""Validate the A01-A14 pack and export a reviewable, versioned content index."""
from pathlib import Path
import csv
import hashlib
import json
import wave
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
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
    profile = read('voice/profile.json')
    assert profile['character_id'] == 'naimei' and profile['default_voice_id'] == 'NMV01'
    assert len(profile['voices']) == 3
    for item in profile['voices']:
        verified(item['reference'], item['sha256'])
    speech = read('voice/speech-library.json')['assets']
    assert len(speech) == 25
    for item in speech:
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
              'rejected_actions_preserved': len(pack['actions']) - len(enabled), 'voice_references': 3,
              'speech_wavs': len(speech), 'speech_seconds': sum(x['audio_seconds'] for x in speech),
              'speech_clipped_samples': 0, 'audio': audio, 'additional_model_weights_bytes': 0,
              'integrity_passed': True, 'live_speech_quality_accepted': False,
              'voice_user_audition_confirmed': False, 'note': 'Integrity and asset completeness do not imply lip/fang or pronunciation acceptance.'}
    (PACK / 'integrity-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
