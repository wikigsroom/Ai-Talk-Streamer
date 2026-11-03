"""Prepare pinned public MC build inputs inside this checkout; never starts a runtime."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.setup/mc-survival'
PATCHES = ROOT / 'game-adapters/minecraft/survival/controlled-patches.json'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked(data: bytes, spec: dict) -> bytes:
    if len(data) > spec['max_bytes'] or digest(data) != spec['sha256']:
        raise ValueError('MC_SURVIVAL_BUILD_INPUT_HASH_OR_SIZE')
    return data


def contained(path: Path, base: Path) -> None:
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)() or not path.resolve().is_relative_to(base.resolve()):
        raise ValueError('MC_SURVIVAL_BUILD_PATH_OUTSIDE_PROJECT')


def obtain(spec: dict, offline: bool) -> Path:
    if Path(spec['file']).name != spec['file'] or ':' in spec['file'] or chr(92) in spec['file']:
        raise ValueError('MC_SURVIVAL_BUILD_INPUT_PATH')
    target = CACHE / spec['file']
    contained(target, CACHE)
    if target.exists():
        if target.stat().st_size > spec['max_bytes']:
            raise ValueError('MC_SURVIVAL_BUILD_INPUT_HASH_OR_SIZE')
        checked(target.read_bytes(), spec)
        return target
    if offline:
        raise ValueError('MC_SURVIVAL_BUILD_INPUT_MISSING')
    request = urllib.request.Request(spec['url'], headers={'User-Agent': 'Ai-Talk-Streamer-native-survival-build'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = checked(response.read(spec['max_bytes'] + 1), spec)
    target.write_bytes(data)
    return target


def extract_sources(source: Path, destination: Path) -> dict[str, str]:
    files, seen = {}, set()
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 1000 or sum(e.file_size for e in entries) > 20 * 1024 * 1024:
            raise ValueError('MC_SURVIVAL_SOURCE_ARCHIVE_LIMIT')
        for entry in entries:
            name = PurePosixPath(entry.orig_filename)
            if name.is_absolute() or '..' in name.parts or any(':' in part or chr(92) in part or chr(0) in part for part in name.parts):
                raise ValueError('MC_SURVIVAL_SOURCE_ARCHIVE_PATH')
            relative = PurePosixPath(*name.parts[1:])
            if entry.is_dir() or not (str(relative).startswith('src/main/') or str(relative) == 'LICENSE'):
                continue
            key = str(relative).casefold()
            if key in seen or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('MC_SURVIVAL_SOURCE_ARCHIVE_DUPLICATE_OR_LINK')
            seen.add(key)
            target = destination.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('MC_SURVIVAL_SOURCE_ARCHIVE_PATH')
            target.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(entry)
            target.write_bytes(data)
            files[str(relative)] = digest(data)
    return files


def apply_patches(source: Path, patch_path: Path) -> list[dict]:
    patches = json.loads(patch_path.read_text(encoding='utf-8'))
    results = []
    for patch in patches:
        target = source / patch['path']
        if not target.resolve().is_relative_to(source.resolve()):
            raise ValueError('MC_SURVIVAL_PATCH_PATH')
        before = target.read_text(encoding='utf-8')
        if not patch['before'] or before.count(patch['before']) != patch.get('count', 1):
            raise ValueError('MC_SURVIVAL_PATCH_CONTEXT:' + patch['id'])
        after = before.replace(patch['before'], patch['after'])
        target.write_text(after, encoding='utf-8', newline='\n')
        results.append({'id': patch['id'], 'path': patch['path'], 'sha256_after': digest(target.read_bytes())})
    return results


def tree_hashes(directory: Path) -> dict[str, str]:
    result, total = {}, 0
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError('MC_SURVIVAL_GENERATED_LINK')
        if path.is_file():
            total += path.stat().st_size
            if len(result) >= 1000 or total > 20 * 1024 * 1024:
                raise ValueError('MC_SURVIVAL_GENERATED_SIZE_LIMIT')
            result[path.relative_to(directory).as_posix()] = digest(path.read_bytes())
    return result


def embedded_jars(data: bytes, parent: str, depth: int = 0) -> list[dict]:
    if depth > 4:
        raise ValueError('MC_SURVIVAL_EMBEDDED_DEPTH')
    result = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = [e for e in archive.infolist() if e.filename.startswith('META-INF/jars/') and e.filename.endswith('.jar')]
        if len(entries) > 32 or sum(e.file_size for e in entries) > 32 * 1024 * 1024:
            raise ValueError('MC_SURVIVAL_EMBEDDED_LIMIT')
        for entry in sorted(entries, key=lambda e: e.filename):
            nested = archive.read(entry)
            name = parent + '!/' + entry.filename
            result.append({'entry': name, 'sha256': digest(nested), 'bytes': len(nested)})
            result.extend(embedded_jars(nested, name, depth + 1))
    return result


def require_branch() -> None:
    if subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() != 'mc':
        raise ValueError('MC_BRANCH_REQUIRED')


def materialize_local_module(spec: dict) -> dict[str, str]:
    """Loom needs module metadata for a nested include; bytes remain the pinned upstream JAR."""
    directory = CACHE / 'maven/dev/aitalkstreamer/pinned/baritone/1.21.1'
    contained(directory, CACHE)
    directory.mkdir(parents=True, exist_ok=True)
    jar = directory / 'baritone-1.21.1.jar'
    contained(jar, CACHE)
    jar.write_bytes(checked((CACHE / spec['file']).read_bytes(), spec))
    pom = directory / 'baritone-1.21.1.pom'
    contained(pom, CACHE)
    pom.write_text('<project><modelVersion>4.0.0</modelVersion><groupId>dev.aitalkstreamer.pinned</groupId>'
                   '<artifactId>baritone</artifactId><version>1.21.1</version><packaging>jar</packaging></project>\n', encoding='utf-8')
    return {p.relative_to(CACHE).as_posix(): digest(p.read_bytes()) for p in [jar, pom]}


def verify() -> dict:
    require_branch()
    contained(CACHE, ROOT)
    receipt = json.loads((CACHE / 'preparation.json').read_text(encoding='utf-8'))
    lock_path = ROOT / 'configs/mc-survival-build.lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    if receipt['lock_sha256'] != digest(lock_path.read_bytes()) or receipt['patches_sha256'] != digest(PATCHES.read_bytes()):
        raise ValueError('MC_SURVIVAL_PREPARATION_STALE')
    for spec in [lock['source'], lock['compile_artifact'], *lock['nested']]:
        obtain(spec, True)
    for relative, expected in receipt['local_module_hashes'].items():
        path = CACHE / relative
        contained(path, CACHE)
        if path.stat().st_size > 2 * 1024 * 1024 or digest(path.read_bytes()) != expected:
            raise ValueError('MC_SURVIVAL_LOCAL_MODULE_CHANGED')
    directory = CACHE / receipt['generated_directory']
    if not directory.resolve().is_relative_to(CACHE.resolve()) or tree_hashes(directory) != receipt['generated_hashes']:
        raise ValueError('MC_SURVIVAL_GENERATED_CHANGED')
    if embedded_jars((CACHE / lock['compile_artifact']['file']).read_bytes(), lock['compile_artifact']['file']) != receipt['embedded_artifacts']:
        raise ValueError('MC_SURVIVAL_EMBEDDED_CHANGED')
    if receipt['automatic_input_authorized'] is not False or receipt['runtime_started'] is not False:
        raise ValueError('MC_SURVIVAL_INVALID_PREPARATION_SCOPE')
    return receipt


def prepare(offline: bool) -> dict:
    require_branch()
    contained(CACHE, ROOT)
    lock_path = ROOT / 'configs/mc-survival-build.lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    CACHE.mkdir(parents=True, exist_ok=True)
    source, artifact = obtain(lock['source'], offline), obtain(lock['compile_artifact'], offline)
    with zipfile.ZipFile(artifact) as archive:
        for nested in lock['nested']:
            # Validate the cache destination even when the nested input has not been written yet.
            if Path(nested['file']).name != nested['file'] or ':' in nested['file'] or chr(92) in nested['file']:
                raise ValueError('MC_SURVIVAL_BUILD_INPUT_PATH')
            data = checked(archive.read(nested['entry']), nested)
            target = CACHE / nested['file']
            contained(target, CACHE)
            target.write_bytes(data)
    patch_hash = digest(PATCHES.read_bytes())
    generated = CACHE / ('generated-' + lock['source']['sha256'][:16] + '-' + patch_hash[:16])
    contained(generated, CACHE)
    files = extract_sources(source, generated)
    audit = json.loads((ROOT / 'configs/mc-executor-source-audit.json').read_text(encoding='utf-8'))
    if audit['commit'] != lock['source_commit']:
        raise ValueError('MC_SURVIVAL_SOURCE_COMMIT')
    for entry in audit['reviewed_source_files']:
        if entry['path'].startswith('src/main/') or entry['path'] == 'LICENSE':
            if files.get(entry['path']) != entry['sha256']:
                raise ValueError('MC_SURVIVAL_SOURCE_AUDIT')
    patched = apply_patches(generated, PATCHES)
    hashes = tree_hashes(generated)
    if set(files) != set(hashes):
        raise ValueError('MC_SURVIVAL_GENERATED_EXTRA_FILES')
    local_modules = materialize_local_module(lock['nested'][0]) if lock['nested'] else {}
    receipt = {'classification': 'BUILD_INPUT_PREPARATION_ONLY', 'branch': 'mc', 'source_commit': lock['source_commit'],
               'lock_sha256': digest(lock_path.read_bytes()), 'source_files': len(files), 'patches': patched,
               'patches_sha256': patch_hash, 'generated_directory': generated.name, 'generated_hashes': hashes,
               'embedded_artifacts': embedded_jars(artifact.read_bytes(), artifact.name),
               'local_module_hashes': local_modules,
               'automatic_input_authorized': False, 'runtime_started': False}
    (CACHE / 'preparation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Require all hash-pinned files already in the project cache.')
    parser.add_argument('--verify', action='store_true', help='Read-only check of prepared inputs, exact patches and generated source tree.')
    args = parser.parse_args()
    receipt = verify() if args.verify else prepare(args.offline)
    print(json.dumps({'classification': receipt['classification'], 'source_commit': receipt['source_commit'],
                      'source_files': receipt['source_files'], 'patch_count': len(receipt['patches']),
                      'embedded_artifact_count': len(receipt['embedded_artifacts']),
                      'lock_sha256': receipt['lock_sha256'], 'automatic_input_authorized': False,
                      'runtime_started': False}, ensure_ascii=False))
