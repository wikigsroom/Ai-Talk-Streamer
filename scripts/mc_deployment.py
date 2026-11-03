"""Native MC source packages and preparation, bound to real device/source files.

No downloads, model imports, source-receipt rewrites, service starts or game input.
The preparation record authorizes the selected native inference environment only;
the controlled game's own launch/input gates remain independent.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import json
import os
import re
import socket
import stat
import struct
import subprocess
import uuid
import zipfile

PROFILE = 'configs/deployment-profiles/mc-native-3080-neoforge-v1.json'
PROFILE_ID = 'mc-native-3080-neoforge-v1'
BINDINGS = 'configs/mc-runtime.private.json'
RECEIPT = '.setup/mc-native-preparation.json'
PREPARING = '.setup/mc-native-prepare.lock'
SOURCE_ROOTS = ['backend', 'web', 'integration', 'scripts', 'deployment', 'configs', 'tests',
                'game-adapters', 'docs/dsh-humanity', 'docs/technical/mc-live-v1/contracts']
SOURCE_FILES = {'.gitignore', '.gitattributes', 'package.json', 'package-lock.json',
                'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'README.zh-CN.md', 'AGENTS.md'}
SOURCE_GENERATED = {'docs/technical/mc-live-v1/contracts/verification.json'}
SOURCE_PRIVATE = {'configs/livetalking.yaml', 'configs/hardware-profile.json', 'configs/resident-tts.json',
                  'configs/mc-vision.json', 'configs/mc-game.json', 'configs/dsh-enabled.json',
                  'configs/dsh-active-policy.json', 'configs/moss-live.json', 'configs/dsh-operator.token',
                  'configs/dsh-media.token'}
SOURCE_IGNORED_DIRS = {'.git', '.setup', '.gradle', 'build', 'run', 'node_modules', '__pycache__',
                       'logs', 'crash-reports'}
SOURCE_IGNORED_SUFFIXES = {'.pyc', '.pyo', '.part', '.uploading', '.tmp', '.log', '.zip', '.7z', '.mkv',
                         '.pt', '.pth', '.ckpt', '.safetensors', '.key', '.pem', '.pfx', '.p12', '.token'}
SOURCE_ORIGIN = '.setup/mc-source-origin.json'
SOURCE_INSTALL_OWNER = '.setup/mc-source-install.owner'
SOURCE_MANIFEST = 'mc-source-manifest.json'
SOURCE_MAX_FILES, SOURCE_MAX_BYTES, SOURCE_MAX_FILE = 10000, 256 * 1024 * 1024, 16 * 1024 * 1024
SOURCE_MAX_MANIFEST = 4 * 1024 * 1024
SOURCE_REQUIRED = {PROFILE, 'scripts/mc_deployment.py', 'scripts/mc_runtime.py', 'scripts/mc_application.py', 'scripts/mc_application_console.py',
                   'scripts/mc_game_service.py', 'scripts/mc_vision_service.py', 'scripts/mc_offline_install.py', 'configs/mc-player.example.json',
                   'scripts/mc_readiness.py', 'scripts/mc_vision_install.py',
                   'web/mc-runtime.html', 'web/mc-runtime.js', 'web/mc-runtime.css', 'scripts/deployment_target.py',
                   'scripts/mc_source_checks.py', 'configs/mc-source-checks.json',
                   'scripts/mc_client.py', 'configs/mc-client.lock.json', 'tests/test_mc_client.py',
                     'scripts/mc_neoforge.py', 'configs/mc-neoforge-client.lock.json', 'configs/mc-neoforge-bridge.lock.json', 'tests/test_mc_neoforge.py',
                     'tests/mc_neoforge_runtime_fixture.py', 'tests/test_mc_neoforge_runtime.py',
                     'game-adapters/minecraft/neoforge/src/main/java/dev/aitalkstreamer/mc/neoforge/NativeGamePort.java',
                     'game-adapters/minecraft/neoforge/src/main/java/dev/aitalkstreamer/mc/neoforge/NativeBridge.java',
                   'game-adapters/minecraft/neoforge/src/main/java/dev/aitalkstreamer/mc/neoforge/NativeClient.java',
                   'game-adapters/minecraft/neoforge/src/main/resources/META-INF/neoforge.mods.toml',
                   'configs/deployment-target.json', 'configs/deployment-targets.json', 'configs/releases/current.json',
                   'configs/layouts/mc-landscape-v1.json', 'docs/technical/mc-live-v1/contracts/game.schema.json',
                   'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'}
SHA_RE = re.compile(r'[0-9a-f]{64}\Z')
MODEL_ARCHIVE_METADATA = frozenset({'.gitattributes', 'README.md', 'LICENSE',
                                    'benchmark-download.json', 'benchmark-manifest.json', 'configuration.json'})


def model_runtime_rows(lock):
    """Keep every weight, tokenizer and inference config pinned; separate archive-only provenance."""
    rows = lock['model_files']
    require(isinstance(rows, list) and 0 < len(rows) <= 1024, 'MC_NATIVE_MODEL_LOCK')
    for row in rows:
        require(isinstance(row, dict) and type(row.get('bytes')) is int and row['bytes'] >= 0
                and isinstance(row.get('sha256'), str) and SHA_RE.fullmatch(row['sha256'])
                and isinstance(row.get('path'), str), 'MC_NATIVE_MODEL_LOCK')
    runtime = [row for row in rows if PurePosixPath(row['path']).name not in MODEL_ARCHIVE_METADATA]
    require(bool(runtime), 'MC_NATIVE_MODEL_LOCK')
    return runtime


class PreparationError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise PreparationError(code)


def sha(path):
    # The pinned native avatar environment uses Python 3.10, before file_digest.
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def inside(root, name):
    require(isinstance(name, str) and name and '\\' not in name and '\x00' not in name,
            'MC_PREPARATION_PATH')
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and '..' not in relative.parts
            and all(':' not in part for part in relative.parts), 'MC_PREPARATION_PATH')
    root = Path(root).resolve()
    path = root.joinpath(*relative.parts)
    for part in [path, *path.parents]:
        if part == root:
            break
        # Python 3.10 has no Path.is_junction; lstat exposes the native tag.
        try:
            junction = getattr(part.lstat(), 'st_reparse_tag', 0) == getattr(
                stat, 'IO_REPARSE_TAG_MOUNT_POINT', 0xA0000003)
        except FileNotFoundError:
            junction = False
        require(not part.is_symlink() and not junction,
                'MC_PREPARATION_LINK')
    require(path.resolve().is_relative_to(root), 'MC_PREPARATION_PATH')
    return path


def read(path, limit=8 * 1024 * 1024):
    require(path.is_file() and path.stat().st_size <= limit, 'MC_PREPARATION_FILE_MISSING_OR_LARGE')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (UnicodeError, ValueError):
        raise PreparationError('MC_PREPARATION_JSON_INVALID') from None


def base_guard():
    spec = importlib.util.spec_from_file_location('mc_device_guard', Path(__file__).with_name('deployment_target.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def output(argv, *, cwd, timeout=15):
    flags = {'creationflags': 0x08000000} if os.name == 'nt' else {}
    # No shell or configurable command fragments; only fixed probes are executed.
    # Fixed read-only probes must not inherit an operator/HTTP host's input pipe.
    # In a native threaded console Git may otherwise wait on that inherited pipe.
    return subprocess.check_output(argv, cwd=cwd, timeout=timeout, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, **flags)


def source_name(name):
    """Public project source only; installed dependencies and private bindings stay separate."""
    if not isinstance(name, str) or not name or name in SOURCE_GENERATED:
        return False
    parts = name.split('/')
    if (any(not p or p in {'.', '..'} or p[-1:] in {'.', ' '}
            or any(ord(c) < 32 or c in '\\:<>"|?*' for c in p)
            or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p) for p in parts)
            or any(p.casefold() in SOURCE_IGNORED_DIRS for p in parts[:-1])):
        return False
    lower = name.casefold(); filename = parts[-1].casefold()
    if (lower in SOURCE_PRIVATE or '.private.' in filename or filename.endswith('.private')
            or filename == '.env' or filename.startswith('.env.') and filename != '.env.example'
            or filename.endswith('.env') or Path(filename).suffix in SOURCE_IGNORED_SUFFIXES):
        return False
    return (name in SOURCE_FILES or any(name.startswith(folder + '/') for folder in SOURCE_ROOTS)
            or len(parts) == 1 and Path(filename).suffix in {'.cmd', '.ps1'})


def source_hashes(root, names):
    require(names and len(names) <= SOURCE_MAX_FILES and all(source_name(n) for n in names),
            'MC_SOURCE_PATH_OR_COUNT')
    require(len({name.casefold() for name in names}) == len(names), 'MC_SOURCE_WINDOWS_ALIAS')
    files, total = {}, 0
    for name in sorted(names):
        path = inside(root, name)
        require(path.is_file(), 'MC_PREPARATION_SOURCE_MISSING')
        size = path.stat().st_size; total += size
        require(size <= SOURCE_MAX_FILE and total <= SOURCE_MAX_BYTES, 'MC_PREPARATION_SOURCE_SIZE')
        files[name] = sha(path)
    return files


def source_identity(root):
    root = Path(root).resolve()
    if not (root / '.git').exists():
        require(inside(root, SOURCE_ORIGIN).is_file(), 'MC_PREPARATION_REQUIRES_MC_SOURCE_CHECKOUT')
        return installed_source_identity(root)
    branch = output(['git', 'branch', '--show-current'], cwd=root).decode('utf-8').strip()
    commit = output(['git', 'rev-parse', 'HEAD'], cwd=root).decode('ascii').strip()
    require(branch == 'mc' and re.fullmatch('[0-9a-f]{40}', commit), 'MC_PREPARATION_SOURCE_BRANCH')
    paths = output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--',
                    *SOURCE_ROOTS, *sorted(SOURCE_FILES), ':(top,glob)*.cmd', ':(top,glob)*.ps1'], cwd=root).decode('utf-8').split('\x00')
    # Include every file in these runtime source roots, including prompts,
    # resource files and newly introduced extensions. Git ignore rules exclude
    # installed dependencies, build caches, models and private configuration.
    names = sorted({name for name in paths if name and name not in SOURCE_GENERATED})
    files = source_hashes(root, names)
    return {'kind': 'git_worktree_with_file_manifest', 'branch': branch, 'commit': commit,
            'commit_alone_describes_workspace': False, 'files': files, 'snapshot_sha256': digest(files)}


def load_profile(root):
    guard = base_guard()
    registry, selected = guard.contract(root)
    profile = read(inside(root, PROFILE))
    require(set(profile) == {'schema_version', 'id', 'application', 'source_branch', 'device_target',
            'base_deployment_branch', 'topology', 'inference', 'layout', 'native', 'game',
            'base_runtime_lock', 'ports', 'initial_mode', 'automatic_input_authorized_by_preparation',
            'runtime_acceptance'}, 'MC_PROFILE_SHAPE')
    require(profile['schema_version'] == 1 and profile['id'] == PROFILE_ID
            and profile['application'] == 'mc' and profile['source_branch'] == 'mc'
            and profile['device_target'] == selected['target'] == 'rtx3080', 'MC_PROFILE_DEVICE')
    spec = registry['targets']['rtx3080']
    require(profile['base_deployment_branch'] == selected['branch'] == 'deploy/rtx3080'
            and profile['topology'] == spec['topology'] == 'native_3080_cohost'
            and profile['inference'] == {'batch_size': spec['batch_size'], 'precision': 'FP16',
                                         'fps': 25, 'state_path': spec['state_path']}, 'MC_PROFILE_INFERENCE')
    require(profile['initial_mode'] == 'PAUSED'
            and profile['automatic_input_authorized_by_preparation'] is False
            and profile['runtime_acceptance'] == 'not_run', 'MC_PROFILE_NO_AUTOMATIC_AUTHORIZATION')
    layout = profile['layout']
    require(layout == {'id':'mc-landscape-v1', 'revision':4, 'path':'configs/layouts/mc-landscape-v1.json',
                      'sha256':'6d3e60cc91934dd44017f65f992cc4c820f52d84fffb2a3d90da759f3acd9f76'}
            and sha(inside(root, layout['path'])) == layout['sha256'], 'MC_PROFILE_LAYOUT')
    require(profile['native'] == {'node':'24.22.1', 'python':'3.10.22', 'java_major':21,
                                   'platform':'win32', 'architecture':'x64'}, 'MC_PROFILE_NATIVE_VERSIONS')
    require(profile['base_runtime_lock'] == spec['release_pointer']['runtime_lock'], 'MC_PROFILE_BASE_LOCK')
    runtime_lock = read(inside(root, profile['base_runtime_lock']))
    require(runtime_lock['python'] == profile['native']['python'], 'MC_PROFILE_PYTHON_LOCK')
    game = profile['game']
    require(game == {'minecraft':'1.21.1', 'loader':'neoforge', 'loader_version':'21.1.248',
                     'client_lock':'configs/mc-neoforge-client.lock.json',
                     'bridge_lock':'configs/mc-neoforge-bridge.lock.json',
                     'username':'NAIMEI', 'authentication':'offline'}, 'MC_PROFILE_GAME_VERSIONS')
    client = read(inside(root, game['client_lock']))
    require(all(client.get(key) == value for key, value in {
        'minecraft':'1.21.1', 'neoforge':'21.1.248', 'username':'NAIMEI',
        'authentication':'offline', 'offline_uuid':'a77465cf-2de0-3278-bf48-d13b367e09ce',
        'premium_verification_required':False, 'server_whitelist_required':True,
        'version_id':'MC-Friends-S1-r001', 'mod_count':319}.items()), 'MC_PROFILE_NEOFORGE_LOCK')
    bridge = read(inside(root, game['bridge_lock']))
    require(bridge.get('schema_version') == 1
            and bridge.get('shared_core') == 'game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core'
            and bridge.get('schema') == 'docs/technical/mc-live-v1/contracts/game.schema.json',
            'MC_PROFILE_NEOFORGE_BRIDGE_LOCK')
    require(profile['ports'] == {'studio':8010, 'tts':9880, 'primary_voice':9881, 'backup_voice':9882,
            'dsh_management':3091, 'dsh':3092, 'receiver':8020, 'vision':8019}, 'MC_PROFILE_PORTS')
    return guard, registry, selected, profile


def executable(root, value, name):
    require(isinstance(value, str) and value and not any(c in value for c in ['\x00', '\n', '\r']),
            'MC_NATIVE_EXECUTABLE_PATH')
    path = Path(value)
    path = path if path.is_absolute() else inside(root, value)
    require(not path.is_symlink() and path.is_file() and path.name.lower() == name + '.exe',
            'MC_NATIVE_EXECUTABLE_MISSING')
    return path.resolve()


def native_binaries(root):
    bindings = read(inside(root, BINDINGS))
    require(set(bindings) == {'schema_version', 'profile', 'executables'} and bindings['schema_version'] == 1
            and bindings['profile'] == PROFILE and isinstance(bindings['executables'], dict)
            and set(bindings['executables']) == {'node', 'python', 'java'}, 'MC_NATIVE_BINDINGS')
    result = {}
    for name in ['node', 'python', 'java']:
        path = executable(root, bindings['executables'][name], name)
        if name == 'node':
            code = "import {DatabaseSync} from 'node:sqlite';const d=new DatabaseSync(':memory:');d.close();console.log(JSON.stringify({version:process.versions.node,platform:process.platform,arch:process.arch,sqlite:true}));"
            raw = output([str(path), '--input-type=module', '-e', code], cwd=root).decode('utf-8')
            value = json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
            require(value == {'version':'24.22.1', 'platform':'win32', 'arch':'x64', 'sqlite':True}, 'MC_NATIVE_NODE')
            version = value['version']
        elif name == 'python':
            code = "import json,sys,struct;print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),'platform':sys.platform,'bits':struct.calcsize('P')*8}))"
            value = json.loads(output([str(path), '-I', '-c', code], cwd=root).decode('utf-8'))
            require(value == {'version':'3.10.22', 'platform':'win32', 'bits':64}, 'MC_NATIVE_PYTHON')
            version = value['version']
        else:
            text = output([str(path), '-XshowSettings:properties', '-version'], cwd=root).decode('utf-8', errors='replace')
            version_match = re.search(r'(?:openjdk|java) version "(21(?:\.[0-9]+)*(?:[+_-][^"\s]+)?)"', text)
            require(version_match and re.search(r'os.arch\s*=\s*amd64\s*$', text, re.M), 'MC_NATIVE_JAVA')
            version = version_match[1]
        result[name] = {'path':str(path), 'bytes':path.stat().st_size, 'sha256':sha(path), 'version':version}
    return result


def client_runtime_files(root):
    from mc_neoforge import HOME, runtime_files as neoforge_runtime_files
    try:
        files = neoforge_runtime_files(root)
        name = HOME + '/work/config/ai-talk-streamer-bridge.json'
        path = inside(root, name)
        require(read(path) == {'enabled':True, 'endpoint':'ws://127.0.0.1:3092/api/dsh/game/bridge'},
                'MC_NATIVE_GAME_BRIDGE_BINDING')
        files[name] = sha(path)
        return files
    except ValueError as error:
        raise PreparationError(str(error)) from None


def runtime_files(root):
    files = {}
    def capture(name, expected=None):
        path = inside(root, name)
        actual = sha(path)
        require(expected is None or actual == expected, 'MC_NATIVE_RUNTIME_HASH')
        files[name] = actual
        return path
    for name in ['configs/deployment-target.json', 'configs/deployment-targets.json', 'configs/releases/current.json',
                 'configs/livetalking.yaml', 'configs/hardware-profile.json', 'configs/resident-tts.json',
                 'configs/dsh-active-policy.json', BINDINGS]:
        capture(name)
    from mc_game_service import configuration as player_configuration, CONFIG as player_config_path
    player_configuration(root)
    capture(player_config_path)
    policy_name = read(inside(root, 'configs/dsh-active-policy.json'))['policy_file']
    policy = read(capture(policy_name))
    require(policy['deployment']['dsh_home_relative_path'] == 'state/female-a-3080-k02/dsh-home'
            and policy['deployment']['bridge_port'] == 3092 and policy['deployment']['management_port'] == 3091,
            'MC_NATIVE_DSH_BINDING')
    require(read(inside(root, 'configs/hardware-profile.json'))['preset'] == 'rtx3080-k02-batch4', 'MC_NATIVE_HARDWARE_PRESET')
    voices = read(inside(root, 'configs/resident-tts.json'))
    require(voices['default_voice_id'] == 'O07' and set(voices['voices']) == {'O07', 'F07'}
            and voices['voices']['O07']['precision'] == 'FP16' and voices['voices']['F07']['precision'] == 'FP32',
            'MC_NATIVE_VOICE_PAIR')
    for name in ['readiness', 'asset-check']:
        require(read(capture('.setup/' + name + '.result.json')).get('ok') is True, 'MC_NATIVE_BASE_ASSETS_UNPREPARED')
    lock = read(inside(root, 'configs/releases/rtx3080-k02-runtime-lock.json'))
    for row in model_runtime_rows(lock):
        path = inside(root, row['path'])
        require(path.is_file() and path.stat().st_size == row['bytes'], 'MC_NATIVE_MODEL_MISSING_OR_SIZE')
        capture(row['path'], row['sha256'])
    capture(voices['reference_audio'], lock['reference_sha256'])
    require(voices['reference_sha256'] == lock['reference_sha256'], 'MC_NATIVE_VOICE_REFERENCE')
    for filename in ['package.json', 'package-lock.json']:
        capture('tools/dsh/' + filename, sha(inside(root, 'backend/dsh-bridge/' + filename)))
    for package, version in [('@deepseek-ai/dsh', '0.2.0-rc.2'), ('deepseek-harness-humanity', '0.1.17')]:
        require(read(capture('tools/dsh/node_modules/' + package + '/package.json'))['version'] == version,
                'MC_NATIVE_DSH_PACKAGE')
    patch = read(capture('.setup/dsh-humanity-patch.json'))
    prefix = 'tools/dsh/node_modules/deepseek-harness-humanity/lib/'
    require(patch['base_version'] == '0.1.17' and patch['connector_version'] == 'stream-humanity-v1'
            and patch['connector_sha256'] == sha(inside(root, 'backend/dsh-bridge/humanity-port.mjs')),
            'MC_NATIVE_HUMANITY_PATCH')
    capture(prefix + 'stream-connector.mjs', patch['connector_sha256'])
    require(isinstance(patch['files'], list) and 0 < len(patch['files']) <= 100, 'MC_NATIVE_HUMANITY_PATCH')
    for row in patch['files']:
        capture(prefix + row['file'], row['patched_sha256'])
    files.update(client_runtime_files(root))
    from mc_runtime_projection import validate as validate_projection
    files.update(validate_projection(root))
    return files


def idle(root, ports):
    import psutil
    for port in ports:
        with socket.socket() as probe:
            probe.settimeout(.15)
            require(probe.connect_ex(('127.0.0.1', port)) != 0, 'MC_PREPARATION_SERVICE_PORT_BUSY')
    anchors = {str(inside(root, name)).casefold().replace('/', '\\') for name in [
        'backend/dsh-bridge/server.mjs', 'src/LiveTalking/app.py', 'integration/resident_tts_service.py',
        'scripts/receiver_service.py']}
    for process in psutil.process_iter(['cmdline']):
        try:
            args = {str(arg).casefold().replace('/', '\\') for arg in (process.info['cmdline'] or [])}
            require(not anchors.intersection(args), 'MC_PREPARATION_PROJECT_PROCESS_ACTIVE')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def preflight(root):
    root = Path(root).resolve()
    checks, gathered = [], {}
    def check(name, fn):
        try:
            gathered[name] = fn()
            checks.append({'name':name, 'ok':True})
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
            code = str(error) if isinstance(error, PreparationError) else 'MC_' + name.upper() + '_UNAVAILABLE'
            checks.append({'name':name, 'ok':False, 'code':code})
    check('profile', lambda: load_profile(root))
    if 'profile' in gathered:
        guard, registry, selected, profile = gathered['profile']
        check('source', lambda: source_identity(root))
        # Report the real game installation independently when avatar/model
        # preparation is missing. A passing game inventory cannot mask either
        # those failures or the idle/single-owner gate below.
        check('game_files', lambda: client_runtime_files(root))
        check('device', lambda: guard.validate_device(root, registry['targets'][selected['target']], True, True))
        check('native', lambda: native_binaries(root))
        check('runtime_files', lambda: runtime_files(root))
        check('idle', lambda: idle(root, profile['ports'].values()))
    result = {'schema_version':1, 'classification':'NATIVE_ENVIRONMENT_PREPARATION_NOT_GAME_OR_RELEASE_ACCEPTANCE',
              'ok':bool(checks) and all(c['ok'] for c in checks), 'checks':checks,
              'profile':PROFILE, 'automatic_input_authorized':False, 'real_acceptance_passed':0,
              'services_started':False, 'models_loaded':False, 'downloads_performed':False}
    return result, gathered


@contextmanager
def preparation_lock(root):
    path = inside(root, PREPARING)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = path.open('x', encoding='utf-8')
    except FileExistsError:
        raise PreparationError('MC_PREPARATION_ALREADY_RUNNING_OR_LOCK_REQUIRES_REVIEW') from None
    try:
        with stream:
            stream.write(json.dumps({'pid':os.getpid(), 'started_at':datetime.now(timezone.utc).isoformat()}))
            stream.flush(); os.fsync(stream.fileno())
        yield
    finally:
        path.unlink()


def prepare(root, *, refresh=False):
    from native_operation import operation
    with operation(root, 'prepare-environment'):
        return _prepare(root, refresh=refresh)


def _prepare(root, *, refresh=False):
    root = Path(root).resolve()
    path = inside(root, RECEIPT)
    require(refresh or not path.exists(), 'MC_PREPARATION_EXISTS_USE_REFRESH')
    with preparation_lock(root):
        report, gathered = preflight(root)
        require(report['ok'], 'MC_PREPARATION_PREFLIGHT_FAILED')
        _, _, selected, profile = gathered['profile']
        # Capture again after all probes and hashes. A changed workspace cannot
        # receive a record for the earlier inventory.
        require(source_identity(root) == gathered['source'], 'MC_PREPARATION_SOURCE_CHANGED_DURING_CHECK')
        require(runtime_files(root) == gathered['runtime_files'], 'MC_PREPARATION_RUNTIME_CHANGED_DURING_CHECK')
        idle(root, profile['ports'].values())
        receipt = {'schema_version':1, 'kind':'mc_native_environment_preparation',
            'profile':PROFILE, 'profile_sha256':sha(inside(root, PROFILE)), 'profile_id':profile['id'],
            'installation_path':str(root), 'device_target':selected['target'], 'source':gathered['source'],
            'executables':gathered['native'], 'runtime_files':gathered['runtime_files'],
            'prepared_at':datetime.now(timezone.utc).isoformat(), 'initial_mode':'PAUSED',
            'automatic_input_authorized':False, 'real_acceptance_passed':0}
        if path.exists():
            history = inside(root, '.setup/mc-native-history/' + uuid.uuid4().hex + '.json')
            history.parent.mkdir(parents=True, exist_ok=True)
            with history.open('xb') as backup:
                backup.write(path.read_bytes())
        temporary = inside(root, '.setup/mc-native-' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(canonical(receipt) + b'\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {'ok':True, 'profile_id':profile['id'], 'receipt':RECEIPT, 'receipt_sha256':sha(path),
            'source_snapshot_sha256':receipt['source']['snapshot_sha256'],
            'automatic_input_authorized':False, 'real_acceptance_passed':0}


def validate_prepared(root, selected):
    root = Path(root).resolve()
    require(not inside(root, PREPARING).exists(), 'MC_PREPARATION_IN_PROGRESS')
    record = read(inside(root, RECEIPT))
    _, _, checked_selection, profile = load_profile(root)
    require(isinstance(record, dict) and selected == checked_selection and type(record.get('schema_version')) is int
            and record.get('schema_version') == 1
            and record.get('kind') == 'mc_native_environment_preparation'
            and record.get('profile') == PROFILE and record.get('profile_id') == profile['id']
            and record.get('device_target') == selected['target']
            and record.get('installation_path') == str(root)
            and record.get('profile_sha256') == sha(inside(root, PROFILE)), 'MC_PREPARATION_RECORD_BINDING')
    require(record.get('initial_mode') == 'PAUSED' and record.get('automatic_input_authorized') is False
            and record.get('real_acceptance_passed') == 0, 'MC_PREPARATION_NOT_EXECUTION_AUTHORITY')
    require(record.get('source') == source_identity(root), 'MC_PREPARATION_SOURCE_CHANGED')
    current_files = runtime_files(root)
    require(record.get('runtime_files') == current_files, 'MC_PREPARATION_RUNTIME_CHANGED')
    require(record.get('executables') == native_binaries(root), 'MC_PREPARATION_BINARY_CHANGED')
    return {'profile_id':profile['id'], 'source_branch':profile['source_branch'],
            'source_kind':record['source']['kind'],
            'source_snapshot_sha256':record['source']['snapshot_sha256'],
            'preparation_receipt_sha256':sha(inside(root, RECEIPT)), 'automatic_input_authorized':False}


def _source_json(data, limit=SOURCE_MAX_MANIFEST):
    require(len(data) <= limit, 'MC_SOURCE_MANIFEST_SIZE')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'MC_SOURCE_DUPLICATE_JSON_KEY')
            value[key] = item
        return value
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique)


def _source_manifest(value):
    require(isinstance(value, dict) and set(value) == {'schema_version', 'kind', 'profile', 'profile_id',
            'device_target', 'source', 'file_sizes', 'environment_prepared', 'automatic_input_authorized',
            'real_acceptance_passed'} and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['kind'] == 'mc_project_source_package' and value['profile'] == PROFILE
            and value['profile_id'] == PROFILE_ID and value['device_target'] == 'rtx3080'
            and value['environment_prepared'] is False and value['automatic_input_authorized'] is False
            and type(value['real_acceptance_passed']) is int and value['real_acceptance_passed'] == 0,
            'MC_SOURCE_MANIFEST_BINDING')
    source = value['source']
    require(isinstance(source, dict) and set(source) == {'kind', 'branch', 'commit',
            'commit_alone_describes_workspace', 'files', 'snapshot_sha256'}
            and source['kind'] == 'git_worktree_with_file_manifest' and source['branch'] == 'mc'
            and isinstance(source['commit'], str) and re.fullmatch('[0-9a-f]{40}', source['commit'])
            and source['commit_alone_describes_workspace'] is False and isinstance(source['files'], dict),
            'MC_SOURCE_MANIFEST_SOURCE')
    files = source['files']; sizes = value['file_sizes']
    require(0 < len(files) <= SOURCE_MAX_FILES and all(source_name(n) for n in files)
            and all(isinstance(h, str) and SHA_RE.fullmatch(h) for h in files.values())
            and isinstance(sizes, dict) and set(sizes) == set(files)
            and all(type(n) is int and 0 <= n <= SOURCE_MAX_FILE for n in sizes.values())
            and sum(sizes.values()) <= SOURCE_MAX_BYTES, 'MC_SOURCE_MANIFEST_FILES')
    require(len({n.casefold() for n in files}) == len(files), 'MC_SOURCE_WINDOWS_ALIAS')
    require(SOURCE_REQUIRED <= set(files) and source['snapshot_sha256'] == digest(files),
            'MC_SOURCE_MANIFEST_INCOMPLETE_OR_DIGEST')
    return source


def _installed_source_files(root):
    names = set()
    for folder in SOURCE_ROOTS:
        top = inside(root, folder)
        if not top.exists():
            continue
        require(top.is_dir(), 'MC_SOURCE_DIRECTORY')
        for directory, dirs, files in os.walk(top, followlinks=False):
            dirs[:] = [d for d in dirs if d.casefold() not in SOURCE_IGNORED_DIRS]
            for name in dirs:
                inside(root, (Path(directory) / name).relative_to(root).as_posix())
            for name in files:
                relative = (Path(directory) / name).relative_to(root).as_posix()
                if source_name(relative):
                    names.add(relative)
    for path in root.iterdir():
        if source_name(path.name):
            require(path.is_file(), 'MC_SOURCE_ROOT_FILE')
            names.add(path.name)
    return source_hashes(root, names)


def installed_source_identity(root):
    root = Path(root).resolve(); path = inside(root, SOURCE_ORIGIN)
    require(path.is_file() and path.stat().st_size <= SOURCE_MAX_MANIFEST + 4096, 'MC_SOURCE_ORIGIN_MISSING_OR_LARGE')
    record = _source_json(path.read_bytes(), SOURCE_MAX_MANIFEST + 4096)
    require(isinstance(record, dict) and set(record) == {'schema_version', 'kind', 'installation_path',
            'package_sha256', 'manifest_sha256', 'manifest'} and type(record['schema_version']) is int
            and record['schema_version'] == 1 and record['kind'] == 'installed_mc_source_package'
            and record['installation_path'] == str(root)
            and isinstance(record['package_sha256'], str) and SHA_RE.fullmatch(record['package_sha256'])
            and record['manifest_sha256'] == digest(record['manifest']), 'MC_SOURCE_ORIGIN_BINDING')
    source = _source_manifest(record['manifest'])
    require(_installed_source_files(root) == source['files'], 'MC_SOURCE_PACKAGE_FILES_CHANGED')
    return {**source, 'kind':'installed_mc_source_package_with_file_manifest',
            'package_sha256':record['package_sha256'], 'package_manifest_sha256':record['manifest_sha256']}


def _new_source_destination(path):
    path = Path(path).absolute()
    require(path.parent.is_dir(), 'MC_SOURCE_DESTINATION_PARENT')
    path = path.parent.resolve() / path.name
    require(not path.exists() and not path.is_symlink(), 'MC_SOURCE_DESTINATION_EXISTS')
    return path


def export_source(root, destination):
    """Export reviewed project files; dependencies, models and environment proof are separate."""
    root = Path(root).resolve(); destination = _new_source_destination(destination)
    require(destination.suffix.lower() == '.zip', 'MC_SOURCE_ARCHIVE_EXTENSION')
    require(not destination.parent.is_relative_to(root) or not any(
            destination.parent.is_relative_to(root / folder) for folder in SOURCE_ROOTS),
            'MC_SOURCE_EXPORT_IN_RUNTIME_SOURCE')
    _, _, _, profile = load_profile(root)
    source = source_identity(root)
    require(source['kind'] == 'git_worktree_with_file_manifest', 'MC_SOURCE_EXPORT_REQUIRES_GIT')
    sizes = {name:inside(root, name).stat().st_size for name in source['files']}
    manifest = {'schema_version':1, 'kind':'mc_project_source_package', 'profile':PROFILE, 'profile_id':profile['id'],
                'device_target':profile['device_target'], 'source':source, 'file_sizes':sizes,
                'environment_prepared':False, 'automatic_input_authorized':False, 'real_acceptance_passed':0}
    _source_manifest(manifest); raw = canonical(manifest)
    require(len(raw) <= SOURCE_MAX_MANIFEST, 'MC_SOURCE_MANIFEST_SIZE')
    temporary = destination.with_name('.mc-source-export-' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as output_file:
            with zipfile.ZipFile(output_file, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
                def add(name, data):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3; info.external_attr = (stat.S_IFREG | 0o644) << 16
                    archive.writestr(info, data)
                add(SOURCE_MANIFEST, raw)
                for name, expected in source['files'].items():
                    data = inside(root, name).read_bytes()
                    require(len(data) == sizes[name] and hashlib.sha256(data).hexdigest() == expected,
                            'MC_SOURCE_CHANGED_DURING_EXPORT')
                    add(name, data)
            output_file.flush(); os.fsync(output_file.fileno())
        require(source_identity(root) == source, 'MC_SOURCE_CHANGED_DURING_EXPORT')
        # Same-directory link publishes complete bytes and fails if a destination exists.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {'ok':True, 'classification':'PROJECT_SOURCE_PACKAGE_NOT_COMPLETE_APPLICATION_RELEASE',
            'archive':str(destination), 'sha256':sha(destination), 'source_snapshot_sha256':source['snapshot_sha256'],
            'source_files':len(source['files']), 'environment_prepared':False, 'services_started':False,
            'models_loaded':False, 'automatic_input_authorized':False, 'real_acceptance_passed':0}


def _source_archive_index(stream):
    """Bound the central directory before ZipFile can allocate an unbounded index."""
    stream.seek(0, os.SEEK_END); size = stream.tell()
    require(22 <= size <= SOURCE_MAX_BYTES + SOURCE_MAX_MANIFEST + 16 * 1024 * 1024,
            'MC_SOURCE_ARCHIVE_SIZE')
    stream.seek(-22, os.SEEK_END); footer = stream.read(22)
    require(len(footer) == 22, 'MC_SOURCE_ARCHIVE_INDEX')
    signature, disk, central_disk, on_disk, entries, central_bytes, offset, comment = struct.unpack('<4s4H2IH', footer)
    require(signature == b'PK\x05\x06' and disk == central_disk == 0 and on_disk == entries
            and 0 < entries <= SOURCE_MAX_FILES + 1 and comment == 0
            and central_bytes <= 16 * 1024 * 1024 and offset + central_bytes == size - 22,
            'MC_SOURCE_ARCHIVE_INDEX')
    stream.seek(0)


def _stream_sha(stream):
    stream.seek(0); value = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        value.update(block)
    stream.seek(0)
    return value.hexdigest()


def _remove_source_stage(stage, parent, marker):
    # Only this freshly-created sibling is removable. Preserve a replaced/reparse
    # path rather than following it into an unrelated directory.
    if not stage.exists():
        return
    require(stage.parent == parent and stage.resolve() == stage and not stage.is_symlink()
            and getattr(stage.lstat(), 'st_reparse_tag', 0) != 0xA0000003
            and inside(stage, SOURCE_INSTALL_OWNER).read_text(encoding='ascii') == marker,
            'MC_SOURCE_STAGE_OWNERSHIP_CHANGED')
    import shutil
    shutil.rmtree(stage)


def install_source(archive_path, destination, expected_sha256):
    """Install into a fresh native Windows directory without executing package code."""
    require(os.name == 'nt', 'MC_SOURCE_INSTALL_REQUIRES_NATIVE_WINDOWS')
    require(isinstance(expected_sha256, str) and SHA_RE.fullmatch(expected_sha256), 'MC_SOURCE_EXPECTED_SHA256')
    destination = _new_source_destination(destination); marker = uuid.uuid4().hex
    stage = destination.with_name('.mc-source-install-' + marker)
    require(not stage.exists(), 'MC_SOURCE_STAGE_EXISTS')
    published = owned = False
    try:
        with Path(archive_path).open('rb') as stream:
            _source_archive_index(stream)
            require(_stream_sha(stream) == expected_sha256, 'MC_SOURCE_ARCHIVE_HASH')
            with zipfile.ZipFile(stream) as archive:
                infos = archive.infolist(); names = [info.filename for info in infos]
                require(names and names[0] == SOURCE_MANIFEST and len(names) == len(set(names))
                        and len(names) <= SOURCE_MAX_FILES + 1, 'MC_SOURCE_ARCHIVE_MEMBERS')
                for info in infos:
                    mode = info.external_attr >> 16
                    require(not info.is_dir() and not info.external_attr & 0x10
                            and info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                            and not info.flag_bits & 1 and stat.S_IFMT(mode) in {0, stat.S_IFREG}
                            and len(info.filename.encode('utf-8')) <= 1024 and len(info.extra) <= 4096
                            and info.file_size <= (SOURCE_MAX_MANIFEST if info.filename == SOURCE_MANIFEST else SOURCE_MAX_FILE),
                            'MC_SOURCE_ARCHIVE_MEMBER_TYPE_OR_SIZE')
                raw = archive.read(infos[0]); manifest = _source_json(raw); source = _source_manifest(manifest)
                require(names == [SOURCE_MANIFEST, *sorted(source['files'])], 'MC_SOURCE_ARCHIVE_MEMBERS')
                for info in infos[1:]:
                    require(info.file_size == manifest['file_sizes'][info.filename], 'MC_SOURCE_ARCHIVE_FILE_SIZE')
                stage.mkdir(); (stage / '.setup').mkdir()
                inside(stage, SOURCE_INSTALL_OWNER).write_text(marker, encoding='ascii')
                owned = True
                for info in infos[1:]:
                    data = archive.read(info)
                    require(len(data) == manifest['file_sizes'][info.filename]
                            and hashlib.sha256(data).hexdigest() == source['files'][info.filename], 'MC_SOURCE_ARCHIVE_FILE_HASH')
                    target = inside(stage, info.filename); target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as output_file:
                        output_file.write(data)
                require(_installed_source_files(stage) == source['files'], 'MC_SOURCE_PACKAGE_FILES_CHANGED')
                load_profile(stage)
                origin = {'schema_version':1, 'kind':'installed_mc_source_package', 'installation_path':str(destination),
                          'package_sha256':expected_sha256, 'manifest_sha256':digest(manifest), 'manifest':manifest}
                target = inside(stage, SOURCE_ORIGIN); target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as output_file:
                    output_file.write(canonical(origin) + b'\n'); output_file.flush(); os.fsync(output_file.fileno())
            require(_stream_sha(stream) == expected_sha256, 'MC_SOURCE_ARCHIVE_CHANGED_DURING_INSTALL')
        require(not destination.exists() and not destination.is_symlink(), 'MC_SOURCE_DESTINATION_EXISTS')
        # Windows rename refuses an existing destination; no old installation is replaced.
        stage.rename(destination); published = True
    finally:
        if owned and not published:
            _remove_source_stage(stage, destination.parent, marker)
    return {'ok':True, 'classification':'PROJECT_SOURCE_INSTALLED_NOT_COMPLETE_APPLICATION_RELEASE',
            'source_files':len(source['files']), 'source_snapshot_sha256':source['snapshot_sha256'],
            'package_sha256':expected_sha256, 'source_origin':SOURCE_ORIGIN, 'environment_prepared':False,
            'services_started':False, 'models_loaded':False, 'automatic_input_authorized':False, 'real_acceptance_passed':0}
