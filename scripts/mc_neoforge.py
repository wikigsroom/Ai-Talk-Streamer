"""Use the supplied native NeoForge pack in a separate project-owned game directory.

No launcher accounts, tokens, command history or saves are imported. The original
319 mod files remain unchanged. This flow verifies a real offline player's login;
it does not establish inference preparation or authorize the survival executor.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

from native_operation import OperationError, atomic_json, safe_path, operation
from native_windows_process import NativeJob

LOCK = 'configs/mc-neoforge-client.lock.json'
BRIDGE_LOCK = 'configs/mc-neoforge-bridge.lock.json'
BRIDGE_CORE = 'game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core'
BRIDGE_SCHEMA = 'docs/technical/mc-live-v1/contracts/game.schema.json'
HOME = 'runtime/minecraft/mc-friends-s1-neoforge-21.1.248'
RECEIPT = '.setup/mc-neoforge-installation.json'
BUILD_RECEIPT = '.setup/mc-neoforge-probe-build.json'
CONTROLLER_JAR = HOME + '/work/mods/ai-talk-streamer-native-neoforge-0.1.0.jar'
COPY_DIRS = ('mods', 'config', 'defaultconfigs', 'configureddefaults', 'kubejs',
             'resourcepacks', 'patchouli_books', 'blueprints', 'schematics', 'shaderpacks')
MODULES = {'bootstraplauncher-2.0.2.jar', 'securejarhandler-3.0.8.jar',
           'asm-commons-9.10.1.jar', 'asm-util-9.10.1.jar', 'asm-analysis-9.10.1.jar',
           'asm-tree-9.10.1.jar', 'asm-9.10.1.jar', 'JarJarFileSystems-0.4.1.jar'}


def require(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def offline_uuid(name):
    require(isinstance(name, str) and re.fullmatch('[A-Za-z0-9_]{1,16}', name), 'MC_OFFLINE_USERNAME')
    return str(uuid.UUID(bytes=hashlib.md5(('OfflinePlayer:' + name).encode('utf-8')).digest(), version=3))


def allowed(rules):
    if not rules:
        return True
    result = False
    for rule in rules:
        system = rule.get('os', {})
        matches = system.get('name', 'windows') == 'windows'
        if 'arch' in system:
            matches = matches and re.fullmatch(system['arch'], 'amd64') is not None
        if system.get('version'):
            matches = matches and re.search(system['version'], '10.0') is not None
        if rule.get('features'):
            matches = False
        if matches:
            result = rule['action'] == 'allow'
    return result


def package(root, source):
    root = Path(root).resolve(); source = Path(source).resolve()
    require(source.is_dir() and not source.is_relative_to(root / 'runtime'), 'MC_NEOFORGE_SOURCE')
    lock = read(root / LOCK)
    require(lock['username'] == 'NAIMEI' and lock['authentication'] == 'offline'
            and lock['minecraft'] == '1.21.1' and lock['neoforge'] == '21.1.248'
            and lock['mod_count'] == 319, 'MC_NEOFORGE_LOCK')
    for entry in lock['files']:
        relative = Path(entry['path'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'MC_NEOFORGE_PIN_PATH')
        path = source / relative
        require(path.is_file() and path.resolve().is_relative_to(source)
                and path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'],
                'MC_NEOFORGE_SUPPLIED_FILE_CHANGED:' + relative.as_posix())
    instance = source / '.minecraft/versions' / lock['version_id']
    names = {x.name for x in (instance / 'mods').iterdir() if x.is_file()}
    prefix = '.minecraft/versions/' + lock['version_id'] + '/mods/'
    expected = {Path(x['path']).name for x in lock['files'] if x['path'].startswith(prefix)}
    require(len(expected) == 319 and names == expected, 'MC_NEOFORGE_MOD_SET_CHANGED')
    return lock, instance


def prepare(root, source):
    root = Path(root).resolve(); source = Path(source).resolve()
    lock, instance = package(root, source)
    work = safe_path(root, root / HOME / 'work'); work.mkdir(parents=True, exist_ok=True)
    with operation(root, 'mc-neoforge-prepare'):
        # The pack is immutable input; only known static content goes into our own instance.
        for name in COPY_DIRS:
            origin = instance / name
            if origin.is_dir():
                for item in origin.rglob('*'):
                    require(not item.is_symlink() and item.resolve().is_relative_to(origin.resolve()), 'MC_NEOFORGE_SOURCE_LINK')
                shutil.copytree(origin, work / name, dirs_exist_ok=True)
        natives = instance / (lock['version_id'] + '-natives')
        shutil.copytree(natives, work.parent / 'natives', dirs_exist_ok=True)
        # ConfiguredDefaults can replace options on its first run. Apply our own
        # first-run settings to that copied template as well as the fresh instance.
        # The supplied defaults are a partial modern-keyboard template without
        # a data version. As a complete options file they would be treated as
        # pre-LWJGL3 data, fail integer key conversion and discard our settings.
        first_run = {'version': '3955', 'onboardAccessibility': 'false', 'skipMultiplayerWarning': 'true',
            'tutorialStep': 'none', 'renderDistance': '8', 'simulationDistance': '6',
            'maxFps': '30', 'soundCategory_master': '0.0', 'rawMouseInput': 'false'}
        defaults = work / 'configureddefaults/options.txt'
        content = defaults.read_text(encoding='utf-8-sig') if defaults.exists() else 'version:3955\n'
        values = dict(line.split(':', 1) for line in content.splitlines() if ':' in line)
        values.update(first_run)
        initial = ''.join(key + ':' + value + '\n' for key, value in values.items())
        if defaults.exists():
            defaults.write_text(initial, encoding='utf-8')
        # Account caches, old servers and player settings never enter this directory.
        options = work / 'options.txt'
        if not options.exists():
            options.write_text(initial, encoding='utf-8')
        bridge = work / 'config/ai-talk-streamer-bridge.json'
        if not bridge.exists():
            atomic_json(root, bridge, {'enabled': True, 'endpoint': 'ws://127.0.0.1:3092/api/dsh/game/bridge'})
        record = {'schema_version': 1, 'classification': 'NEOFORGE_PLAYER_INTEGRATION_NOT_FULL_APPLICATION_PREPARATION',
            'source': str(source), 'installation_root': str(root), 'lock_sha256': sha(root / LOCK),
            'work': str(work), 'username': lock['username'], 'offline_uuid': offline_uuid(lock['username']),
            'mod_count': len([p for p in (work / 'mods').glob('*.jar') if p.name != 'ai-talk-streamer-native-neoforge-0.1.0.jar']), 'automatic_input_authorized': False,
            'full_application_prepared': False, 'created_at': datetime.now(timezone.utc).isoformat()}
        require(record['mod_count'] == 319, 'MC_NEOFORGE_TARGET_MOD_SET_CHANGED')
        atomic_json(root, root / RECEIPT, record)
    return record


def java_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def runtime_files(root):
    """Read the actual installed NeoForge dependencies without starting a game.

    Source-pack files are read in place. Only immutable client dependencies enter
    the preparation inventory; player settings, generated configs, logs, saves,
    account caches and live game journals are never treated as immutable assets.
    This is one prerequisite of application preparation, not AUTO authority.
    """
    root = Path(root).resolve()
    files = {}
    def capture(base, path, expected=None, size=None):
        path = safe_path(base, path)
        require(path.is_file() and (size is None or path.stat().st_size == size),
                'MC_NEOFORGE_RUNTIME_FILE_MISSING_OR_SIZE')
        actual = sha(path)
        require(expected is None or actual == expected, 'MC_NEOFORGE_RUNTIME_HASH')
        key = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        files[key] = actual
        return path

    record = read(capture(root, root / RECEIPT))
    require(isinstance(record, dict) and record.get('schema_version') == 1
            and record.get('classification') == 'NEOFORGE_PLAYER_INTEGRATION_NOT_FULL_APPLICATION_PREPARATION'
            and record.get('installation_root') == str(root)
            and record.get('username') == 'NAIMEI'
            and record.get('offline_uuid') == offline_uuid('NAIMEI')
            and record.get('mod_count') == 319
            and record.get('automatic_input_authorized') is False
            and record.get('full_application_prepared') is False,
            'MC_NEOFORGE_RUNTIME_BINDING')
    source_name = record.get('source')
    require(isinstance(source_name, str) and Path(source_name).is_absolute(), 'MC_NEOFORGE_RUNTIME_SOURCE')
    source = Path(source_name)
    require(source == source.resolve(), 'MC_NEOFORGE_RUNTIME_SOURCE_LINK')
    lock, instance = package(root, source)
    require(isinstance(record.get('lock_sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', record['lock_sha256']), 'MC_NEOFORGE_RUNTIME_LOCK_HASH')
    capture(root, root / LOCK, record['lock_sha256'])
    work = safe_path(root, root / HOME / 'work')
    require(record.get('work') == str(work), 'MC_NEOFORGE_RUNTIME_WORK')
    for pin in lock['files']:
        capture(source, source / pin['path'], pin['sha256'], pin['bytes'])

    mod_prefix = '.minecraft/versions/' + lock['version_id'] + '/mods/'
    mods = {Path(pin['path']).name: pin for pin in lock['files'] if pin['path'].startswith(mod_prefix)}
    installed = safe_path(root, work / 'mods')
    entries = list(installed.iterdir())
    require(len(mods) == 319 and {p.name for p in entries} == set(mods) | {Path(CONTROLLER_JAR).name}
            and all(p.is_file() for p in entries), 'MC_NEOFORGE_TARGET_MOD_SET_CHANGED')
    for name, pin in mods.items():
        capture(root, installed / name, pin['sha256'], pin['bytes'])

    native_prefix = '.minecraft/versions/' + lock['version_id'] + '/' + lock['version_id'] + '-natives/'
    natives = {pin['path'][len(native_prefix):]: pin for pin in lock['files'] if pin['path'].startswith(native_prefix)}
    require(bool(natives), 'MC_NEOFORGE_RUNTIME_NATIVES')
    native_home = safe_path(root, work.parent / 'natives')
    actual_natives = {p.relative_to(native_home).as_posix() for p in native_home.rglob('*') if p.is_file()}
    require(actual_natives == set(natives), 'MC_NEOFORGE_RUNTIME_NATIVE_SET')
    for name, pin in natives.items():
        capture(root, native_home / name, pin['sha256'], pin['bytes'])

    # The supplied lock pins java.exe. Bind the rest of that actual JRE as well,
    # so a later DLL/module change invalidates preparation even with the same exe.
    jre = instance / 'runtime/java21'
    require(jre.is_dir(), 'MC_NEOFORGE_RUNTIME_JRE')
    for p in sorted(jre.rglob('*')):
        if p.is_file():
            capture(source, p)

    base = read(source / '.minecraft/versions/1.21.1/1.21.1.json')
    index_name = base.get('assetIndex', {}).get('id')
    require(isinstance(index_name, str) and re.fullmatch('[A-Za-z0-9_.-]{1,80}', index_name),
            'MC_NEOFORGE_RUNTIME_ASSET_INDEX')
    index_path = source / ('.minecraft/assets/indexes/' + index_name + '.json')
    require(any(pin['path'] == index_path.relative_to(source).as_posix() for pin in lock['files']),
            'MC_NEOFORGE_RUNTIME_ASSET_INDEX_UNPINNED')
    objects = read(index_path).get('objects')
    require(isinstance(objects, dict) and 0 < len(objects) <= 65536, 'MC_NEOFORGE_RUNTIME_ASSETS')
    for item in objects.values():
        require(isinstance(item, dict) and isinstance(item.get('hash'), str)
                and re.fullmatch('[0-9a-f]{40}', item['hash'])
                and type(item.get('size')) is int and item['size'] >= 0, 'MC_NEOFORGE_RUNTIME_ASSET_PIN')
        p = safe_path(source, source / ('.minecraft/assets/objects/' + item['hash'][:2] + '/' + item['hash']))
        require(p.is_file() and p.stat().st_size == item['size'], 'MC_NEOFORGE_RUNTIME_ASSET_MISSING_OR_SIZE')
        first, second = hashlib.sha1(), hashlib.sha256()
        with p.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                first.update(block); second.update(block)
        require(first.hexdigest() == item['hash'], 'MC_NEOFORGE_RUNTIME_ASSET_HASH')
        key = p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p)
        files[key] = second.hexdigest()

    build = read(capture(root, root / BUILD_RECEIPT))
    require(build.get('ok') is True and build.get('jar') == CONTROLLER_JAR
            and build.get('compiled_against') == 'actual_supplied_neoforge_21.1.248_mojmap_libraries'
            and build.get('automatic_input_authorized') is False
            and isinstance(build.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', build['sha256'])
            and type(build.get('bytes')) is int and build['bytes'] > 0, 'MC_NEOFORGE_RUNTIME_BUILD_BINDING')
    sources = {}
    for top in ['game-adapters/minecraft/neoforge/src/main/java',
                'game-adapters/minecraft/neoforge/src/main/resources', BRIDGE_CORE]:
        for p in sorted(safe_path(root, root / top).rglob('*')):
            if p.is_file():
                name = p.relative_to(root).as_posix()
                capture(root, p); sources[name] = files[name]
    for name in [BRIDGE_LOCK, BRIDGE_SCHEMA, 'scripts/mc_neoforge.py']:
        capture(root, root / name); sources[name] = files[name]
    require(build.get('sources') == sources, 'MC_NEOFORGE_RUNTIME_BUILD_SOURCE_SET_OR_HASH')
    dependencies, paths = bridge_dependencies(root)
    expected_dependencies = {}
    for pin, path in zip(dependencies, paths):
        capture(root, path, pin['sha256'], pin['bytes'])
        expected_dependencies[path.relative_to(root).as_posix()] = pin['sha256']
    require(build.get('dependencies') == expected_dependencies, 'MC_NEOFORGE_RUNTIME_BUILD_DEPENDENCY_SET')
    jar = capture(root, root / CONTROLLER_JAR, build.get('sha256'), build.get('bytes'))
    with zipfile.ZipFile(jar) as archive:
        names = archive.namelist()
        require(len(set(names)) == len(names) and all(name in names for name in [
            'dev/aitalkstreamer/mc/neoforge/NativeClient.class',
            'dev/aitalkstreamer/mc/neoforge/NativeBridge.class',
            'dev/aitalkstreamer/mc/core/BridgeCore.class']), 'MC_NEOFORGE_RUNTIME_JAR_CLASSES')
        resources = root / 'game-adapters/minecraft/neoforge/src/main/resources'
        for p in resources.rglob('*'):
            if p.is_file():
                require(archive.read(p.relative_to(resources).as_posix()) == p.read_bytes(),
                        'MC_NEOFORGE_RUNTIME_JAR_RESOURCE')
        require(archive.read('mc-contracts/game.schema.json') == (root / BRIDGE_SCHEMA).read_bytes(),
                'MC_NEOFORGE_RUNTIME_JAR_SCHEMA')
        metadata = []
        for pin in dependencies:
            embedded = 'META-INF/jarjar/' + pin['file']
            data = archive.read(embedded)
            require(len(data) == pin['bytes'] and hashlib.sha256(data).hexdigest() == pin['sha256'],
                    'MC_NEOFORGE_RUNTIME_JAR_DEPENDENCY')
            metadata.append({'identifier': {'group': pin['group'], 'artifact': pin['artifact']},
                'version': {'range': '[' + pin['version'] + ']', 'artifactVersion': pin['version']},
                'path': embedded, 'isObfuscated': False})
        require(json.loads(archive.read('META-INF/jarjar/metadata.json')) == {'jars': metadata},
                'MC_NEOFORGE_RUNTIME_JAR_DEPENDENCY_METADATA')
    return files


def runtime_status(root):
    result = {'classification':'NEOFORGE_RUNTIME_FILES_NOT_FULL_APPLICATION_READINESS',
              'services_started':False, 'models_loaded':False, 'game_started':False,
              'automatic_input_authorized':False, 'full_application_prepared':False,
              'real_acceptance_passed':0}
    try:
        files = runtime_files(root)
        result.update(ok=True, verified_files=len(files), inventory_sha256=hashlib.sha256(
            json.dumps(files, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest())
    except (OSError, ValueError, KeyError, TypeError, OperationError, zipfile.BadZipFile):
        # A status reply never publishes a private source path or launcher data.
        result.update(ok=False, code='MC_NEOFORGE_RUNTIME_UNPREPARED_OR_CHANGED')
    return result


def launch_plan(root, source, server, world_samples=5, *, integration_probe=True,
                mode='multiplayer', world=None):
    root = Path(root).resolve(); source = Path(source).resolve()
    require(type(world_samples) is int and 5 <= world_samples <= 300, 'MC_NEOFORGE_WORLD_SAMPLE_LIMIT')
    require(type(integration_probe) is bool, 'MC_NEOFORGE_PROBE_FLAG')
    require(mode in ('singleplayer', 'multiplayer'), 'MC_NEOFORGE_WORLD_MODE')
    if mode == 'multiplayer':
        require(world is None and isinstance(server, str)
                and re.fullmatch(r'(?:[A-Za-z0-9][A-Za-z0-9.-]{0,252}|\[[0-9A-Fa-f:]+\]):[0-9]{1,5}', server)
                and 0 < int(server.rsplit(':', 1)[1]) < 65536, 'MC_NEOFORGE_SERVER')
    else:
        require(server is None and (world is None or isinstance(world, str)
                and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]{0,63}', world)
                and not world.endswith(' ')
                and all(not part.startswith('-') for part in world.split(' '))
                and world.casefold() not in {'con','prn','aux','nul',*[f'com{i}' for i in range(1,10)],*[f'lpt{i}' for i in range(1,10)]}),
                'MC_NEOFORGE_LOCAL_WORLD')
    if not integration_probe:
        runtime_files(root)
    lock, instance = package(root, source)
    record = read(root / RECEIPT); work = safe_path(root, root / HOME / 'work')
    if mode == 'singleplayer' and world is not None:
        require(safe_path(root, work / 'saves' / world / 'level.dat').is_file(),
                'MC_NEOFORGE_LOCAL_WORLD_MISSING')
    require(record['installation_root'] == str(root) and record['source'] == str(source)
            and record['lock_sha256'] == sha(root / LOCK) and Path(record['work']) == work,
            'MC_NEOFORGE_INSTALLATION_BINDING')
    prefix = '.minecraft/versions/' + lock['version_id'] + '/mods/'
    expected_mods = {Path(row['path']).name: row for row in lock['files'] if row['path'].startswith(prefix)}
    actual_mods = {p.name for p in (work / 'mods').iterdir() if p.is_file()}
    require(actual_mods == set(expected_mods) | {'ai-talk-streamer-native-neoforge-0.1.0.jar'}, 'MC_NEOFORGE_TARGET_MOD_SET_CHANGED')
    for name, pin in expected_mods.items():
        require(sha(safe_path(root, work / 'mods' / name)) == pin['sha256'], 'MC_NEOFORGE_TARGET_MOD_CHANGED')
    build = read(root / '.setup/mc-neoforge-probe-build.json')
    require(sha(safe_path(root, root / build['jar'])) == build['sha256'], 'MC_NEOFORGE_PROBE_CHANGED')
    for name, digest in build['sources'].items():
        require(sha(safe_path(root, root / name)) == digest, 'MC_NEOFORGE_PROBE_BUILD_STALE')
    for name, digest in build.get('dependencies', {}).items():
        require(sha(safe_path(root, root / name)) == digest, 'MC_NEOFORGE_BRIDGE_DEPENDENCY_CHANGED')
    base = read(source / '.minecraft/versions/1.21.1/1.21.1.json')
    neo = read(instance / (lock['version_id'] + '.json')); library = source / '.minecraft/libraries'
    libraries = {}
    for item in base['libraries'] + neo['libraries']:
        if allowed(item.get('rules')):
            bits = item['name'].split(':'); libraries[tuple(bits[:2] + bits[3:])] = item
    paths = []
    for item in libraries.values():
        artifact = item.get('downloads', {}).get('artifact')
        if artifact:
            path = library / artifact['path']; require(path.is_file(), 'MC_NEOFORGE_LIBRARY_MISSING')
            if path.name not in MODULES:
                paths.append(str(path))
    paths.append(str(instance / (lock['version_id'] + '.jar')))
    values = {'auth_player_name': lock['username'], 'auth_uuid': offline_uuid(lock['username']).replace('-', ''),
        'auth_access_token': '0', 'user_type': 'legacy', 'clientid': '0', 'auth_xuid': '0',
        'version_name': lock['version_id'], 'game_directory': str(work),
        'assets_root': str(source / '.minecraft/assets'), 'assets_index_name': base['assetIndex']['id'],
        'version_type': 'release', 'natives_directory': str(work.parent / 'natives'),
        'launcher_name': 'AI-Talk-Streamer', 'launcher_version': 'mc-native-1',
        'classpath': os.pathsep.join(paths), 'library_directory': str(library), 'classpath_separator': os.pathsep}
    def expand(items):
        args = []
        for item in items:
            if isinstance(item, dict):
                if not allowed(item.get('rules')):
                    continue
                item = item['value']
            for value in item if isinstance(item, list) else [item]:
                args.append(re.sub(r'\$\{([^}]+)\}', lambda m: values[m[1]], value))
        return args
    args = ['-Xms1G', '-Xmx6G', '-Dfile.encoding=UTF-8', '-Djava.io.tmpdir=' + str(work.parent / 'tmp')]
    if integration_probe:
        args += ['-Dai.talk.streamer.integrationProbe=true',
                 '-Dai.talk.streamer.integrationWorldSamples=' + str(world_samples)]
    jvm = expand(base['arguments']['jvm']) + expand(neo['arguments']['jvm'])
    # Vanilla points JNA at the native-library directory. Its random extracted
    # DLLs and deletion markers must not mutate our immutable dependency set.
    args += [arg for arg in jvm if not arg.startswith('-Djna.tmpdir=')]
    args += ['-Djna.tmpdir=' + str(work.parent / 'tmp')]
    game_args = expand(base['arguments']['game']) + expand(neo['arguments']['game'])
    if mode == 'singleplayer':
        require(not any(a in {'--server','--port','-s','-p','--quickPlayMultiplayer','--quickPlayRealms'}
                        for a in game_args), 'MC_NEOFORGE_LOCAL_WORLD_NETWORK_ARGUMENT')
    args += [neo['mainClass']] + game_args
    args += ['--width', '1280' if integration_probe else '1920', '--height', '720' if integration_probe else '1080']
    # The exact folder name stays one argument; java_quote also quotes it in
    # the native argfile. Do not trim, split or rename an existing world.
    if mode == 'multiplayer': args += ['--quickPlayMultiplayer', server]
    elif world is not None: args += ['--quickPlaySingleplayer', world]
    args += ['--quickPlayPath', str(work / 'logs/quickplay.json')]
    require(neo['mainClass'] == 'cpw.mods.bootstraplauncher.BootstrapLauncher', 'MC_NEOFORGE_MAIN_CLASS')
    return instance / 'runtime/java21/bin/java.exe', args, work


def bridge_dependencies(root):
    root = Path(root).resolve(); lock = read(root / BRIDGE_LOCK)
    require(lock['schema_version'] == 1 and lock['shared_core'] == BRIDGE_CORE and lock['schema'] == BRIDGE_SCHEMA,
            'MC_NEOFORGE_BRIDGE_LOCK')
    expected = {('dev.harrel', 'json-schema', '1.9.1'), ('org.xerial', 'sqlite-jdbc', '3.53.4.0')}
    entries = lock['dependencies']
    require(len(entries) == 2 and {(d['group'], d['artifact'], d['version']) for d in entries} == expected,
            'MC_NEOFORGE_BRIDGE_DEPENDENCY_SET')
    paths = []
    for entry in entries:
        require(entry['file'] == entry['artifact'] + '-' + entry['version'] + '.jar', 'MC_NEOFORGE_BRIDGE_DEPENDENCY_PATH')
        path = safe_path(root, root / HOME / 'dependencies' / entry['file'])
        require(path.is_file() and path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'],
                'MC_NEOFORGE_BRIDGE_DEPENDENCY_HASH:' + entry['file'])
        paths.append(path)
    return entries, paths


def build_probe(root, source, jdk):
    root = Path(root).resolve(); source = Path(source).resolve(); jdk = Path(jdk).resolve()
    _, instance = package(root, source)
    work = safe_path(root, root / HOME / 'work'); build = safe_path(root, root / HOME / 'build')
    classes = build / ('classes-' + uuid.uuid4().hex); classes.mkdir(parents=True)
    entries, dependencies = bridge_dependencies(root)
    library = source / '.minecraft/libraries'
    # Patched Mojmap classes precede vanilla; no game library is fetched or altered.
    first = [library / 'net/neoforged/neoforge/21.1.248/neoforge-21.1.248-client.jar',
             library / 'net/minecraft/client/1.21.1-20240808.144430/client-1.21.1-20240808.144430-srg.jar']
    cp = first + sorted(p for p in library.rglob('*.jar') if p not in first) + dependencies
    java = root / 'game-adapters/minecraft/neoforge/src/main/java'
    core = root / BRIDGE_CORE
    args = ['--release', '21', '-proc:none', '-encoding', 'UTF-8', '-classpath', os.pathsep.join(map(str, cp)),
            '-d', str(classes), *[str(p) for top in (java, core) for p in sorted(top.rglob('*.java'))]]
    argfile = build / 'javac.args'; argfile.write_text('\n'.join(map(java_quote, args)), encoding='utf-8')
    result = subprocess.run([str(jdk / 'bin/javac.exe'), '@' + str(argfile)], cwd=root,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    (build / 'compile.log').write_bytes(result.stdout)
    require(result.returncode == 0, 'MC_NEOFORGE_NATIVE_COMPILE_FAILED:' + str(build / 'compile.log'))
    jar = work / 'mods/ai-talk-streamer-native-neoforge-0.1.0.jar'
    candidate = build / ('bridge-' + uuid.uuid4().hex + '.jar')
    with zipfile.ZipFile(candidate, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for path in classes.rglob('*.class'):
            output.write(path, path.relative_to(classes).as_posix())
        resources = root / 'game-adapters/minecraft/neoforge/src/main/resources'
        for path in resources.rglob('*'):
            if path.is_file():
                output.write(path, path.relative_to(resources).as_posix())
        output.write(root / BRIDGE_SCHEMA, 'mc-contracts/game.schema.json')
        metadata = []
        for entry, path in zip(entries, dependencies):
            embedded = 'META-INF/jarjar/' + entry['file']
            output.write(path, embedded)
            metadata.append({'identifier': {'group': entry['group'], 'artifact': entry['artifact']},
                'version': {'range': '[' + entry['version'] + ']', 'artifactVersion': entry['version']},
                'path': embedded, 'isObfuscated': False})
        output.writestr('META-INF/jarjar/metadata.json', json.dumps({'jars': metadata}))
    os.replace(candidate, jar)
    result = {'ok': True, 'jar': jar.relative_to(root).as_posix(), 'sha256': sha(jar), 'bytes': jar.stat().st_size,
            'compiled_against': 'actual_supplied_neoforge_21.1.248_mojmap_libraries',
            'automatic_input_authorized': False,
            'classes': classes.relative_to(root).as_posix(), 'shared_authority': 'BridgeCore/ControlArbiter/LocalJournal',
            'dependencies': {p.relative_to(root).as_posix(): sha(p) for p in dependencies},
            'sources': {p.relative_to(root).as_posix(): sha(p) for p in [
                *[p for top in (java, resources, core) for p in top.rglob('*') if p.is_file()],
                root / BRIDGE_LOCK, root / BRIDGE_SCHEMA, root / 'scripts/mc_neoforge.py']}}
    atomic_json(root, root / '.setup/mc-neoforge-probe-build.json', result)
    return result


def probe(root, source, server, timeout=600, world_samples=5):
    require(os.name == 'nt' and platform.node().casefold() == 'desktop-2qqpn1h',
            'MC_GAME_TEST_REQUIRES_REMOTE_3080_NOT_LOCAL_MACHINE')
    root = Path(root).resolve(); require(60 <= timeout <= 900, 'MC_NEOFORGE_PROBE_TIMEOUT')
    java, args, work = launch_plan(root, source, server, world_samples)
    import psutil
    require(psutil.virtual_memory().available >= 8 * 1024**3, 'MC_NEOFORGE_FREE_RAM_BELOW_8_GIB')
    require(not any(p.info['name'] and p.info['name'].lower() in ('java.exe', 'javaw.exe')
                    and any(str(work.parent).casefold() in a.casefold() or 'MC-Friends-S1-r001.json' in a
                            for a in p.info.get('cmdline') or [])
                    for p in psutil.process_iter(['name', 'cmdline'])), 'MC_NEOFORGE_PLAYER_ALREADY_RUNNING')
    logs = work / 'logs'; logs.mkdir(exist_ok=True); (work.parent / 'tmp').mkdir(exist_ok=True)
    facts = logs / 'ai-talk-streamer-native.json'; facts.unlink(missing_ok=True)
    (logs / 'ai-talk-streamer-native.png').unlink(missing_ok=True)
    argfile = work.parent / 'launch.args'
    # Windows java.exe uses the native argument-file encoding, including Chinese paths.
    argfile.write_text('\n'.join(map(java_quote, args)), encoding='mbcs')
    result = {'classification': 'REAL_NEOFORGE_CLIENT_LOGIN_PROBE_NOT_FULL_RELEASE_ACCEPTANCE',
        'username': 'NAIMEI', 'automatic_input_authorized': False, 'game_started': False,
        'models_loaded': False, 'formal_acceptance_passed': 0, 'started_at': datetime.now(timezone.utc).isoformat()}
    job = NativeJob(); process = None
    try:
        with operation(root, 'mc-neoforge-player-probe'):
            with (logs / 'native-console.log').open('wb') as log:
                process = job.spawn([str(java), '@' + str(argfile)], cwd=work, stdout=log, stderr=log)
                result.update(game_started=True, process=process.identity())
                atomic_json(root, root / HOME / 'probe-process.json', result)
                deadline = time.monotonic() + timeout
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.5)
                result['timed_out'] = process.poll() is None
                if result['timed_out']:
                    job.rollback()
                result['exit_code'] = process.wait(timeout=15)
            result['facts'] = read(facts) if facts.is_file() else None
            result['ok'] = result['exit_code'] == 0 and bool(result['facts']) \
                and result['facts'].get('in_world') is True and result['facts'].get('player_name') == 'NAIMEI' \
                and result['facts'].get('world_samples', 0) >= 5
    finally:
        if job.active():
            job.rollback()
        result['all_owned_processes_closed'] = job.active() == 0
        job.close()
        if process:
            process.close()
        result['completed_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(root, root / HOME / 'probe-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'prepare', 'build-probe', 'probe'])
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--source', required=True)
    parser.add_argument('--jdk')
    parser.add_argument('--server')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--world-samples', type=int, default=5)
    args = parser.parse_args()
    if args.action == 'inspect':
        lock, _ = package(args.root, args.source)
        result = {k: lock[k] for k in ['minecraft', 'neoforge', 'username', 'authentication', 'mod_count']}
        result['ok'] = True
    elif args.action == 'prepare':
        result = prepare(args.root, args.source)
    elif args.action == 'build-probe':
        require(args.jdk, 'MC_NEOFORGE_JDK_REQUIRED'); result = build_probe(args.root, args.source, args.jdk)
    else:
        result = probe(args.root, args.source, args.server, args.timeout, args.world_samples)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result.get('ok', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
