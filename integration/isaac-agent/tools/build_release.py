"""Build a versioned release strictly from a committed Git tree, without game access."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {'private', '.dsh-home', 'node_modules', 'python-libs', '__pycache__',
                   'logs', 'recordings', 'screenshots', 'backups', 'artifacts', '.venv', 'venv'}
FORBIDDEN_FILES = {'game-install.json', 'save-protection.json', 'native-controller.lua',
                   'native-request.lock', '.stack-operation.lock', 'strategy-process.json',
                   'config/decision_provider.json', 'dsh-host/runtime.json', 'dsh-host/isaac.patch.json'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def committed_files(ref):
    if ref.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_./-]+', ref):
        raise ValueError('Expected a normal Git revision')
    sha = subprocess.check_output(['git', 'rev-parse', '--verify', ref+'^{commit}'], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(['git', 'archive', '--format=tar', sha], cwd=ROOT)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as tar:
        for member in tar:
            if member.isdir(): continue
            name = member.name
            path = PurePosixPath(name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsupported Git archive entry: '+name)
            if FORBIDDEN_PARTS.intersection(path.parts) or name in FORBIDDEN_FILES or (
                    path.suffix.lower() in {'.dat', '.vdf', '.zip', '.tgz', '.7z', '.pyc'}):
                raise ValueError('Private/runtime data cannot enter a release: '+name)
            data = tar.extractfile(member).read()
            if re.search(rb'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{24,})', data):
                raise ValueError('Credential-like content in release: '+name)
            files[name] = data
    return sha, files


def build(version, ref, output):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('A final vMAJOR.MINOR.PATCH version is required')
    sha, files = committed_files(ref)
    number = version[1:]
    project = tomllib.loads(files['pyproject.toml'].decode())['project']
    plugin = json.loads(files['dsh-host/isaac-plugin/package.json'])
    if any(value != number for value in (project['version'], plugin['version'],
                                         json.loads(files['dsh-host/package.json'])['version'])):
        raise ValueError('Project, host, plugin and release versions must agree')
    notes = files['docs/releases/'+version+'.md']
    required = {'README.md', 'README.en.md', 'LICENSE', 'requirements-native.lock.txt',
                'configure_install.py', 'configure_model.py', 'launch_game.py', 'manage_stack.py',
                'game-card-enum.json', 'tests/fixtures/native-movement-samples.json', 'dsh-host/package-lock.json', 'docs/media/local-gameplay.gif'}
    if not required.issubset(files): raise ValueError('Missing product files')
    output = Path(output).resolve()
    if output == ROOT or not output.is_relative_to(ROOT/'artifacts'):
        raise ValueError('Output must stay under this checkout artifacts/ directory')
    output.mkdir(parents=True, exist_ok=True)
    prefix = 'agent-gameplay-isaac-'+version
    source_name = prefix+'-windows-source.zip'
    with zipfile.ZipFile(output/source_name, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(prefix+'/'+name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(output/source_name) as archive:
        if archive.testzip() is not None: raise ValueError('Source ZIP verification failed')
        for name, data in files.items():
            if archive.read(prefix+'/'+name) != data: raise ValueError('Source ZIP changed a file')
    folder = 'dsh-host/isaac-plugin/'
    selected = {'package.json', 'LICENSE', *plugin['files']}
    plugin_files = {name: files[folder+name] for name in sorted(selected)}
    tgz_name = plugin['name']+'-'+number+'.tgz'
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for name, data in plugin_files.items():
            info = tarfile.TarInfo('package/'+name)
            info.size = len(data); info.mode = 0o644; info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    with (output/tgz_name).open('wb') as stream:
        with gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as compressed:
            compressed.write(tar_buffer.getvalue())
    with tarfile.open(output/tgz_name, 'r:gz') as archive:
        if set(archive.getnames()) != {'package/'+n for n in plugin_files}: raise ValueError('Unexpected plugin member')
        for name, data in plugin_files.items():
            if archive.extractfile('package/'+name).read() != data: raise ValueError('Plugin content mismatch')
    (output/'RELEASE_NOTES.md').write_bytes(notes)
    assets = []
    for name in [source_name, tgz_name, 'RELEASE_NOTES.md']:
        data = (output/name).read_bytes()
        assets.append({'name': name, 'bytes': len(data), 'sha256': digest(data)})
    manifest = {'schema': 'isaac-release/1', 'version': version, 'source_commit': sha,
        'release_type': 'final', 'build': 'native130-dsh',
        'requirements': {'os': 'native Windows AMD64', 'python': '3.13', 'node': '>=24.9',
                         'game': 'Repentance 1.7.9b, 32-bit', 'dsh': '0.2.2-rc.1'},
        'distribution': 'Source distribution; install native runtimes and pinned dependencies; game not included',
        'source_file_count': len(files),
        'source_files': {name: digest(data) for name, data in sorted(files.items())},
        'assets': assets, 'private_runtime_data_included': False,
        'known_limit': 'Migrated model gateway rejected the configured key during the last audit; local-only mode works'}
    (output/'release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf8', newline='\n')
    checksums = [(a['name'], a['sha256']) for a in assets]
    checksums.append(('release-manifest.json', digest((output/'release-manifest.json').read_bytes())))
    (output/'SHA256SUMS.txt').write_text(''.join(h+'  '+n+'\n' for n, h in checksums), encoding='ascii', newline='\n')
    print(json.dumps({'version': version, 'source_commit': sha, 'source_files': len(files),
                      'assets': [n for n, _ in checksums]+['SHA256SUMS.txt'], 'output': str(output)}))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True); parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--output', default=str(ROOT/'artifacts/release'))
    args = parser.parse_args()
    build(args.version, args.ref, args.output)


if __name__ == '__main__': main()
