"""Export a fixed allowlist of non-secret observations from an original delivery."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery-root', required=True, type=Path)
    args = parser.parse_args()
    delivery = args.delivery_root.resolve()
    out = ROOT / 'docs/evidence'
    out.mkdir(parents=True, exist_ok=True)

    def read(relative):
        path = delivery / relative
        raw = path.read_bytes()
        return json.loads(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()

    def save(name, value, digest):
        value['evidence_scope'] = 'curated reference-deployment observation; private paths and channel settings excluded'
        value['source_record_sha256'] = digest
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    data, digest = read('outputs/vertical/browser/acceptance.json')
    value = {k: data[k] for k in ('ok', 'at', 'checks')}
    if 'recheck' in data:
        value['recheck'] = {k: data['recheck'][k] for k in ('at', 'reason')}
    save('browser-acceptance.json', value, digest)

    data, digest = read('outputs/vertical/browser/cloud-conversation.json')
    save('cloud-conversation.json', {k: data[k] for k in
         ('ok', 'at', 'mode', 'configured', 'first_reply_ms', 'first_speech_ms', 'reply')}, digest)

    data, digest = read('outputs/vertical/review/material-provenance.json')
    save('material-provenance.json', {k: data[k] for k in ('ok', 'at', 'count', 'seconds', 'multiplier', 'items')}, digest)

    data, digest = read('outputs/vertical/scenarios/result.json')
    value = {k: data[k] for k in ('ok', 'at', 'text_mode', 'scene', 'avatar_id')}
    allowed = ('id', 'title', 'description', 'ok', 'events', 'test_script_sha256', 'media', 'seconds',
               'bytes', 'sha256', 'audio_rms', 'audio_peak', 'silence_window_seconds', 'silence_rms')
    value['items'] = [{k: item[k] for k in allowed if k in item} for item in data['items']]
    value['seconds'] = round(sum(i['seconds'] for i in value['items']), 2)
    value['hash_scope'] = 'original 720x1280 OBS recordings, not resized documentation previews'
    save('scenarios.json', value, digest)

    data, digest = read('outputs/vertical/tour/result.json')
    clips = [{k: item[k] for k in ('id', 'title', 'active_seconds', 'speaking')} for item in data['clips']]
    save('motion-tour.json', {'ok': data['ok'], 'at': data['at'], 'count': len(clips), 'clips': clips,
         'media': data['media'], 'speaking_screenshots': sum(bool(c['speaking']) for c in clips),
         'quiet_screenshots': sum(not c['speaking'] for c in clips)}, digest)

    packages = {}
    source_digests = {}
    allowed = ('ok', 'at', 'bytes', 'archive_bytes', 'archive_sha256', 'entries', 'video_clips', 'video_seconds',
               'independent_pose_images', 'crc_verified', 'all_media_checksums_match', 'count', 'seconds',
               'all_video_hashes_verified', 'all_video_formats_verified')
    for name in ('material', 'scenario'):
        data, digest = read(f'outputs/vertical/review/{name}-package-verification.json')
        packages[name] = {k: data[k] for k in allowed if k in data}
        source_digests[name] = digest
    save('package-verification.json', {'ok': all(p['ok'] for p in packages.values()), 'packages': packages}, source_digests)

    data, digest = read('remote_snapshot/.setup/delivery-snapshot.json')
    value = {k: data[k] for k in ('ok', 'at', 'ram_gib', 'ram_used_gib', 'runtime_platform',
                                 'material_count', 'material_seconds', 'motion_clips', 'gpu', 'independent_pose_images')}
    value['scope'] = 'final idle live snapshot after generation models were released; not a peak or minimum requirement'
    save('runtime-snapshot.json', value, digest)
    data, digest = read('outputs/vertical/review/resource-summary.json')
    save('resource-summary.json', {k: data[k] for k in ('samples', 'maximum_sampled_gpu_used_mib',
         'maximum_sampled_ram_used_gib', 'interval_seconds', 'last')}, digest)
    print(json.dumps({'ok': True, 'files': 8}))

if __name__ == '__main__':
    main()
