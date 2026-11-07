"""Install the locked official DSH on native Windows; no global runtime changes."""
from pathlib import Path
import argparse
import json
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def discover(node=None, npm=None):
    """Explicit paths win; otherwise use the operator's native PATH runtime."""
    node = node or os.environ.get('ISAAC_NODE') or shutil.which('node')
    if not node or not Path(node).is_file():
        raise RuntimeError('Native Node >=24.9 is required; pass --node PATH_TO_NODE_EXE')
    node = Path(node).resolve()
    version = subprocess.check_output([str(node), '--version'], text=True).strip()
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', version)
    if not match or tuple(map(int, match.groups())) < (24, 9, 0):
        raise RuntimeError('Native Node >=24.9 is required; current version: '+version)
    npm = npm or os.environ.get('ISAAC_NPM_CLI')
    if not npm:
        candidates = [node.parent/'node_modules/npm/bin/npm-cli.js',
                      node.parent.parent/'node_modules/npm/bin/npm-cli.js']
        launcher = shutil.which('npm.cmd') or shutil.which('npm')
        if launcher:
            candidates.append(Path(launcher).parent/'node_modules/npm/bin/npm-cli.js')
        npm = next((p for p in candidates if p.is_file()), None)
    if not npm or not Path(npm).is_file() or Path(npm).name != 'npm-cli.js':
        raise RuntimeError('Native npm-cli.js is required; pass --npm PATH_TO_NPM_CLI_JS')
    return node, Path(npm).resolve(), version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node'); parser.add_argument('--npm')
    parser.add_argument('--check', action='store_true', help='Validate discovery without installing')
    args = parser.parse_args()
    node, npm, version = discover(args.node, args.npm)
    if args.check:
        print(json.dumps({'native_runtime_ok': True, 'node_version': version})); return
    env = dict(os.environ, PATH=str(node.parent)+os.pathsep+os.environ.get('PATH', ''),
               npm_config_cache=str(ROOT/'dsh-host/.npm-cache'), npm_config_update_notifier='false')
    if not (ROOT/'dsh-host/package-lock.json').is_file():
        raise RuntimeError('Missing DSH package-lock.json; restore the repository lockfile')
    subprocess.run([str(node), str(npm), 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--loglevel=warn'],
                   cwd=ROOT/'dsh-host', env=env, check=True)
    value = {'node': str(node), 'npm_cli': str(npm), 'node_version': version,
             'dsh_version': '0.2.2-rc.1', 'dsh_cli': str(ROOT/'dsh-host/node_modules/@deepseek-ai/dsh/lib/bin.js'),
             'install_scripts_enabled': False, 'native_windows_only': True}
    (ROOT/'dsh-host/runtime.json').write_text(json.dumps(value, indent=2), encoding='utf8')
    print(json.dumps({'installed': True, 'node_version': version, 'dsh_version': value['dsh_version']}))


if __name__ == '__main__': main()
