"""Native offline A/B maintenance coordination, with immutable reviewed plans."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid

from mc_maintenance_dependencies import MaintenanceError, application_fence, canonical, capture, digest, parse, require, safe_path

SHA = re.compile(r'[0-9a-f]{64}\Z')
PLAN = re.compile(r'maintenance-[0-9a-f-]{36}\.json\Z')
B_PLAN = re.compile(r'retention-[0-9a-f-]{36}\.json\Z')
MAX_PLANS, MAX_LOGS, MAX_ATTEMPTS = 16, 128, 64
MAX_JSON, MAX_LOG = 4 * 1024 * 1024, 512 * 1024
BACKUP_FILES, BACKUP_BYTES, DISK_RESERVE = 8, 2 * 1024 ** 3, 512 * 1024 ** 2


def file_sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def read_json(path, maximum=MAX_JSON):
    path = safe_path(path)
    require(path.stat().st_size <= maximum, 'MC_MAINTENANCE_FILE_LIMIT')
    data = path.read_bytes()
    require(len(data) <= maximum, 'MC_MAINTENANCE_FILE_LIMIT')
    return parse(data)


def exclusive_json(path, value):
    data = canonical(value) + b'\n'
    require(len(data) <= MAX_JSON, 'MC_MAINTENANCE_FILE_LIMIT')
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def folder(parent, name):
    path = parent / name
    path.mkdir(exist_ok=True)
    result = safe_path(path, directory=True)
    require(result.parent == parent, 'MC_MAINTENANCE_PATH_TYPE')
    return result


class NativeRuntime:
    """Only the fixed journal main class; arguments never pass through a shell."""
    def __init__(self, configuration):
        self.configuration = safe_path(configuration)
        self.value = read_json(self.configuration)
        require(set(self.value) == {'schema_version', 'java', 'classpath'} and self.value['schema_version'] == 1,
                'MC_MAINTENANCE_RUNTIME_CONFIG')
        require(isinstance(self.value['classpath'], list) and 1 <= len(self.value['classpath']) <= 32,
                'MC_MAINTENANCE_RUNTIME_CONFIG')
        self.identity = self.verify()
        version = subprocess.run([self.value['java']['path'], '-version'], capture_output=True, timeout=10, check=False)
        require(version.returncode == 0 and re.search(rb'(?:openjdk|java) version "21(?:\.|[+"]|$)', version.stdout + version.stderr),
                'MC_MAINTENANCE_JAVA_VERSION')

    def verify(self):
        require(read_json(self.configuration) == self.value, 'MC_MAINTENANCE_RUNTIME_CHANGED')
        files, seen = {}, set()
        for index, entry in enumerate([self.value['java'], *self.value['classpath']]):
            require(isinstance(entry, dict) and set(entry) == {'path', 'sha256'} and isinstance(entry['path'], str)
                    and isinstance(entry['sha256'], str) and SHA.fullmatch(entry['sha256']), 'MC_MAINTENANCE_RUNTIME_CONFIG')
            path = Path(entry['path'])
            path = safe_path(path, directory=path.is_dir())
            require(str(path).casefold() not in seen, 'MC_MAINTENANCE_RUNTIME_CONFIG')
            seen.add(str(path).casefold())
            require(index != 0 or path.is_file() and path.name.lower() == 'java.exe', 'MC_MAINTENANCE_RUNTIME_CONFIG')
            if path.is_dir():
                values = {}
                for directory, dirs, names in os.walk(path):
                    for name in [*dirs, *names]:
                        safe_path(Path(directory) / name, directory=name in dirs)
                    for name in names:
                        item = Path(directory) / name
                        values[item.relative_to(path).as_posix()] = file_sha(item)
                        require(len(values) <= 3000, 'MC_MAINTENANCE_RUNTIME_LIMIT')
                actual = digest(values)
                require(values, 'MC_MAINTENANCE_RUNTIME_CONFIG')
            else:
                require(index == 0 or path.suffix.lower() == '.jar', 'MC_MAINTENANCE_RUNTIME_CONFIG')
                actual = file_sha(path)
            require(actual == entry['sha256'], 'MC_MAINTENANCE_RUNTIME_CHANGED')
            files[str(path)] = actual
        identity = digest({'configuration': self.value, 'files': files})
        require(not hasattr(self, 'identity') or self.identity == identity, 'MC_MAINTENANCE_RUNTIME_CHANGED')
        return identity

    def invoke(self, action, journal, extra, work):
        self.verify()
        logs = folder(work, 'native-logs')
        require(len(list(logs.iterdir())) < MAX_LOGS, 'MC_MAINTENANCE_LOG_LIMIT')
        path = logs / ('native-' + str(uuid.uuid4()) + '.log')
        # The temporary tree is created and owned by this call; cleanup stays
        # inside the verified maintenance directory, never a user-supplied tree.
        with tempfile.TemporaryDirectory(prefix='native-temp-', dir=work) as temporary:
            require(Path(temporary).resolve().parent == work, 'MC_MAINTENANCE_PATH_TYPE')
            argv = [self.value['java']['path'], '-Xmx512m', '-Dorg.sqlite.tmpdir=' + temporary,
                    '-cp', os.pathsep.join(entry['path'] for entry in self.value['classpath']),
                    'dev.aitalkstreamer.mc.core.JournalMaintenanceCli', '--directory', str(journal), '--action', action, *extra]
            with path.open('xb') as output:
                process = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT, cwd=work, shell=False)
                started = time.monotonic()
                try:
                    while process.poll() is None:
                        require(time.monotonic() - started <= 40, 'MC_MAINTENANCE_NATIVE_TIMEOUT')
                        require(path.stat().st_size <= MAX_LOG, 'MC_MAINTENANCE_NATIVE_OUTPUT_LIMIT')
                        try:
                            process.wait(timeout=0.1)
                        except subprocess.TimeoutExpired:
                            pass
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
        require(path.stat().st_size <= MAX_LOG, 'MC_MAINTENANCE_NATIVE_OUTPUT_LIMIT')
        self.verify()
        values = [parse(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.startswith('{')]
        require(len(values) == 1 and isinstance(values[0], dict), 'MC_MAINTENANCE_NATIVE_RESULT')
        value = values[0]
        if process.returncode:
            code = value.get('error')
            raise MaintenanceError(code if isinstance(code, str) and re.fullmatch(r'GAME_[A-Z0-9_]{1,100}', code)
                                   else 'MC_MAINTENANCE_NATIVE_FAILED')
        return value


class MaintenanceCoordinator:
    def __init__(self, application_database, journal, runtime, installation):
        self.database = safe_path(application_database)
        self.journal = safe_path(journal, directory=True)
        require((self.journal / 'mc-control.sqlite3').is_file(), 'MC_MAINTENANCE_B_MISSING')
        safe_path(self.journal / 'mc-control.sqlite3')
        self.runtime, self.installation = runtime, installation
        self.work = folder(self.database.parent, 'maintenance')
        self.plans = folder(self.work, 'plans')
        self.attempts = folder(self.work, 'attempts')

    def binding(self):
        return {'application_database': str(self.database), 'journal_directory': str(self.journal),
                'runtime_sha256': self.runtime.verify(), 'installation': self.installation}

    def dependencies(self):
        with application_fence(self.database) as db:
            return capture(db)

    def status(self):
        with application_fence(self.database) as db:
            dependencies = capture(db)
            native = self.runtime.invoke('status', self.journal, [], self.work)
            require(native.get('game_instance_id') == dependencies['game_instance_id'], 'MC_MAINTENANCE_INSTANCE_MISMATCH')
            return {'game_instance_id': dependencies['game_instance_id'], 'a_snapshot_sha256': dependencies['snapshot_sha256'],
                    'protected_tasks': len(dependencies['task_ids']), 'protection_counts': dependencies['protection_counts'],
                    'b_status': native, 'services_started': False, 'automatic_input_authorized': False}

    def preview(self):
        with application_fence(self.database) as db:
            dependencies, binding = capture(db), self.binding()
            require(len(list(self.plans.glob('maintenance-*.json'))) < MAX_PLANS * 2, 'MC_MAINTENANCE_PLAN_LIMIT')
            require(sum(path.stat().st_size for path in self.plans.iterdir()) < MAX_PLANS * MAX_JSON * 2,
                    'MC_MAINTENANCE_PLAN_LIMIT')
            plan_id = 'maintenance-' + str(uuid.uuid4())
            protection = {'game_instance_id': dependencies['game_instance_id'], 'task_ids': dependencies['task_ids']}
            protection_path = self.plans / (plan_id + '.protection.json')
            protection_sha = exclusive_json(protection_path, protection)
            native = self.runtime.invoke('preview', self.journal, ['--protect', str(protection_path)], self.work)
            require(native.get('game_instance_id') == dependencies['game_instance_id'] and native.get('applied') is False
                    and native.get('additional_task_protection_supplied') is True, 'MC_MAINTENANCE_NATIVE_RESULT')
            require(isinstance(native.get('plan_file'), str) and B_PLAN.fullmatch(native['plan_file'])
                    and isinstance(native.get('plan_sha256'), str) and SHA.fullmatch(native['plan_sha256']), 'MC_MAINTENANCE_NATIVE_RESULT')
            b_file = safe_path(self.journal / 'maintenance' / native['plan_file'])
            require(file_sha(b_file) == native['plan_sha256'], 'MC_MAINTENANCE_B_PLAN_CHANGED')
            b_plan = read_json(b_file, 32 * 1024 * 1024)
            require(b_plan['game_instance_id'] == dependencies['game_instance_id']
                    and b_plan['protected_task_ids'] == dependencies['task_ids']
                    and b_plan['counts'] == native['counts'] and b_plan['expires_at_ms'] == native['expires_at_ms'],
                    'MC_MAINTENANCE_NATIVE_RESULT')
            plan = {'format_version': 1, 'plan_id': plan_id, 'binding': binding, 'a_dependencies': dependencies,
                    'protection_file': protection_path.name, 'protection_sha256': protection_sha,
                    'b_preview': native, 'created_at': datetime.now(timezone.utc).isoformat()}
            name = plan_id + '.json'
            reviewed_sha = exclusive_json(self.plans / name, plan)
            return {'plan_file': name, 'plan_sha256': reviewed_sha, 'game_instance_id': dependencies['game_instance_id'],
                    'protected_tasks': len(dependencies['task_ids']), 'protection_counts': dependencies['protection_counts'],
                    'expires_at_ms': native['expires_at_ms'], 'counts': native['counts'], 'applied': False}

    def load(self, name, reviewed_sha):
        require(isinstance(name, str) and PLAN.fullmatch(name) and isinstance(reviewed_sha, str) and SHA.fullmatch(reviewed_sha),
                'MC_MAINTENANCE_PLAN_ARGUMENT')
        path = safe_path(self.plans / name)
        require(file_sha(path) == reviewed_sha, 'MC_MAINTENANCE_PLAN_HASH')
        plan = read_json(path)
        require(isinstance(plan, dict) and set(plan) == {'format_version', 'plan_id', 'binding', 'a_dependencies',
                'protection_file', 'protection_sha256', 'b_preview', 'created_at'}
                and plan.get('format_version') == 1 and isinstance(plan.get('plan_id'), str) and plan['plan_id'] + '.json' == name
                and plan.get('binding') == self.binding(), 'MC_MAINTENANCE_PLAN_BINDING')
        require(plan.get('protection_file') == plan['plan_id'] + '.protection.json', 'MC_MAINTENANCE_PLAN_BINDING')
        protection = safe_path(self.plans / plan['protection_file'])
        require(file_sha(protection) == plan['protection_sha256'], 'MC_MAINTENANCE_PROTECTION_CHANGED')
        require(read_json(protection) == {'game_instance_id': plan['a_dependencies']['game_instance_id'],
                                       'task_ids': plan['a_dependencies']['task_ids']}, 'MC_MAINTENANCE_PROTECTION_CHANGED')
        require(B_PLAN.fullmatch(plan['b_preview']['plan_file']), 'MC_MAINTENANCE_PLAN_BINDING')
        b_file = safe_path(self.journal / 'maintenance' / plan['b_preview']['plan_file'])
        require(file_sha(b_file) == plan['b_preview']['plan_sha256'], 'MC_MAINTENANCE_B_PLAN_CHANGED')
        b_plan = read_json(b_file, 32 * 1024 * 1024)
        require(b_plan['game_instance_id'] == plan['a_dependencies']['game_instance_id']
                and b_plan['protected_task_ids'] == plan['a_dependencies']['task_ids']
                and b_plan['counts'] == plan['b_preview']['counts']
                and b_plan['expires_at_ms'] == plan['b_preview']['expires_at_ms'], 'MC_MAINTENANCE_PROTECTION_CHANGED')
        return plan

    def native_args(self, plan):
        return ['--plan', plan['b_preview']['plan_file'], '--sha256', plan['b_preview']['plan_sha256']]

    def result(self, plan):
        value = self.runtime.invoke('result', self.journal, self.native_args(plan), self.work)
        require(value.get('game_instance_id') == plan['a_dependencies']['game_instance_id']
                and value.get('plan_file_sha256') == plan['b_preview']['plan_sha256']
                and value.get('run_id') + '.json' == plan['b_preview']['plan_file'] and type(value.get('found')) is bool,
                'MC_MAINTENANCE_NATIVE_RESULT')
        if value['found']:
            result = value.get('result')
            require(isinstance(result, dict) and result.get('game_instance_id') == value['game_instance_id']
                    and result.get('run_id') == value['run_id'] and result.get('counts') == plan['b_preview']['counts']
                    and result.get('originals_in_backup') is True, 'MC_MAINTENANCE_NATIVE_RESULT')
        else:
            require(value.get('result') is None, 'MC_MAINTENANCE_NATIVE_RESULT')
        return value

    def reconcile(self, name, reviewed_sha):
        with application_fence(self.database) as db:
            plan = self.load(name, reviewed_sha)
            require(capture(db)['game_instance_id'] == plan['a_dependencies']['game_instance_id'], 'MC_MAINTENANCE_INSTANCE_MISMATCH')
            value = self.result(plan)
            observation = {'outcome': 'confirmed_in_current_b_ledger' if value['found'] else 'not_found_in_current_b_ledger',
                           'b_observation': value, 'apply_command_dispatched': False, 'automatic_input_authorized': False}
            require(len(list(self.attempts.glob('*.observation.json'))) < MAX_ATTEMPTS, 'MC_MAINTENANCE_ATTEMPT_LIMIT')
            exclusive_json(self.attempts / ('reconcile-' + str(uuid.uuid4()) + '.observation.json'),
                           {'plan_id': plan['plan_id'], 'plan_sha256': reviewed_sha, **observation})
            return observation

    def backup(self, db, plan):
        directory = folder(self.work, 'backups')
        files = list(directory.iterdir())
        for path in files:
            safe_path(path)
        require(len([path for path in files if path.suffix == '.sqlite3']) < BACKUP_FILES, 'MC_MAINTENANCE_BACKUP_LIMIT')
        b_directory = self.journal / 'backups'
        b_files = []
        if b_directory.exists():
            safe_path(b_directory, directory=True)
            b_files = list(b_directory.iterdir())
            for path in b_files:
                safe_path(path)
        page_bytes = db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
        # Include the existing B snapshots and conservatively reserve a new B
        # snapshot, including committed WAL, before either side can be pruned.
        b_bytes = sum(path.stat().st_size for path in [self.journal / 'mc-control.sqlite3', self.journal / 'mc-control.sqlite3-wal'] if path.exists())
        require(sum(path.stat().st_size for path in [*files, *b_files]) + page_bytes + b_bytes <= BACKUP_BYTES,
                'MC_MAINTENANCE_BACKUP_BYTES')
        shared_volume = directory.stat().st_dev == self.journal.stat().st_dev
        require(shutil.disk_usage(directory).free >= page_bytes + (b_bytes if shared_volume else 0) + DISK_RESERVE,
                'MC_MAINTENANCE_DISK_RESERVE')
        require(shutil.disk_usage(self.journal).free >= b_bytes + DISK_RESERVE, 'MC_MAINTENANCE_DISK_RESERVE')
        path = directory / ('a-' + str(uuid.uuid4()) + '.sqlite3')
        # A's writer fence remains held. A separate reader avoids attempting a
        # backup from inside the source connection's own write transaction.
        with path.open('xb'):
            pass
        source = sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True, timeout=0)
        target = sqlite3.connect(path)
        try:
            source.backup(target)
            require(target.execute('PRAGMA quick_check(1)').fetchone()[0] == 'ok', 'MC_MAINTENANCE_BACKUP_INTEGRITY')
        finally:
            target.close()
            source.close()
        require(path.stat().st_size <= page_bytes, 'MC_MAINTENANCE_BACKUP_BYTES')
        receipt = {'format_version': 1, 'plan_id': plan['plan_id'], 'file': path.name, 'sha256': file_sha(path),
                   'a_snapshot_sha256': plan['a_dependencies']['snapshot_sha256'], 'application_database': str(self.database),
                   'game_instance_id': plan['a_dependencies']['game_instance_id'], 'bytes': path.stat().st_size,
                   'scope': 'A_GAME_DATABASE_ONLY_NOT_MC_WORLD_OR_HUMANITY_BACKUP'}
        exclusive_json(path.with_suffix('.sqlite3.json'), receipt)
        return receipt

    def apply(self, name, reviewed_sha):
        with application_fence(self.database) as db:
            plan = self.load(name, reviewed_sha)
            observed = self.result(plan)
            if observed['found']:
                return {'outcome': 'confirmed_in_current_b_ledger', 'duplicate': True, 'result': observed['result'],
                        'apply_command_dispatched': False, 'automatic_input_authorized': False}
            dependencies = capture(db)
            require(dependencies == plan['a_dependencies'], 'MC_MAINTENANCE_A_CHANGED')
            require(plan['b_preview']['expires_at_ms'] > int(time.time() * 1000), 'MC_MAINTENANCE_PLAN_EXPIRED')
            require(plan['b_preview']['counts']['events'] + plan['b_preview']['counts']['tasks'] > 0,
                    'MC_MAINTENANCE_NOTHING_TO_APPLY')
            require(len(list(self.attempts.glob('*.started.json'))) < MAX_ATTEMPTS, 'MC_MAINTENANCE_ATTEMPT_LIMIT')
            attempt = 'attempt-' + str(uuid.uuid4())
            started = {'format_version': 1, 'attempt_id': attempt, 'plan_id': plan['plan_id'], 'plan_sha256': reviewed_sha,
                       'phase': 'started', 'at': datetime.now(timezone.utc).isoformat()}
            exclusive_json(self.attempts / (attempt + '.started.json'), started)
            dispatched = False
            try:
                backup = self.backup(db, plan)
                require(capture(db) == dependencies, 'MC_MAINTENANCE_A_CHANGED')
                dispatched = True
                self.runtime.invoke('apply', self.journal, self.native_args(plan), self.work)
                # Read back the committed run; a process exit or stdout line
                # alone is never a cross-database success receipt.
                proof = self.result(plan)
                require(proof['found'], 'MC_MAINTENANCE_COMMIT_UNPROVEN')
                value = {'outcome': 'confirmed_in_current_b_ledger', 'duplicate': False, 'result': proof['result'],
                         'a_backup': backup, 'apply_command_dispatched': True, 'automatic_input_authorized': False}
                exclusive_json(self.attempts / (attempt + '.outcome.json'), {'attempt_id': attempt, **value})
                return value
            except Exception as error:
                outcome = 'unknown' if dispatched else 'not_dispatched'
                code = error.code if isinstance(error, MaintenanceError) else 'MC_MAINTENANCE_FAILED'
                try:
                    exclusive_json(self.attempts / (attempt + '.outcome.json'),
                                   {'attempt_id': attempt, 'outcome': outcome, 'code': code})
                except Exception as record_error:
                    # A partial or unavailable result file must never turn a
                    # potentially committed B operation into "not dispatched".
                    # Preserve its bytes and return uncertainty for readback.
                    raise MaintenanceError('MC_MAINTENANCE_OUTCOME_UNRECORDED', outcome) from record_error
                raise MaintenanceError(code, outcome) from error
