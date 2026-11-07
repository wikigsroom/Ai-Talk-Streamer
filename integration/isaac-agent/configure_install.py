"""Create machine-local game config and a verified save snapshot; never alter saves."""
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json
import os
import re
import shutil
import psutil

ROOT = Path(__file__).resolve().parent
SLOT3 = re.compile(r'^(?:[0-9]{8}[.])?(?:(?:rep|abp|ab)_)?(?:persistentgamedata|gamestate)3[.]dat$', re.I)


def linked(path):
    return path.is_symlink() or path.is_junction()


def inventory(root):
    if linked(root): raise RuntimeError('Linked save root is unsupported')
    files = {}
    directories = []
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in [*dirs, *names]:
            entry = Path(base)/name
            if linked(entry): raise RuntimeError('Linked save entry is unsupported: '+str(entry))
            relative = entry.relative_to(root).as_posix()
            if entry.is_dir(): directories.append(relative)
            elif entry.is_file(): files[relative] = hashlib.sha256(entry.read_bytes()).hexdigest()
            else: raise RuntimeError('Unsupported save entry: '+str(entry))
    return {'files': files, 'directories': sorted(directories)}


def configure(game_root, save_root, protected_roots=(), backup_root=None, allow_existing_slot3=False):
    outputs = [ROOT/'game-install.json', ROOT/'save-protection.json']
    if any(p.exists() for p in outputs):
        raise RuntimeError('Machine config already exists; left untouched. Use a separate checkout for a new setup.')
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').lower() == 'isaac-ng.exe':
            raise RuntimeError('Close the game normally before creating a consistent save backup')
    game_root = Path(game_root).resolve(); save_root = Path(save_root)
    if not (game_root/'isaac-ng.exe').is_file(): raise RuntimeError('isaac-ng.exe is missing')
    if not save_root.is_dir() or linked(save_root): raise RuntimeError('Expected an existing unlinked save directory')
    save_root = save_root.resolve()
    roots = [save_root]
    for item in protected_roots:
        original = Path(item)
        if not original.is_dir() or linked(original): raise RuntimeError('Invalid protected save root')
        path = original.resolve()
        if path == save_root or path.is_relative_to(save_root) or save_root.is_relative_to(path):
            raise RuntimeError('Protected roots must be separate from the writable slot-3 save area')
        if path not in roots: roots.append(path)
    if not allow_existing_slot3 and any(SLOT3.fullmatch(p.name) for p in save_root.rglob('*.dat')):
        raise RuntimeError('Slot-3 data exists. No files changed. Use --allow-existing-slot3 only for an explicitly authorized test slot.')
    parent = Path(backup_root).resolve() if backup_root else ROOT/'backups'
    if any(parent == p or parent.is_relative_to(p) for p in roots):
        raise RuntimeError('Backup destination must be outside every source directory')
    inventories = [inventory(p) for p in roots]
    destination = parent/('setup_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for index, (source, before) in enumerate(zip(roots, inventories)):
        target = destination/str(index)
        shutil.copytree(source, target, copy_function=shutil.copy2)
        if inventory(source) != before or inventory(target) != before:
            raise RuntimeError('Save snapshot verification failed; no machine config created')
        for relative, digest in before['files'].items():
            original = source/relative
            writable_slot3 = index == 0 and bool(SLOT3.fullmatch(original.name))
            records.append({'source': str(original), 'backup': str(target/relative),
                            'sha256': digest, 'writable_test_slot3': writable_slot3})
    protected = [r for r in records if not r['writable_test_slot3']]
    dat_count = sum(Path(r['source']).suffix.lower() == '.dat' for r in protected)
    manifest = destination/'manifest.json'
    manifest.write_text(json.dumps({'verification': 'passed', 'files': protected,
        'snapshot_files': records, 'protected_dat_count': dat_count,
        'source_files_modified': False}, indent=2), encoding='utf8')
    install = {'game_root': str(game_root), 'executable': 'isaac-ng.exe',
        'launch_arguments': ['--luadebug'], 'save_root': str(save_root),
        'expected_version': '1.7.9b', 'allowed_slot': 3, 'provider': 'local', 'shadow_enabled': False}
    protection = {'allowed_slot': 3, 'require_fresh_slot': not allow_existing_slot3,
        'autopilot_allowed': False, 'baseline_manifest': str(manifest),
        'game_root': str(game_root), 'save_root': str(save_root),
        'active_persistent_save': 'persistentgamedata3.dat', 'state': 'unverified_observation_only'}
    for path, value in zip(outputs, [install, protection]):
        with path.open('x', encoding='utf8') as stream: json.dump(value, stream, indent=2)
    return {'configured': True, 'backup_verified': True, 'protected_dat_files': dat_count,
            'snapshot_files': len(records), 'gameplay_armed': False, 'backup': str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root', required=True); parser.add_argument('--save-root', required=True)
    parser.add_argument('--protected-root', action='append', default=[])
    parser.add_argument('--backup-root'); parser.add_argument('--allow-existing-slot3', action='store_true')
    args = parser.parse_args()
    print(json.dumps(configure(args.game_root, args.save_root, args.protected_root,
                               args.backup_root, args.allow_existing_slot3)))


if __name__ == '__main__': main()
