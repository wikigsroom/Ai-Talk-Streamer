"""Install DSH media hooks without changing the selected GPU engine or its config."""
from pathlib import Path
import ast
import datetime
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    live = ROOT / 'src/LiveTalking'
    if not (live / 'app.py').exists():
        raise RuntimeError('An existing prepared LiveTalking installation is required')
    backup = ROOT / '.setup/dsh-media-backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    mappings = [(ROOT / 'integration' / name, live / 'server' / name) for name in
                ('studio_routes.py', 'dsh_bridge.py', 'local_broadcast.py', 'stream_encoder.py', 'viewer_buffer.py')]
    mappings += [(ROOT / 'integration/moss_tts.py', live / 'tts/moss.py'),
                 (ROOT / 'integration/obs.html', live / 'web/obs.html')]
    mappings += [(source, live / 'web' / source.name) for source in (ROOT / 'web').iterdir() if source.is_file()]
    receipts = []
    for source, target in mappings:
        data = source.read_bytes()
        if target.suffix == '.py':
            ast.parse(data.decode('utf-8-sig'), filename=str(target))
        if target.exists():
            old = backup / target.relative_to(ROOT); old.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, old)
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        receipts.append({'path': str(target.relative_to(ROOT)), 'sha256': hashlib.sha256(data).hexdigest()})
    (ROOT / 'configs/dsh-enabled.json').write_text(json.dumps({'enabled': True, 'media_protocol': 2}), encoding='utf-8')
    record = {'ok': True, 'backup': str(backup.relative_to(ROOT)), 'files': receipts, 'engine_config_changed': False}
    (ROOT / '.setup/dsh-media-install.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'files': len(receipts), 'backup': str(backup.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
