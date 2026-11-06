"""Stage integrity-checked extension sources beside the native DSH dependencies."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def stage(root: Path, runtime: Path):
    root, runtime = root.resolve(), runtime.resolve()
    runtime.relative_to(root)
    source_root = root / 'extensions/naimei-dsh'
    lock = json.loads((source_root / 'sources.lock.json').read_text('utf-8'))
    for item in lock['sources']:
        source = source_root / item['directory']
        for name, expected in item['files'].items():
            path = source / name
            path.resolve().relative_to(source.resolve())
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"EXTENSION_SOURCE_HASH:{item['id']}:{name}")
    for item in lock['sources']:
        source = source_root / item['directory']
        target = runtime / 'node_modules/@naimei' / item['id']
        target.mkdir(parents=True, exist_ok=True)
        for name in item['files']:
            output = target / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, output)
    receipt = {'contract': lock['contract'], 'source_lock_sha256': hashlib.sha256((source_root / 'sources.lock.json').read_bytes()).hexdigest(),
               'sources': [{'id': row['id'], 'commit': row['commit'], 'version': row['version']} for row in lock['sources']],
               'upstream_install_scripts_executed': False, 'model_weights_added_bytes': 0}
    (runtime / 'naimei-extensions-receipt.json').write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.project_root, args.runtime), ensure_ascii=False))
