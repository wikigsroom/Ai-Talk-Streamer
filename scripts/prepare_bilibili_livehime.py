"""Prepare the official native Bilibili Livehime in the project, without OBS.

Extracts the signed installer; does not execute its setup tasks, install drivers,
log in, accept account terms, or start a public broadcast.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import io
import importlib.util
import json
import os
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_signature_spec = importlib.util.spec_from_file_location('platform_signature', ROOT / 'scripts/prepare_douyin_companion.py')
_signature_module = importlib.util.module_from_spec(_signature_spec)
_signature_spec.loader.exec_module(_signature_module)
signature = _signature_module.signature
VERSION_URL = 'https://api.live.bilibili.com/xlive/app-blink/v1/liveVersionInfo/getHomePageLiveVersion?system_version=2'
UNPACK_URL = ('https://api.github.com/repos/jrathlev/InnoUnpacker-Windows-GUI/contents/'
              'innounp-2/bin/innounp-270.zip?ref=07ee3b1a05a26fa27a0efe110fe78dfa72c06c71')
UNPACK_SHA256 = 'd5514cac741f12ca94f642eacd30d514d820dce016e4d016325413df472c34ea'


def request(url):
    return urllib.request.Request(url, headers={'User-Agent': 'Ai-Talk-Streamer/1.0',
                                                'Referer': 'https://live.bilibili.com/liveHime'})


def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with urllib.request.urlopen(request(url), timeout=45) as response, target.with_suffix('.part').open('wb') as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        target.with_suffix('.part').replace(target)
    return target


def verified_signature(path):
    result = signature(path)
    if result['status'] != 'Valid' or not any(word in result['publisher'].lower() for word in ('bilibili', 'huandian', '幻电')):
        raise RuntimeError('Official Livehime Authenticode signature is not valid')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', help='Optional existing HTTP proxy')
    parser.add_argument('--version-file', type=Path, help='Previously downloaded official API response, under the project')
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Native Windows is required')
    if args.proxy:
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({'http': args.proxy, 'https': args.proxy})))
    if args.version_file:
        source = args.version_file.resolve()
        if not source.is_relative_to(ROOT):
            raise ValueError('Version response must be inside the project')
        metadata = json.loads(source.read_text(encoding='utf-8-sig'))
    else:
        with urllib.request.urlopen(request(VERSION_URL), timeout=25) as response:
            metadata = json.load(response)
    if metadata.get('code') != 0:
        raise RuntimeError('Official Livehime version API failed')
    info = metadata['data']
    url = info['download_url']
    if not url.startswith('https://dl.hdslb.com/bili/bililive/win/') or not url.endswith('.exe'):
        raise ValueError('Unexpected official installer URL')
    installer = download(url, ROOT / 'downloads/platforms' / url.rsplit('/', 1)[1])
    raw = installer.read_bytes()
    if len(raw) != int(info['file_size']) or hashlib.md5(raw).hexdigest() != info['file_md5'].lower():
        raise RuntimeError('Installer differs from the official size/MD5 metadata')
    signed = verified_signature(installer)
    unpacker = ROOT / 'tools/innounp/innounp.exe'
    archive = ROOT / 'downloads/platforms/innounp-270.zip'
    if not archive.exists():
        with urllib.request.urlopen(request(UNPACK_URL), timeout=30) as response:
            archive.write_bytes(base64.b64decode(json.load(response)['content']))
    packed = archive.read_bytes()
    if hashlib.sha256(packed).hexdigest() != UNPACK_SHA256:
        raise RuntimeError('Pinned InnoUnpacker checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(packed)) as package:
        for name in package.namelist():
            destination = (unpacker.parent / name).resolve()
            if not destination.is_relative_to(unpacker.parent.resolve()):
                raise ValueError('Unpacker archive leaves its directory')
            if name.endswith('/'):
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(package.read(name))
    output = ROOT / 'outputs/platforms/setup'
    output.mkdir(parents=True, exist_ok=True)
    app = ROOT / 'tools/bilibili-livehime/app'
    app.mkdir(parents=True, exist_ok=True)
    with (output / 'bilibili-livehime-extract.log').open('w', encoding='utf-8') as log:
        subprocess.run([str(unpacker), '-x', '-y', '-d' + str(app), str(installer)], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, timeout=180,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    candidates = [p for p in app.rglob('*.exe') if p.name.lower() == 'livehime.exe']
    if len(candidates) != 1:
        raise RuntimeError('Expected one official Livehime.exe in the extracted payload')
    entry = candidates[0]
    receipt = {'prepared': True, 'version': info['curr_version'], 'official_version_url': VERSION_URL,
               'installer_url': url, 'installer_bytes': len(raw), 'official_md5_verified': True,
               'installer_sha256': hashlib.sha256(raw).hexdigest(), 'installer_signature': signed,
               'application': entry.relative_to(ROOT).as_posix(), 'application_signature': verified_signature(entry),
               'unpacker_version': '2.70.1', 'unpacker_archive_sha256': UNPACK_SHA256,
               'account_login': False, 'public_broadcast_started': False, 'obs_required': False}
    (output / 'bilibili-livehime.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n',
                                              encoding='utf-8', newline='\n')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
