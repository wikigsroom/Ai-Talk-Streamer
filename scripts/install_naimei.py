"""Verify a Naimei source archive before installing into its own native directory."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import subprocess
import zipfile
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install(archive, expected_hash, destination, shared):
    if os.name != 'nt':
        raise RuntimeError('NATIVE_WINDOWS_REQUIRED')
    destination, shared = destination.resolve(), shared.resolve()
    if destination != shared / 'naimei' or shared.name != '虚拟数字人直播':
        raise RuntimeError('NAIMEI_INSTALL_DESTINATION_MISMATCH')
    data = archive.read_bytes()
    if digest(data) != expected_hash:
        raise RuntimeError('ARCHIVE_CHECKSUM_MISMATCH')
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('source-manifest.json'))
        if manifest['branch'] != 'naimei' or manifest['target'] != 'naimei-rtx4090':
            raise RuntimeError('WRONG_SOURCE_BRANCH')
        records = manifest['files']
        names = [x['path'] for x in records]
        if len(names) != len(set(names)) or set(bundle.namelist()) != set(names + ['source-manifest.json']):
            raise RuntimeError('SOURCE_MANIFEST_FILE_SET_MISMATCH')
        verified = []
        for item in records:
            rel = PurePosixPath(item['path'])
            if rel.is_absolute() or '..' in rel.parts or ':' in str(rel) or '\\' in str(rel):
                raise RuntimeError('UNSAFE_ARCHIVE_PATH')
            if rel.parts[0] not in {'backend', 'web', 'integration', 'scripts', 'configs', 'docs', 'assets'}:
                raise RuntimeError('UNEXPECTED_SOURCE_ROOT')
            payload = bundle.read(item['path'])
            if len(payload) != item['bytes'] or digest(payload) != item['sha256']:
                raise RuntimeError('SOURCE_FILE_CHECKSUM_MISMATCH:' + item['path'])
            target = destination.joinpath(*rel.parts)
            if not target.resolve().is_relative_to(destination):
                raise RuntimeError('SOURCE_FILE_OUTSIDE_NAIMEI')
            verified.append((target, payload))
    destination.mkdir(parents=True, exist_ok=True)
    for target, payload in verified:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    tools = destination / 'tools'
    tools.mkdir(exist_ok=True)
    link = tools / 'dsh'
    dependency = shared / 'tools/dsh'
    if not dependency.is_dir():
        raise RuntimeError('SHARED_DSH_RUNTIME_MISSING')
    if not link.exists():
        script = "New-Item -ItemType Junction -Path '" + str(link).replace("'", "''") + "' -Target '" + str(dependency).replace("'", "''") + "' | Out-Null"
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                       check=True, creationflags=0x08000000, timeout=20)
    if link.resolve() != dependency.resolve():
        raise RuntimeError('SHARED_DSH_LINK_MISMATCH')
    setup = destination / '.setup'
    setup.mkdir(exist_ok=True)
    (setup / 'source-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    receipt = {'target': manifest['target'], 'branch': manifest['branch'], 'source_commit': manifest['source_commit'],
               'source_worktree_dirty': manifest['source_worktree_dirty'], 'archive_sha256': expected_hash,
               'verified_source_manifest': True, 'verified_file_count': len(verified), 'installed_at': time.time(),
               'source_manifest_sha256': digest(json.dumps(manifest, sort_keys=True).encode()),
               'persistent_state_imported': False, 'new_model_weight_bytes': 0}
    (setup / 'deployment-origin.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--shared-root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.archive, args.sha256, args.destination, args.shared_root), ensure_ascii=False))
