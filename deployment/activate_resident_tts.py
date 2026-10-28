"""Select the approved O07/F07 pair without changing memory, avatar or platform state."""
from pathlib import Path
import argparse, ast, datetime, hashlib, json, shutil, socket

ROOT = Path(__file__).resolve().parents[1]


def activate():
    for port in (8010, 9880, 9881, 9882):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('Stop this project media/TTS first; configuration is not changed while serving')
    config = json.loads((ROOT/'configs/resident-tts.example.json').read_text('utf8'))
    required = [ROOT/config['reference_audio'], ROOT/config['warmup_audio']]
    for value in config['voices'].values():
        required += [ROOT/value[k] for k in ('python', 'source', 'model')]
    required.append(ROOT/config['voices']['F07']['vocoder'])
    for path in required:
        if not path.exists():
            raise RuntimeError('Required local asset missing: '+str(path))
    if hashlib.sha256((ROOT/config['reference_audio']).read_bytes()).hexdigest() != config['reference_sha256']:
        raise RuntimeError('O07 reference checksum mismatch')
    live = ROOT/'src/LiveTalking'
    base = live/'avatars/base_avatar.py'
    source = base.read_text('utf8')
    if "'resident-local': 'tts.resident_local'" not in source:
        marker = "'gpt-sovits': 'tts.sovits',"
        if marker not in source:
            raise RuntimeError('Pinned LiveTalking TTS registry missing')
        source = source.replace(marker, marker+"\n            'resident-local': 'tts.resident_local',", 1)
    options_path = ROOT/'configs/livetalking.yaml'
    options = json.loads(options_path.read_text('utf-8-sig'))
    options.update(tts='resident-local', TTS_SERVER='http://127.0.0.1:9880', TTS_VOICE_ID='O07',
        TTS_REFERENCE_SHA256=config['reference_sha256'], REF_FILE=str(ROOT/config['reference_audio']),
        REF_TEXT=config['reference_text'])
    options.pop('MOSS_VOICE_ID', None)
    changes = {base: source, live/'tts/resident_local.py': (ROOT/'integration/resident_tts.py').read_text('utf8'),
        live/'server/studio_routes.py': (ROOT/'integration/studio_routes.py').read_text('utf8'),
        live/'server/isolated_inference.py': (ROOT/'integration/isolated_inference.py').read_text('utf8'),
        live/'web/studio.js': (ROOT/'web/studio.js').read_text('utf8'),
        live/'web/studio.html': (ROOT/'web/studio.html').read_text('utf8'),
        options_path: json.dumps(options, ensure_ascii=False, indent=2),
        ROOT/'configs/resident-tts.json': json.dumps(config, ensure_ascii=False, indent=2),
        ROOT/'configs/tts-selection.private.json': json.dumps({'voice_id': 'O07', 'release': config['release']})}
    backup = ROOT/'.setup/resident-tts/backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for target, text in changes.items():
        if target.suffix == '.py':
            ast.parse(text, filename=str(target))
        if target.exists():
            saved = backup/target.relative_to(ROOT)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix+'.part')
        temp.write_text(text+'\n', encoding='utf8', newline='\n')
        temp.replace(target)
    receipt = {'release': config['release'], 'voice_id': 'O07', 'fallback_voice_id': 'F07',
        'reference_sha256': config['reference_sha256'], 'avatar_id': options['avatar_id'],
        'batch_size': options['batch_size'], 'fps': options['fps'], 'backup': str(backup.relative_to(ROOT)),
        'memory_path_changed': False, 'platform_config_changed': False, 'services_started': False}
    p = ROOT/'.setup/resident-tts/activation.json'
    p.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    activate()
