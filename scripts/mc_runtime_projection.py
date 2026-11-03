"""Project the reviewed MC web proxy into LiveTalking while all owners are stopped.

The other vendor modules, inference patches, models and dependency import receipt
remain untouched. The projection is source code, never execution authority.
"""
from contextlib import contextmanager
from pathlib import Path
import argparse
import ast
import json
import os
import uuid

import mc_deployment as mc
from native_operation import atomic_json, operation, safe_path

RECEIPT = '.setup/mc-runtime-projection.json'
PROJECTIONS = {'integration/dsh_bridge.py': 'src/LiveTalking/server/dsh_bridge.py',
               'integration/motion_control.py':'src/LiveTalking/server/motion_control.py'}
# Reviewed round083 v26 ZIP 811401a8c16b12574548cd77115aa65a5a336c9ebba5bbf661e1fe04defefbdc,
# snapshot 8e38f1b5f3ad8593cc655209377b4bd682306976b3a45747ae08fc29b4288d3a.
BOOTSTRAP = {'src/LiveTalking/server/dsh_bridge.py':
             'ef2256429ae1d80ed8c477d52b901ea374f6cbba9ec3b1f4a46dd24faa62c6d7'}
OWNERS = ('backend/dsh-bridge/server.mjs', 'src/LiveTalking/app.py',
          'integration/resident_tts_service.py', 'scripts/receiver_service.py',
          'scripts/mc_game_service.py', 'scripts/mc_vision_service.py')


def require_stopped(root):
    import psutil
    anchors = {str(safe_path(root, root / name)).replace('/', '\\').casefold() for name in OWNERS}
    for process in psutil.process_iter(['cmdline']):
        try:
            arguments = {str(a).replace('/', '\\').casefold() for a in process.info['cmdline'] or []}
            mc.require(not anchors.intersection(arguments), 'MC_RUNTIME_PROJECTION_RUNNING_OWNER')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def replace(root, path, data):
    path = safe_path(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.mc-projection-' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        safe_path(root, path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate(root, source=None):
    """Check the bytes actually imported by the running server, without importing it."""
    root = Path(root).resolve()
    source = source or mc.source_identity(root)
    receipt = mc.read(safe_path(root, root / RECEIPT))
    mc.require(receipt.get('schema_version') == 1 and receipt.get('installation_root') == str(root)
               and set(receipt.get('files', {})) == set(PROJECTIONS.values()),
               'MC_RUNTIME_PROJECTION_RECEIPT')
    files = {RECEIPT: mc.sha(safe_path(root, root / RECEIPT))}
    for name, destination in PROJECTIONS.items():
        pin = source['files'].get(name)
        row = receipt['files'][destination]
        mc.require(pin and row.get('source') == name and row.get('sha256') == pin,
                   'MC_RUNTIME_PROJECTION_SOURCE_CHANGED')
        mc.require(mc.sha(safe_path(root, root / name)) == pin
                   and mc.sha(safe_path(root, root / destination)) == pin,
                   'MC_RUNTIME_PROJECTION_BYTES_CHANGED')
        files[destination] = pin
    return files


@contextmanager
def applied(root, source, backup):
    """One source-update transaction: exact allowlist, rollback mirrors and receipt."""
    root = Path(root).resolve(); backup = safe_path(root, Path(backup))
    require_stopped(root)
    previous_path = safe_path(root, root / RECEIPT)
    previous_bytes = previous_path.read_bytes() if previous_path.exists() else None
    previous = json.loads(previous_bytes) if previous_bytes is not None else None
    if previous is not None:
        mc.require(previous.get('schema_version') == 1 and previous.get('installation_root') == str(root)
                   and set(previous.get('files', {})) <= set(PROJECTIONS.values()),
                   'MC_RUNTIME_PROJECTION_RECEIPT')
    dependency_path = safe_path(root, root / '.setup/mc-offline-dependencies.json')
    dependency = mc.read(dependency_path, limit=64 * 1024 * 1024) if dependency_path.exists() else {}
    if dependency:
        mc.require(dependency.get('installation_root') == str(root), 'MC_RUNTIME_PROJECTION_DEPENDENCY_BINDING')
    planned = []; rows = {}
    for name, destination in PROJECTIONS.items():
        target = safe_path(root, root / destination); original = target.read_bytes()
        before = mc.hashlib.sha256(original).hexdigest()
        pin = source['files'].get(name)
        data = safe_path(root, root / name).read_bytes()
        mc.require(pin and mc.hashlib.sha256(data).hexdigest() == pin, 'MC_RUNTIME_PROJECTION_REVIEW_CHANGED')
        ast.parse(data, filename=name)
        if previous is not None and destination in previous['files']:
            row = previous['files'][destination]
            mc.require(row.get('source') == name and before == row.get('sha256'),
                       'MC_RUNTIME_PROJECTION_PREVIOUS_CHANGED')
        else:
            imported = dependency.get('files', {}).get(destination, {}).get('sha256')
            mc.require(before in {pin, BOOTSTRAP.get(destination), imported},
                       'MC_RUNTIME_PROJECTION_UNKNOWN_BASELINE')
        saved = safe_path(root, backup / 'runtime-projections' / destination)
        saved.parent.mkdir(parents=True, exist_ok=True)
        with saved.open('xb') as stream: stream.write(original)
        planned.append((target, original, data))
        rows[destination] = {'source': name, 'sha256': pin, 'before_sha256': before}
    if previous_bytes is not None:
        saved = safe_path(root, backup / 'runtime-projection-receipt.json')
        with saved.open('xb') as stream: stream.write(previous_bytes)
    record = {'schema_version': 1, 'installation_root': str(root),
              'source_snapshot_sha256': source['snapshot_sha256'], 'files': rows,
              'backup': backup.relative_to(root).as_posix(), 'services_started': False,
              'classification': 'REVIEWED_SOURCE_PROJECTION_NOT_GAME_OR_INFERENCE_ACCEPTANCE'}
    written = []
    try:
        for target, original, data in planned:
            written.append((target, original))
            replace(root, target, data)
        atomic_json(root, previous_path, record)
        validate(root, source)
        yield record
    except BaseException:
        for target, original in reversed(written): replace(root, target, original)
        if previous_bytes is None: previous_path.unlink(missing_ok=True)
        else: replace(root, previous_path, previous_bytes)
        raise


def project(root):
    root = Path(root).resolve()
    with operation(root, 'mc-reviewed-runtime-projection'):
        source = mc.installed_source_identity(root)
        backup = safe_path(root, root / '.setup/mc-runtime-projection-backups' / uuid.uuid4().hex)
        with applied(root, source, backup) as receipt: return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    print(json.dumps(project(parser.parse_args().root), ensure_ascii=False))
