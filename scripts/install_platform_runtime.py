"""Install CPU-only platform adapters in this project's native Windows runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import venv
import urllib.request

BLIVEDM_COMMIT = '3bf17fe862b8c2fc6bc04c81c3f0c5db95de93d6'
BLIVEDM_SOURCE = 'https://codeload.github.com/xfgryujk/blivedm/zip/'+BLIVEDM_COMMIT
ROOT = Path(__file__).resolve().parents[1]


def run(args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True, env=install_environment())


def install_environment():
    env = os.environ.copy()
    for key, folder in [('TEMP', 'cache/platforms-install/tmp'),
                        ('TMP', 'cache/platforms-install/tmp'),
                        ('PIP_CACHE_DIR', 'cache/platforms-install/pip'),
                        ('npm_config_cache', 'cache/platforms-install/npm')]:
        target = ROOT / folder
        target.mkdir(parents=True, exist_ok=True)
        env[key] = str(target)
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--proxy', default='')
    args = parser.parse_args()
    os.environ.update(install_environment())
    if args.proxy:
        for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
            os.environ[name] = args.proxy
        os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
    runtime = ROOT/'runtime/platforms'
    python = runtime/'Scripts/python.exe'
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(runtime)
    pip_args = ['--proxy', args.proxy] if args.proxy else []
    # Official GitHub source, pinned to a full commit. Never install the
    # unrelated PyPI package called blivedm. The archive avoids requiring Git.
    folder = ROOT/'.setup/platforms'; folder.mkdir(parents=True, exist_ok=True)
    source = folder/('blivedm-'+BLIVEDM_COMMIT+'.zip')
    if not source.exists():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {'http': args.proxy, 'https': args.proxy} if args.proxy else {}))
        request = urllib.request.Request(BLIVEDM_SOURCE, headers={'User-Agent': 'Ai-Talk-Streamer setup'})
        with opener.open(request, timeout=45) as response:
            content = response.read(16*1024*1024+1)
        if len(content) > 16*1024*1024:
            raise RuntimeError('Unexpected blivedm source archive size')
        temporary = source.with_suffix('.zip.part')
        temporary.write_bytes(content); temporary.replace(source)
    run([python, '-m', 'pip', 'install', *pip_args, source])
    module = next((path for path in [ROOT/'tools/dsh-browser/node_modules/playwright-core/package.json',
                                    ROOT/'node_modules/playwright-core/package.json'] if path.is_file()),
                  ROOT/'tools/dsh-browser/node_modules/playwright-core/package.json')
    if not module.exists():
        node = ROOT/'tools/node/node-v24.22.1-win-x64/node.exe'
        if not node.is_file():
            found = shutil.which('node')
            if not found:
                raise RuntimeError('Native Node.js is required to install playwright-core')
            node = Path(found)
        npm = node.parent/'node_modules/npm/bin/npm-cli.js'
        if not npm.is_file():
            raise RuntimeError('Native npm CLI is missing: '+str(npm))
        run([node, npm, 'install', '--prefix', ROOT/'tools/dsh-browser',
             '--ignore-scripts', '--save-exact', 'playwright-core@1.59.1'])
    freeze = subprocess.check_output([str(python), '-m', 'pip', 'freeze'], cwd=ROOT, text=True)
    check = subprocess.check_output([str(python), '-c', 'import blivedm;print(blivedm.__version__)'], cwd=ROOT, text=True).strip()
    receipt = {'installed': True, 'native_windows': True, 'gpu_dependencies_added': False,
               'blivedm_commit': BLIVEDM_COMMIT, 'blivedm_version': check,
               'blivedm_source_url': BLIVEDM_SOURCE,
               'blivedm_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'playwright_core': json.loads(module.read_text())['version'],
               'pip_freeze': freeze.splitlines()}
    (folder/'runtime.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
