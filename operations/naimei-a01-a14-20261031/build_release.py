"""Package this actual naimei working tree with a per-file manifest, without private state."""
from pathlib import Path
import hashlib
import json
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/derived/naimei-live-v1/transfer'
OUT.mkdir(parents=True, exist_ok=True)
branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
if branch != 'naimei':
    raise RuntimeError('NAIMEI_BRANCH_REQUIRED')
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
files = set()
for folder in ['backend', 'web', 'docs/dsh-humanity/examples', 'assets/naimei/live-v1']:
    for path in (ROOT / folder).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.log'}:
            files.add(path.relative_to(ROOT).as_posix())
for folder in ['configs/naimei']:
    files.update(x.relative_to(ROOT).as_posix() for x in (ROOT / folder).glob('*.json'))
files.update(['integration/character_identity.py', 'integration/naimei_studio.py', 'integration/naimei_media.py',
    'integration/naimei_voice_worker.py', 'integration/naimei_text.py', 'integration/naimei_lan_client.py',
    'scripts/deployment_target.py', 'scripts/start_naimei.py', 'scripts/install_naimei.py', 'scripts/prepare_naimei_speech.py',
    'scripts/validate_naimei_assets.py', 'scripts/verify_naimei_fallback.py',
    'scripts/reload_naimei_services.ps1',
    'scripts/link_naimei_livehime.ps1',
    'scripts/prepare_bilibili_livehime.py', 'scripts/prepare_douyin_companion.py',
    'configs/active-character.json', 'configs/deployment-target.json', 'configs/deployment-targets.json',
    'configs/releases/current.json', 'configs/releases/naimei-o01-live-v1.json',
    'configs/characters/naimei.json', 'configs/dsh-active-policy.json'])
files.add('docs/naimei/A01-A14实施与直播接入.md')
files.add('docs/naimei/A01-A14验收与阻塞报告.md')
files.add('docs/naimei/直播接入任务清单.csv')
records = []
archive = OUT / 'naimei-source.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as bundle:
    for name in sorted(files):
        if '.private.' in name or name.endswith(('.env', '.key', '.pem')):
            raise RuntimeError('PRIVATE_FILE_IN_SOURCE_SET')
        data = (ROOT / name).read_bytes()
        records.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        bundle.writestr(name, data)
    manifest = {'schema_version': 1, 'branch': branch, 'target': 'naimei-rtx4090', 'source_commit': commit,
        'source_worktree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT, text=True).strip()), 'built_at': time.time(), 'files': records,
        'scope': 'A01-A14 plus native local live integration', 'persistent_state_included': False}
    bundle.writestr('source-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode())
sha = hashlib.sha256(archive.read_bytes()).hexdigest()
(OUT / 'install_naimei.py').write_bytes((ROOT / 'scripts/install_naimei.py').read_bytes())
receipt = {'archive': archive.name, 'sha256': sha, 'bytes': archive.stat().st_size, 'source_commit': commit,
           'branch': branch, 'files': len(records)}
(OUT / 'release.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
print(json.dumps(receipt))
