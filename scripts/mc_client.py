"""Install pinned native Minecraft dependencies without launching a player or models."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error

from native_operation import atomic_json, operation, safe_path
import mc_deployment as deployment

LOCK = 'configs/mc-client.lock.json'
RECEIPT = '.setup/mc-client-installation.json'
PROGRESS = '.setup/mc-client-progress.json'
CLASSIFICATION = 'NATIVE_CLIENT_DEPENDENCIES_ONLY_NOT_GAMEPLAY_OR_APPLICATION_ACCEPTANCE'
HOSTS = {'files.pythonhosted.org', 'piston-meta.mojang.com', 'piston-data.mojang.com',
         'resources.download.minecraft.net', 'libraries.minecraft.net', 'meta.fabricmc.net', 'maven.fabricmc.net', 'maven2.fabricmc.net'}
LIMIT = 256 * 1024 * 1024


class ClientError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise ClientError(code)


def hashes(path):
    one, two = hashlib.sha1(), hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            one.update(block); two.update(block)
    return {'bytes': path.stat().st_size, 'sha1': one.hexdigest(), 'sha256': two.hexdigest()}


def url_allowed(url):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname in HOSTS and parsed.port in (None, 443)
            and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
            'MC_CLIENT_DOWNLOAD_ORIGIN')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError('MC_CLIENT_DOWNLOAD_REDIRECT')


def fetch(root, destination, pin):
    """Hash-check caches, stream into a sibling temporary file, then publish atomically."""
    destination = safe_path(root, destination)
    url_allowed(pin['url'])
    require(type(pin['bytes']) is int and 0 < pin['bytes'] <= LIMIT, 'MC_CLIENT_DOWNLOAD_SIZE')
    require(any(key in pin for key in ('sha1', 'sha256')), 'MC_CLIENT_DOWNLOAD_HASH_REQUIRED')
    for key, length in [('sha1', 40), ('sha256', 64)]:
        require(key not in pin or isinstance(pin[key], str) and re.fullmatch('[0-9a-f]{'+str(length)+'}', pin[key]),
                'MC_CLIENT_DOWNLOAD_HASH')
    def matches(actual):
        return actual['bytes'] == pin['bytes'] and all(actual[key] == pin[key] for key in ('sha1', 'sha256') if key in pin)
    if destination.is_file():
        actual = hashes(destination)
        if matches(actual):
            return {**actual, 'downloaded': False}
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=destination.name+'.', suffix='.part', dir=destination.parent)
    temporary = Path(name)
    try:
        count = 0
        opener = urllib.request.build_opener(NoRedirect())
        request = urllib.request.Request(pin['url'], headers={'User-Agent': 'Ai-Talk-Streamer-native-mc/1'})
        with os.fdopen(descriptor, 'wb') as output:
            with opener.open(request, timeout=30) as response:
                require(response.status == 200, 'MC_CLIENT_DOWNLOAD_STATUS')
                while block := response.read(min(1024*1024, pin['bytes']-count+1)):
                    count += len(block)
                    require(count <= pin['bytes'], 'MC_CLIENT_DOWNLOAD_SIZE')
                    output.write(block)
            output.flush(); os.fsync(output.fileno())
        actual = hashes(temporary)
        require(matches(actual), 'MC_CLIENT_DOWNLOAD_HASH_MISMATCH')
        safe_path(root, destination); os.replace(temporary, destination)
        return {**actual, 'downloaded': True}
    except (urllib.error.URLError, TimeoutError) as error:
        raise ClientError('MC_CLIENT_DOWNLOAD_UNAVAILABLE') from error
    finally:
        temporary.unlink(missing_ok=True)


def download_window(home, requests, threads_count):
    """Keep only active work submitted; a failed batch never drains a huge queue."""
    requests = iter(requests)
    limit = min(8, max(1, threads_count))
    with ThreadPoolExecutor(max_workers=limit) as workers:
        pending = {}
        def submit():
            request = next(requests, None)
            if request is not None:
                entry, pin = request
                pending[workers.submit(fetch, home, entry.dst, pin)] = entry
        for _ in range(limit):
            submit()
        try:
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                # Inspect the entire completed batch before submitting more work.
                completed = [(pending.pop(future), future.result()) for future in done]
                yield from completed
                for _ in completed:
                    submit()
        finally:
            for future in pending:
                future.cancel()


def load_lock(root):
    lock = deployment.read(deployment.inside(root, LOCK))
    require(lock['schema_version'] == 1 and lock['minecraft'] == '1.21.1'
            and lock['fabric_loader'] == '0.16.14' and lock['fabric_api'] == '0.116.6+1.21.1'
            and lock['platform'] == 'win32' and lock['architecture'] == 'AMD64'
            and lock['java']['major'] == 21 and lock['java']['component'] == 'java-runtime-delta'
            and lock['home'] == 'runtime/minecraft/mc-1.21.1-fabric-0.16.14'
            and lock['work'] == lock['home']+'/work', 'MC_CLIENT_LOCK')
    require(set(lock['documents']) == {'minecraft', 'assets', 'fabric', 'java'}
            and lock['resolver']['version'] == '4.4.1'
            and lock['resolver']['sha256'] == '82435214f4745fb0b5a6dbbb065b1b22723f5805d2468a74c896b33733eb2de6',
            'MC_CLIENT_RESOLVER_LOCK')
    return lock


def base_result():
    return {'classification': CLASSIFICATION, 'game_started': False, 'models_loaded': False,
            'services_started': False, 'automatic_input_authorized': False,
            'full_application_prepared': False, 'real_acceptance_passed': 0}


def status(root):
    root = Path(root).resolve(); lock = load_lock(root)
    record_path = deployment.inside(root, RECEIPT)
    if not record_path.is_file():
        return {**base_result(), 'ok': False, 'code': 'MC_CLIENT_NOT_INSTALLED'}
    record = deployment.read(record_path, limit=8*1024*1024)
    require(record.get('schema_version') == 1 and record.get('installation_root') == str(root)
            and record.get('lock_sha256') == deployment.sha(deployment.inside(root, LOCK))
            and record.get('home') == lock['home'], 'MC_CLIENT_INSTALLATION_BINDING')
    files = record.get('files', [])
    require(isinstance(files, list) and 0 < len(files) <= 20000
            and len({row['path'].casefold() for row in files}) == len(files), 'MC_CLIENT_INSTALLATION_FILES')
    names = {row['path'] for row in files}
    required = {record.get('java'), *record.get('classpath', []), *record.get('native_libraries', []),
                lock['work']+'/mods/fabric-api-'+lock['fabric_api']+'.jar'}
    require(record.get('main_class') == 'net.fabricmc.loader.impl.launch.knot.KnotClient'
            and isinstance(record.get('classpath'), list) and bool(record['classpath'])
            and required.issubset(names), 'MC_CLIENT_REQUIRED_FILE_UNVERIFIED')
    for row in files:
        require(row['path'].startswith(lock['home']+'/'), 'MC_CLIENT_INSTALLATION_PATH')
        path = deployment.inside(root, row['path'])
        require(path.is_file() and hashes(path)['sha256'] == row['sha256'] and path.stat().st_size == row['bytes'],
                'MC_CLIENT_INSTALLED_FILE_CHANGED')
    return {**base_result(), 'ok': True, 'files': len(files), 'home': lock['home'],
            'minecraft': lock['minecraft'], 'fabric_loader': lock['fabric_loader'],
            'java_version': record['java_version'], 'installation_receipt': RECEIPT,
            'bridge_and_executor_installed': False, 'player_identity_configured': False}


def prepare(root):
    root = Path(root).resolve(); lock = load_lock(root)
    require(sys.platform == 'win32' and platform.machine().upper() == 'AMD64', 'MC_CLIENT_NATIVE_WINDOWS_X64_REQUIRED')
    deployment.load_profile(root)
    # Source installation is verified independently from the inherited live inference installation.
    source = deployment.source_identity(root)
    with operation(root, 'mc-client-prepare'):
        home = deployment.inside(root, lock['home']); work = deployment.inside(root, lock['work'])
        home.mkdir(parents=True, exist_ok=True); work.mkdir(parents=True, exist_ok=True)
        progress = {**base_result(), 'ok': False, 'phase': 'PINNED_METADATA', 'downloaded_files': 0,
                    'started_at': datetime.now(timezone.utc).isoformat()}
        def report(phase, **values):
            progress.update(phase=phase, **values, updated_at=datetime.now(timezone.utc).isoformat())
            atomic_json(root, root/PROGRESS, progress)
        report('PINNED_METADATA')
        try:
            return _install(root, home, work, lock, source, report)
        except BaseException as error:
            report('FAILED', code=str(error) if isinstance(error, ClientError) else 'MC_CLIENT_PREPARATION_INCOMPLETE',
                   failure_type=type(error).__name__)
            raise


def _install(root, home, work, lock, source, report):
    records = {}
    def capture(path, pin):
        report('PINNED_FILES', current_file=path.relative_to(root).as_posix())
        path = safe_path(home, path); actual = fetch(home, path, pin)
        row = {'path': path.relative_to(root).as_posix(), **actual}
        records[row['path']] = row
        return row
    resolver = lock['resolver']; wheel = home/'installer'/resolver['filename']
    capture(wheel, resolver)
    for name, module in list(sys.modules.items()):
        if name == 'portablemc' or name.startswith('portablemc.'):
            location = getattr(module, '__file__', '')
            require(isinstance(location, str) and os.path.normcase(location).startswith(os.path.normcase(str(wheel))+os.sep),
                    'MC_CLIENT_RESOLVER_ALREADY_IMPORTED')
    sys.path.insert(0, str(wheel))
    from portablemc.fabric import FabricVersion
    from portablemc.standard import Context, Watcher
    from portablemc.download import DownloadList, DownloadResultProgress
    import portablemc.fabric as fabric
    import portablemc.standard as standard
    documents = {}
    for name, pin in lock['documents'].items():
        path = home/'installer'/(name+'.json'); capture(path, pin)
        documents[name] = json.loads(path.read_bytes())
    mc, fm, java = (documents[name] for name in ('minecraft', 'fabric', 'java'))
    require(mc.get('id') == lock['minecraft'] and fm.get('id') == 'fabric-loader-'+lock['fabric_loader']+'-'+lock['minecraft']
            and fm.get('inheritsFrom') == lock['minecraft']
            and fm.get('mainClass') == 'net.fabricmc.loader.impl.launch.knot.KnotClient'
            and mc.get('javaVersion') == {'component': lock['java']['component'], 'majorVersion': 21}, 'MC_CLIENT_METADATA_VERSION')
    require(all(row.get('type') in {'file', 'directory'} for row in java['files'].values()), 'MC_CLIENT_JVM_LINK_NOT_SUPPORTED')
    version_id = 'fabric-'+lock['minecraft']+'-'+lock['fabric_loader']
    seeds = {home/'versions'/version_id/(version_id+'.json'): fm,
             home/'versions'/lock['minecraft']/(lock['minecraft']+'.json'): mc,
             home/'assets/indexes'/(mc['assets']+'.json'): documents['assets'],
             home/'jvm'/(lock['java']['component']+'.json'): {**java, 'version': lock['java']['version']}}
    for path, value in seeds.items():
        safe_path(home, path); atomic_json(root, path, value)
        row = {'path': path.relative_to(root).as_posix(), **hashes(path), 'downloaded': False}
        records[row['path']] = row
    def reject_metadata(*args, **kwargs):
        raise ClientError('MC_CLIENT_UNPINNED_METADATA_REQUEST')
    old_http = standard.http_request, fabric.http_request
    standard.http_request = fabric.http_request = reject_metadata
    class VerifiedDownloads(DownloadList):
        def add(self, entry, *, verify=False):
            safe_path(home, entry.dst); url_allowed(entry.url)
            pin = lock['fabric_libraries'].get(entry.url)
            if pin:
                entry.size, entry.sha1 = pin['bytes'], pin['sha1']
            require(type(entry.size) is int and 0 < entry.size <= LIMIT and isinstance(entry.sha1, str)
                    and re.fullmatch('[0-9a-f]{40}', entry.sha1), 'MC_CLIENT_UNPINNED_ARTIFACT')
            expected = {'url': entry.url, 'bytes': entry.size, 'sha1': entry.sha1, **(pin or {})}
            if entry.dst.is_file():
                actual = hashes(entry.dst)
                if all(actual[k] == expected[k] for k in ('bytes', 'sha1')) and (not pin or actual['sha256'] == pin['sha256']):
                    records[entry.dst.relative_to(root).as_posix()] = {'path': entry.dst.relative_to(root).as_posix(), **actual, 'downloaded': False}
                    return
            super().add(entry, verify=False)
        def download(self, threads_count, *, partial_progress=False):
            needed = sum(item.entry.size for item in self.entries)
            require(shutil.disk_usage(home).free > needed + 128*1024*1024, 'MC_CLIENT_DISK_SPACE')
            last = 0
            requests = ((item.entry, {'url': item.entry.url, 'bytes': item.entry.size, 'sha1': item.entry.sha1,
                         **lock['fabric_libraries'].get(item.entry.url, {})}) for item in self.entries)
            for count, (entry, actual) in enumerate(download_window(home, requests, threads_count), 1):
                name = entry.dst.relative_to(root).as_posix(); records[name] = {'path': name, **actual}
                if time.monotonic()-last > 3 or count == len(self.entries):
                    report('DOWNLOADING', completed_files=count, required_files=len(self.entries),
                           downloaded_files=sum(row['downloaded'] for row in records.values()))
                    last = time.monotonic()
                yield count, DownloadResultProgress(0, entry, actual['bytes'], 0, True)
    class InstallOnly(FabricVersion):
        def _resolve_env(self, watcher):
            # Do not construct an offline identity, start a process, or call Environment.run().
            return SimpleNamespace(java=self._jvm_path, main_class=self._metadata['mainClass'],
                                   classpath=[*self._class_libs, self._jar_path], natives=self._native_libs)
    try:
        version = InstallOnly.with_fabric(lock['minecraft'], lock['fabric_loader'], context=Context(home, work))
        version.manifest.data = {'latest': {'release': lock['minecraft'], 'snapshot': lock['minecraft']}, 'versions': []}
        version._dl = VerifiedDownloads()
        report('RESOLVING_PINNED_FILES')
        environment = version.install(watcher=Watcher())
    finally:
        standard.http_request, fabric.http_request = old_http
        sys.path.remove(str(wheel))
    api = work/'mods'/('fabric-api-'+lock['fabric_api']+'.jar'); capture(api, lock['api_mod'])
    # PortableMC selects javaw.exe on Windows; readiness uses the console sibling
    # from the same verified Mojang runtime so version output can be checked.
    java_path = safe_path(home, environment.java.with_name('java.exe'))
    require(java_path.is_file() and java_path.name.lower() == 'java.exe', 'MC_CLIENT_JAVA_MISSING')
    for path in [*environment.classpath, *environment.natives, java_path]:
        require(path is not None and path.relative_to(root).as_posix() in records, 'MC_CLIENT_REQUIRED_FILE_UNVERIFIED')
        require(hashes(path)['sha256'] == records[path.relative_to(root).as_posix()]['sha256'],
                'MC_CLIENT_REQUIRED_FILE_CHANGED')
    text = subprocess.check_output([str(java_path), '-XshowSettings:properties', '-version'],
        cwd=home, stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=20,
        creationflags=0x08000000 if os.name == 'nt' else 0).decode('utf-8', errors='replace')
    match = re.search(r'(?:openjdk|java) version "(21(?:\.[0-9]+)*(?:[+_-][^"\s]+)?)"', text)
    require(match and re.search(r'os.arch\s*=\s*amd64\s*$', text, re.M), 'MC_CLIENT_JAVA_VERSION')
    record = {**base_result(), 'schema_version': 1, 'installation_root': str(root), 'home': lock['home'],
              'lock_sha256': deployment.sha(root/LOCK), 'source_snapshot_sha256_at_installation': source['snapshot_sha256'],
              'files': sorted(records.values(), key=lambda row: row['path']), 'java_version': match[1],
              'java': java_path.relative_to(root).as_posix(), 'main_class': environment.main_class,
              'classpath': [p.relative_to(root).as_posix() for p in environment.classpath],
              'native_libraries': [p.relative_to(root).as_posix() for p in environment.natives],
              'bridge_and_executor_installed': False, 'player_identity_configured': False,
              'installed_at': datetime.now(timezone.utc).isoformat()}
    atomic_json(root, root/RECEIPT, record)
    result = status(root)
    report('DEPENDENCIES_INSTALLED', ok=True, files=result['files'])
    return result
