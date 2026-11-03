"""Assemble existing native dependencies without downloading models or copying live state.

Run on the authorized 3080 host. Public source installation, dependency assembly,
operator settings, state migration and readiness are separate recorded operations.
No copied readiness/origin/process receipt can authorize the new installation.
"""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import uuid

from native_operation import operation, safe_path, atomic_json
from mc_deployment import installed_source_identity, inside, read, require, sha, digest, model_runtime_rows

GROUPS = ('runtime/python/cpython-3.10.22-windows-x86_64-none', 'runtime/livetalking', 'runtime/platforms', 'runtime/tts-benchmark/omnivoice',
          'runtime/tts-benchmark/f5', 'src/LiveTalking', 'src/tts-benchmark/omnivoice',
          'src/tts-benchmark/f5', 'models', 'tools/dsh/node_modules',
          'tools/node/node-v24.22.1-win-x64', 'tools/ffmpeg7-shared', 'tools/ffmpeg', 'cache/nltk_data', 'assets')
EXCLUDED = frozenset({'.git', '__pycache__', 'logs', 'crash-reports', '.pytest_cache'})
SETTINGS = ('configs/livetalking.yaml', 'configs/hardware-profile.json', 'configs/resident-tts.json',
            'configs/dsh-active-policy.json', 'configs/channel.env', 'configs/platforms.private.json')
RECEIPT = '.setup/mc-offline-dependencies.json'
BASE_PYTHON = 'runtime/python/cpython-3.10.22-windows-x86_64-none'
ORIGINALS = {
    'index.js': '0930f0dd0c004afb8a309e67b45da7bd738f113d9afcf60197116e24152118c1',
    'tools-seam.js': '7cddaa0184a1413bfcb176a5b753cedd9dc85d1b83471add35c0bd76ef496f22',
    'data-plane.js': '742c31924ef3505d378f445a1fd5fd33ad4286305ab52c00cf3c73135f354c43',
    'memory/inject.js': 'e6bb8ce9ebdaada45fe956eaa6397b180b55cc545a02baf1eabb4a3287ceb64e',
}


def finalize_dependencies(root, source, plan):
    """Derive portable venvs and a fresh connector proof from verified bytes."""
    import importlib.util
    changes = []
    for group in ('runtime/livetalking', 'runtime/platforms', 'runtime/tts-benchmark/omnivoice', 'runtime/tts-benchmark/f5'):
        name = group + '/pyvenv.cfg'; path = no_links(root / name, root)
        require(sha(path) == plan['files'][name]['sha256'], 'MC_OFFLINE_VENV_SOURCE_CHANGED')
        before = path.read_bytes(); text = before.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
        rows = dict(line.split(' = ', 1) for line in text.splitlines() if ' = ' in line)
        require(Path(rows.get('home', '')).resolve() == (source / BASE_PYTHON).resolve(), 'MC_OFFLINE_VENV_HOME')
        text = text.replace(str(source), str(root)).replace(source.as_posix(), root.as_posix())
        with path.open('w', encoding='utf-8', newline='\n') as stream: stream.write(text)
        changes.append({'path': name, 'operation': 'REBASE_VERIFIED_NATIVE_PYTHON_HOME',
                        'before_sha256': hashlib.sha256(before).hexdigest(), 'after_sha256': sha(path)})
    # Never import another installation's patch receipt. Restore the pinned
    # original package bytes, then apply this installation's current connector.
    prefix = root / 'tools/dsh/node_modules/deepseek-harness-humanity/lib'
    for name, expected in ORIGINALS.items():
        original = no_links(source / '.setup/dsh-humanity-originals/0.1.17' / name, source)
        require(original.is_file() and sha(original) == expected, 'MC_OFFLINE_HUMANITY_ORIGINAL')
        target = no_links(prefix / name, root)
        require(sha(target) == plan['files'][target.relative_to(root).as_posix()]['sha256'],
                'MC_OFFLINE_HUMANITY_IMPORT_CHANGED')
        before = sha(target); target.write_bytes(original.read_bytes())
        changes.append({'path': target.relative_to(root).as_posix(), 'operation': 'RESTORE_PINNED_UPSTREAM_BEFORE_CURRENT_PATCH',
                        'before_sha256': before, 'after_sha256': expected})
    spec = importlib.util.spec_from_file_location('mc_fresh_humanity_patch', root / 'deployment/patch_humanity.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    patch = module.patch(root, root / 'tools/dsh', source_root=root)
    return {'derived_files': changes, 'current_humanity_patch': patch}


def repair_venv_line_endings(root):
    """Repair only the exact imported/derived venv files recorded by this installer."""
    root=Path(root).resolve();identity=installed_source_identity(root)
    with operation(root,'mc-offline-venv-line-ending-repair'):
        receipt=read(no_links(root/RECEIPT,root),limit=64*1024*1024)
        require(receipt['installation_root']==str(root),'MC_OFFLINE_REPAIR_INSTALLATION')
        source=Path(receipt['source_root']).resolve();changes=[]
        prior={row['path']:row['after_sha256'] for row in receipt['derived_files']}
        for row in receipt.get('venv_repairs',[]):prior[row['path']]=row['after_sha256']
        for group in ('runtime/livetalking','runtime/platforms','runtime/tts-benchmark/omnivoice','runtime/tts-benchmark/f5'):
            name=group+'/pyvenv.cfg';path=no_links(root/name,root);original=no_links(source/name,source)
            require(sha(path)==prior[name] and sha(original)==receipt['files'][name]['sha256'],'MC_OFFLINE_REPAIR_SOURCE_CHANGED')
            text=original.read_bytes().decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
            rows=dict(line.split(' = ',1) for line in text.splitlines() if ' = ' in line)
            require(Path(rows['home']).resolve()==(source/BASE_PYTHON).resolve(),'MC_OFFLINE_VENV_HOME')
            value=text.replace(str(source),str(root)).replace(source.as_posix(),root.as_posix()).encode('utf-8')
            before=sha(path);temp=path.with_name('pyvenv.mc-repair-'+uuid.uuid4().hex+'.tmp')
            try:
                with temp.open('xb') as stream:stream.write(value);stream.flush();os.fsync(stream.fileno())
                os.replace(temp,path)
            finally:temp.unlink(missing_ok=True)
            changes.append({'path':name,'before_sha256':before,'after_sha256':sha(path),'operation':'NORMALIZE_VERIFIED_VENV_TO_LF'})
        receipt.setdefault('venv_repairs',[]).extend(changes)
        atomic_json(root,root/RECEIPT,receipt)
        result={'ok':True,'source_snapshot_sha256':identity['snapshot_sha256'],'files':changes,'models_started':False,'live_state_copied':False}
        atomic_json(root,root/'.setup/mc-venv-repair.json',result)
    return result


def supplement_release_runtime_files(root, source):
    """Import missing inference files; never reconstruct historical download receipts."""
    root=Path(root).resolve();source=Path(source).resolve();identity=installed_source_identity(root)
    lock=read(no_links(root/'configs/releases/rtx3080-k02-runtime-lock.json',root));added=[]
    with operation(root,'mc-offline-release-runtime-supplement'):
        runtime_rows=model_runtime_rows(lock)
        for pin in runtime_rows:
            name=pin['path'];target=no_links(root/name,root);original=no_links(source/name,source)
            if target.exists():
                require(target.stat().st_size==pin['bytes'] and sha(target)==pin['sha256'],'MC_OFFLINE_RELEASE_PIN_CHANGED')
            else:
                copy_verified(original,target,pin);added.append({'path':name,'bytes':pin['bytes'],'sha256':pin['sha256']})
        result={'ok':True,'source_snapshot_sha256':identity['snapshot_sha256'],'added_files':added,
                'release_files_verified':len(runtime_rows),
                'archive_metadata_missing':[pin['path'] for pin in lock['model_files']
                    if pin not in runtime_rows and not (root/pin['path']).is_file()],
                'historical_provenance_reconstructed':False,'downloads_performed':False,'models_started':False}
        atomic_json(root,root/'.setup/mc-offline-release-runtime-supplement.json',result)
    return result


def no_links(path, root):
    path = Path(os.path.abspath(path)); root = Path(root).resolve()
    require(path.is_relative_to(root), 'MC_OFFLINE_PATH_OUTSIDE_ROOT')
    for p in (path, *path.parents):
        try: attributes = getattr(p.lstat(), 'st_file_attributes', 0)
        except FileNotFoundError: attributes = 0
        require(not p.is_symlink() and not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                'MC_OFFLINE_LINK_REFUSED')
        if p == root: break
    return path


def inventory(source, *, groups=None):
    source = Path(source).resolve()
    selected = GROUPS if groups is None else tuple(groups)
    require(selected and all(group in GROUPS for group in selected) and len(set(selected))==len(selected),
            'MC_OFFLINE_INVENTORY_GROUPS')
    # The selected avatar is a single accepted bank; other historical banks are preserved in place.
    avatar = read(inside(source, 'configs/livetalking.yaml'))['avatar_id']
    require(isinstance(avatar, str) and avatar and '/' not in avatar and '\\' not in avatar
            and avatar not in ('.', '..'), 'MC_OFFLINE_AVATAR_ID')
    rows = {}
    for group in selected:
        top = no_links(source / group, source)
        require(top.is_dir(), 'MC_OFFLINE_DEPENDENCY_GROUP_MISSING:' + group)
        for directory, dirs, files in os.walk(top, followlinks=False):
            parent = no_links(Path(directory), source)
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
            if group == 'src/LiveTalking' and parent == top / 'data/avatars':
                dirs[:] = [d for d in dirs if d == avatar]
            for d in dirs: no_links(parent / d, source)
            for name in sorted(files):
                p = no_links(parent / name, source)
                if p.suffix.casefold() in ('.pyc', '.pyo', '.log', '.tmp', '.lock'): continue
                require(p.is_file(), 'MC_OFFLINE_NOT_FILE')
                relative = p.relative_to(source).as_posix()
                require(len(rows) < 250000 and p.stat().st_size <= 32 * 1024**3,
                        'MC_OFFLINE_INVENTORY_LIMIT')
                rows[relative] = {'bytes': p.stat().st_size, 'sha256': sha(p)}
    # Source and license files accompany the actual model/runtime distributions above.
    # The approved voice reference is outside those distribution directories.
    voices = read(inside(source, 'configs/resident-tts.json'))
    require(voices.get('default_voice_id') == 'O07' and set(voices.get('voices', {})) == {'O07', 'F07'},
            'MC_OFFLINE_VOICE_PAIR')
    for name in [voices['reference_audio'], voices.get('warmup_audio', ''), 'tools/dsh/package.json', 'tools/dsh/package-lock.json',
                 'assets/vertical/student-dorm-720x1280.png']:
        if not name: continue
        p = inside(source, name); require(p.is_file(), 'MC_OFFLINE_REFERENCE_MISSING')
        rows[name] = {'bytes': p.stat().st_size, 'sha256': sha(p)}
    require(sum(row['bytes'] for row in rows.values()) <= 128 * 1024**3, 'MC_OFFLINE_TOTAL_LIMIT')
    return {'schema_version': 1, 'classification': 'EXISTING_NATIVE_IMMUTABLE_DEPENDENCIES_NOT_READINESS',
            'source_root': str(source), 'avatar_id': avatar, 'groups': list(selected),
            'files': rows, 'inventory_sha256': digest(rows), 'downloads_performed': False,
            'private_configuration_included': False, 'live_state_included': False}


def validate_inventory(plan):
    require(isinstance(plan, dict) and plan.get('schema_version') == 1 and plan.get('groups') == list(GROUPS)
            and plan.get('classification') == 'EXISTING_NATIVE_IMMUTABLE_DEPENDENCIES_NOT_READINESS'
            and plan.get('downloads_performed') is False and plan.get('live_state_included') is False
            and plan.get('private_configuration_included') is False, 'MC_OFFLINE_PLAN_SHAPE')
    rows = plan.get('files'); require(isinstance(rows, dict) and 0 < len(rows) <= 250000,
                                      'MC_OFFLINE_PLAN_FILES')
    require(plan.get('inventory_sha256') == digest(rows), 'MC_OFFLINE_PLAN_DIGEST')
    require(len({name.casefold() for name in rows}) == len(rows), 'MC_OFFLINE_WINDOWS_ALIAS')
    for name, row in rows.items():
        require(isinstance(name, str), 'MC_OFFLINE_PLAN_PATH')
        p = PurePosixPath(name)
        require(isinstance(name, str) and name and '\\' not in name and not p.is_absolute()
                and '..' not in p.parts and all(':' not in part and part[-1:] not in ('.', ' ') for part in p.parts)
                and not any(part.casefold() in EXCLUDED for part in p.parts), 'MC_OFFLINE_PLAN_PATH')
        permitted = any(name.startswith(group + '/') for group in GROUPS) or name in (
            'tools/dsh/package.json', 'tools/dsh/package-lock.json',
            'assets/voices/female-a-o07/reference.wav', 'assets/voices/female-a-o07/O07-audition.wav',
            'assets/vertical/student-dorm-720x1280.png')
        require(permitted and isinstance(row, dict) and set(row) == {'bytes', 'sha256'}
                and type(row['bytes']) is int and 0 <= row['bytes'] <= 32 * 1024**3
                and isinstance(row['sha256'], str) and len(row['sha256']) == 64
                and all(c in '0123456789abcdef' for c in row['sha256']), 'MC_OFFLINE_PLAN_FILE')
    require(sum(row['bytes'] for row in rows.values()) <= 128 * 1024**3, 'MC_OFFLINE_TOTAL_LIMIT')


def copy_verified(source, target, pin):
    require(source.is_file() and source.stat().st_size == pin['bytes'], 'MC_OFFLINE_SOURCE_SIZE')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite dependencies, private operator data or an earlier partial import.
    require(not target.exists(), 'MC_OFFLINE_TARGET_EXISTS')
    temp = target.with_name('.mc-import-' + uuid.uuid4().hex + '.part')
    total = 0; value = hashlib.sha256()
    try:
        with source.open('rb') as incoming, temp.open('xb') as outgoing:
            while chunk := incoming.read(1024 * 1024):
                total += len(chunk); require(total <= pin['bytes'], 'MC_OFFLINE_SOURCE_CHANGED')
                value.update(chunk); outgoing.write(chunk)
            outgoing.flush(); os.fsync(outgoing.fileno())
        require(total == pin['bytes'] and value.hexdigest() == pin['sha256'], 'MC_OFFLINE_SOURCE_CHANGED')
        # Windows rename refuses an existing destination. No replace is used for imported files.
        temp.rename(target)
    finally:
        temp.unlink(missing_ok=True)


def assemble(root, plan, expected_sha256):
    root = Path(root).resolve(); validate_inventory(plan)
    require(digest(plan) == expected_sha256, 'MC_OFFLINE_REVIEWED_PLAN_CHANGED')
    source = Path(plan['source_root'])
    require(source.is_absolute() and source == source.resolve() and root != source
            and not source.is_relative_to(root), 'MC_OFFLINE_SOURCE_ROOT')
    identity = installed_source_identity(root)
    require(not (root / RECEIPT).exists(), 'MC_OFFLINE_ALREADY_IMPORTED')
    required_bytes = sum(row['bytes'] for row in plan['files'].values())
    require(shutil.disk_usage(root).free >= required_bytes + 2 * 1024**3, 'MC_OFFLINE_DISK_SPACE')
    with operation(root, 'mc-offline-dependency-import'):
        # Reject the whole import before copying if any immutable destination already exists.
        for name in plan['files']:
            require(not no_links(root / name, root).exists(), 'MC_OFFLINE_TARGET_EXISTS')
        copied = 0
        progress = root / '.setup/mc-offline-import-progress.json'
        try:
            from concurrent.futures import ThreadPoolExecutor
            def transfer(pair):
                name,pin=pair
                copy_verified(no_links(source / name, source), no_links(root / name, root), pin)
            # Bound parallel file I/O while retaining exact byte/hash checks,
            # no-overwrite publication and the installation's operation lock.
            with ThreadPoolExecutor(max_workers=4) as workers:
                for _ in workers.map(transfer,plan['files'].items()):
                    copied += 1
                    if copied % 100 == 0:
                        atomic_json(root, progress, {'state': 'copying', 'copied_files': copied, 'total_files': len(plan['files'])})
            derived = finalize_dependencies(root, source, plan)
            result = {**plan, **derived, 'installation_root': str(root), 'source_snapshot_sha256': identity['snapshot_sha256'],
                      'plan_sha256': expected_sha256, 'imported_at': datetime.now(timezone.utc).isoformat(),
                      'full_application_prepared': False, 'automatic_input_authorized': False,
                      'models_loaded': False, 'services_started': False}
            atomic_json(root, root / RECEIPT, result)
            atomic_json(root, progress, {'state': 'copied', 'copied_files': copied, 'total_files': len(plan['files'])})
        except BaseException:
            atomic_json(root, progress, {'state': 'failed', 'copied_files': copied, 'total_files': len(plan['files']),
                                        'recovery': 'PRESERVE_FAILED_INSTALLATION_AND_USE_NEW_SOURCE_DESTINATION'})
            raise
    return {'ok': True, 'copied_files': copied, 'copied_bytes': required_bytes,
            'full_application_prepared': False, 'automatic_input_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'assemble'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    require(os.name == 'nt' and platform.node().casefold() == 'desktop-2qqpn1h',
            'MC_NATIVE_RUNTIME_REQUIRES_REMOTE_3080')
    if args.action == 'inventory':
        require(args.source is not None and not args.plan.exists(), 'MC_OFFLINE_NEW_PLAN_REQUIRED')
        plan = inventory(args.source); validate_inventory(plan)
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        with args.plan.open('x', encoding='utf-8') as output: json.dump(plan, output, ensure_ascii=False, indent=2)
        result = {'ok': True, 'files': len(plan['files']), 'bytes': sum(row['bytes'] for row in plan['files'].values()),
                  'plan_sha256': digest(plan)}
    else:
        require(args.sha256 is not None, 'MC_OFFLINE_PLAN_HASH_REQUIRED')
        plan = json.loads(args.plan.read_text(encoding='utf-8-sig'))
        result = assemble(args.root, plan, args.sha256)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
