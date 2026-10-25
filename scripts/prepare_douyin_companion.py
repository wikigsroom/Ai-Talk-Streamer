"""Extract the official Windows Live Companion into the project; no global install.

Downloads are retained with SHA-256 receipts. This does not log in, install
drivers, accept account terms, or start a public broadcast.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '26.05'


def download(url, target):
    if target.exists() and target.stat().st_size > 100000:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'Ai-Talk-Streamer/1.0'})
    with urllib.request.urlopen(request, timeout=40) as response, target.with_suffix('.part').open('wb') as output:
        while block := response.read(1024 * 1024):
            output.write(block)
    target.with_suffix('.part').replace(target)


def signature(path):
    # The path is an existing local file beneath ROOT, not untrusted shell input.
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Signature target leaves the project')
    escaped = str(path).replace("'", "''")
    command = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();$s=Get-AuthenticodeSignature -LiteralPath '" + escaped + "';$s.Status.ToString();if($s.SignerCertificate){$s.SignerCertificate.Subject.ToString()}"
    value = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                    encoding='utf-8', errors='replace', timeout=40,
                                    creationflags=subprocess.CREATE_NO_WINDOW).strip().splitlines()
    return {'status': value[0], 'publisher': '\n'.join(value[1:])}


def run_extract(executable, archive, destination, log):
    destination = destination.resolve()
    if not destination.is_relative_to(ROOT):
        raise ValueError('Extraction destination leaves the project')
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(executable), 'x', str(archive), '-o' + str(destination), '-y'],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Archive extraction failed; inspect the project setup log')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', help='Optional existing HTTP proxy')
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('This helper prepares the native Windows client')
    if args.proxy:
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({'http': args.proxy, 'https': args.proxy})))
    folder = ROOT / 'outputs/platforms/setup'
    folder.mkdir(parents=True, exist_ok=True)
    downloads = ROOT / 'downloads/platforms'
    installer = downloads / 'douyin-companion.exe'
    download('https://streamingtool.douyin.com/api/invoke/download?arch=x64&isAutoUpdate=1', installer)
    signed = signature(installer)
    if signed['status'] != 'Valid' or 'Douyin Vision' not in signed['publisher']:
        raise RuntimeError('The official Companion installer signature is not valid')
    seven = ROOT / 'tools/7zip/7z.exe'
    with (folder / 'douyin-extract.log').open('w', encoding='utf-8') as log:
        if not seven.exists():
            tiny, full = downloads / '7zr.exe', downloads / '7z2605-x64.exe'
            download('https://github.com/ip7z/7zip/releases/download/' + VERSION + '/7zr.exe', tiny)
            download('https://github.com/ip7z/7zip/releases/download/' + VERSION + '/7z2605-x64.exe', full)
            run_extract(tiny, full, seven.parent, log)
        if not seven.exists():
            raise RuntimeError('The portable 7-Zip binary was not extracted')
        unpacked = ROOT / 'tools/douyin-companion/installer'
        app = ROOT / 'tools/douyin-companion/app'
        run_extract(seven, installer, unpacked, log)
        payloads = [p for p in unpacked.rglob('*.7z') if p.name in {'app-64.7z', 'app.7z'}]
        if len(payloads) == 1:
            run_extract(seven, payloads[0], app, log)
        else:
            app = unpacked
    candidates = [p for p in app.rglob('*.exe') if p.name.lower() in {'streamingtool.exe', 'douyinlivestudio.exe', '直播伴侣.exe'}]
    if len(candidates) != 1:
        raise RuntimeError('Select the actual signed application from tools/douyin-companion; no application was launched')
    entry = candidates[0]
    application_signature = signature(entry)
    if application_signature['status'] != 'Valid' or 'Douyin Vision' not in application_signature['publisher']:
        raise RuntimeError('The extracted application signature is not valid')
    receipt = {'prepared': True, 'installer_signature': signed,
               'installer_sha256': hashlib.sha256(installer.read_bytes()).hexdigest(),
               'application': entry.relative_to(ROOT).as_posix(), 'application_signature': application_signature,
               'account_login': False, 'public_broadcast_started': False,
               'seven_zip_version': VERSION}
    (folder / 'douyin-companion.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
