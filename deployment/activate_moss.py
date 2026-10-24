"""Install the MOSS LiveTalking adapter and select a registered reference voice."""
from pathlib import Path
import argparse
import ast
import datetime
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', choices=['v' + str(i).zfill(2) for i in range(1, 11)], default='v04')
    parser.add_argument('--batch-size', type=int, choices=(1, 2, 4, 8, 16), help='Optional MuseTalk batch size; preserves the existing value when omitted')
    args = parser.parse_args()
    live = ROOT / 'src/LiveTalking'
    settings = ROOT / 'configs/moss-live.json'
    config = json.loads((settings if settings.exists() else ROOT / 'configs/moss-live.example.json').read_text(encoding='utf-8'))
    for path in (ROOT / config['python'], ROOT / config['runtime_root'] / 'vendor',
                 ROOT / config['models_root'] / 'MOSS-TTSD-v1.0/config.json'):
        if not path.exists():
            raise RuntimeError('The configured native MOSS installation is missing: ' + str(path))
    catalog = json.loads((ROOT / 'configs/voices/female-a-v1.json').read_text(encoding='utf-8'))
    selected = next(item for item in catalog['voices'] if item['voice_id'] == args.voice and item['engine'] == 'MOSS')
    if not (ROOT / selected['reference']).is_file():
        raise RuntimeError('The registered reference WAV is missing')
    config.update(voice_id=args.voice, label=selected['label'])
    base = live / 'avatars/base_avatar.py'
    text = base.read_text(encoding='utf-8')
    if "'moss-ttsd': 'tts.moss'" not in text:
        marker = "'gpt-sovits': 'tts.sovits',"
        if marker not in text:
            raise RuntimeError('The pinned TTS registry was not found')
        text = text.replace(marker, marker + "\n            'moss-ttsd': 'tts.moss',", 1)
    changes = {base: text,
               live / 'tts/moss.py': (ROOT / 'integration/moss_tts.py').read_text(encoding='utf-8'),
               live / 'server/studio_routes.py': (ROOT / 'integration/studio_routes.py').read_text(encoding='utf-8'),
               live / 'server/isolated_inference.py': (ROOT / 'integration/isolated_inference.py').read_text(encoding='utf-8'),
               live / 'llm.py': (ROOT / 'integration/llm_channel.py').read_text(encoding='utf-8'),
               live / 'web/studio.js': (ROOT / 'web/studio.js').read_text(encoding='utf-8'),
               live / 'web/studio.html': (ROOT / 'web/studio.html').read_text(encoding='utf-8')}
    config_path = ROOT / 'configs/livetalking.yaml'
    options = json.loads(config_path.read_text(encoding='utf-8-sig'))
    options.update(tts='moss-ttsd', TTS_SERVER='http://127.0.0.1:9880', MOSS_VOICE_ID=args.voice,
                   REF_FILE=str(ROOT / selected['reference']), REF_TEXT=selected['reference_text'])
    if args.batch_size is not None:
        options['batch_size'] = args.batch_size
    changes.update({settings: json.dumps(config, ensure_ascii=False, indent=2) + '\n',
                    config_path: json.dumps(options, ensure_ascii=False, indent=2) + '\n'})
    backup = ROOT / '.setup/moss-live' / ('activate-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    for target, value in changes.items():
        if target.suffix == '.py':
            ast.parse(value, filename=str(target))
        if target.exists():
            saved = backup / target.relative_to(ROOT)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, saved)
        temporary = target.with_suffix(target.suffix + '.part')
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(value, encoding='utf-8', newline='\n')
        temporary.replace(target)
    record = {'engine': 'MOSS-TTSD-v1.0', 'voice_id': args.voice, 'label': selected['label'],
              'avatar_batch_size': options['batch_size'],
              'reference_sha256': hashlib.sha256((ROOT / selected['reference']).read_bytes()).hexdigest(),
              'restart_avatar_required': True, 'restart_tts_if_already_running_with_other_voice': True}
    result = ROOT / '.setup/moss-live/activation.json'
    result.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
