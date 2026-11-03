"""Read A's recovery dependencies while holding its SQLite writer fence.

This module never migrates, recovers, edits or prunes the application database.
Historical projections do not pin B originals; unresolved and live references do.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import stat


class MaintenanceError(RuntimeError):
    def __init__(self, code, outcome='not_dispatched'):
        super().__init__(code)
        self.code, self.outcome = code, outcome


def require(condition, code):
    if not condition:
        raise MaintenanceError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def parse(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'MC_MAINTENANCE_JSON_DUPLICATE')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: require(False, 'MC_MAINTENANCE_JSON_INVALID'))
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise MaintenanceError('MC_MAINTENANCE_JSON_INVALID') from error


def safe_path(value, directory=False):
    path = Path(value)
    require(path.is_absolute(), 'MC_MAINTENANCE_ABSOLUTE_PATH')
    # Inspect the supplied path before resolving it, including Windows junctions.
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'MC_MAINTENANCE_REPARSE_PATH')
    require(path.is_dir() if directory else path.is_file(), 'MC_MAINTENANCE_PATH_TYPE')
    return path.resolve()


def process_alive(pid):
    require(type(pid) is int and 0 < pid < 2 ** 32, 'MC_MAINTENANCE_A_OWNER_INVALID')
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            require(ctypes.get_last_error() in {87, 1168}, 'MC_MAINTENANCE_A_OWNER_UNCHECKABLE')
            return False
        try:
            result = kernel.WaitForSingleObject(handle, 0)
            require(result in {0, 258}, 'MC_MAINTENANCE_A_OWNER_UNCHECKABLE')
            return result == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as error:
        raise MaintenanceError('MC_MAINTENANCE_A_OWNER_UNCHECKABLE') from error


TABLES = {
    1: {'game_owner', 'schema_migrations', 'meta', 'objects', 'idempotency', 'task_transitions',
        'game_events', 'vote_ballots', 'audit', 'stream_receipts'},
    2: {'world_registry', 'world_bases', 'world_checkpoints', 'task_recovery'},
    3: {'world_sessions', 'world_goals', 'world_goal_tasks', 'task_dispositions'},
    4: {'bridge_history', 'history_partial'},
}
KINDS = {'task', 'operation', 'suggestion', 'vote', 'narration', 'history_import', 'audience_intent',
         'audience_receipt', 'audience_support_manifest', 'audience_support'}
TERMINAL = {'succeeded', 'failed', 'cancelled'}
TASK_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
MAX_ROWS, MAX_BYTES, MAX_RECORD, MAX_TASKS = 500000, 512 * 1024 * 1024, 4 * 1024 * 1024, 20000


@contextmanager
def application_fence(path):
    """Existing stopped A only; BEGIN IMMEDIATE excludes a concurrent startup."""
    path = safe_path(path)
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA trusted_schema=OFF')
        try:
            db.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as error:
            raise MaintenanceError('MC_MAINTENANCE_A_BUSY') from error
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        require({'game_owner', 'schema_migrations'} <= names, 'MC_MAINTENANCE_A_SCHEMA')
        versions = [row[0] for row in db.execute('SELECT version FROM schema_migrations ORDER BY version')]
        require(versions and versions[-1] in TABLES and versions == list(range(1, versions[-1] + 1)), 'MC_MAINTENANCE_A_SCHEMA')
        require(names == set().union(*(TABLES[n] for n in versions)), 'MC_MAINTENANCE_A_SCHEMA')
        require(not db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1").fetchone(), 'MC_MAINTENANCE_A_SCHEMA')
        owners = db.execute('SELECT * FROM game_owner').fetchall()
        require(len(owners) <= 1, 'MC_MAINTENANCE_A_OWNER_INVALID')
        # An expired lease alone never authorizes maintenance of a live process.
        require(not owners or not process_alive(owners[0]['pid']), 'MC_MAINTENANCE_A_RUNNING')
        require(db.execute('PRAGMA quick_check(1)').fetchone()[0] == 'ok', 'MC_MAINTENANCE_A_INTEGRITY')
        yield db
    finally:
        if db.in_transaction:
            db.rollback()
        db.close()


def capture(db):
    """Hash all logical rows; select dependencies from actual recovery consumers."""
    names = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    h = hashlib.sha256()
    total_rows = total_bytes = 0
    content = {}
    for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"):
        h.update(canonical(list(row)) + b'\n')
    for name in names:
        if name == 'game_owner':
            continue
        # Name is from the versioned allowlist verified by application_fence.
        require(name in set().union(*TABLES.values()), 'MC_MAINTENANCE_A_SCHEMA')
        h.update(canonical(name) + b'\n')
        values = []
        for row in db.execute('SELECT rowid,* FROM "' + name + '" ORDER BY rowid'):
            data = canonical(list(row))
            total_rows += 1
            total_bytes += len(data)
            require(len(data) <= MAX_RECORD and total_rows <= MAX_ROWS and total_bytes <= MAX_BYTES,
                    'MC_MAINTENANCE_A_SCAN_LIMIT')
            h.update(str(len(data)).encode('ascii') + b':' + data + b'\n')
            if name in {'meta', 'objects', 'task_recovery', 'task_dispositions', 'world_registry', 'world_bases',
                        'world_checkpoints', 'world_goals', 'world_goal_tasks'}:
                value = dict(row)
                if 'value' in value:
                    value['value'] = parse(value['value'])
                    require(isinstance(value['value'], dict) or name == 'meta', 'MC_MAINTENANCE_A_RECORD')
                values.append(value)
            if name == 'history_partial':
                raise MaintenanceError('MC_MAINTENANCE_A_HISTORY_UNFINISHED')
        content[name] = values
    meta = {row['key']: row['value'] for row in content['meta']}
    instance = meta.get('bound_instance')
    require(isinstance(instance, str) and TASK_ID.fullmatch(instance), 'MC_MAINTENANCE_A_INSTANCE')
    objects = content['objects']
    require(all(row['kind'] in KINDS for row in objects), 'MC_MAINTENANCE_A_OBJECT_KIND')
    tasks = {row['id']: row['value'] for row in objects if row['kind'] == 'task'}
    for task_id, task in tasks.items():
        require(task.get('task_id') == task_id and task.get('game_instance_id') == instance,
                'MC_MAINTENANCE_A_TASK_IDENTITY')
    protected, reasons = set(), {}

    def add(task_id, reason):
        require(isinstance(task_id, str) and TASK_ID.fullmatch(task_id), 'MC_MAINTENANCE_A_TASK_ID')
        protected.add(task_id)
        reasons.setdefault(reason, set()).add(task_id)
        require(len(protected) <= MAX_TASKS, 'MC_MAINTENANCE_A_DEPENDENCY_LIMIT')

    def references(value, reason, depth=0, key=''):
        require(depth <= 32, 'MC_MAINTENANCE_A_NESTING')
        if value is not None and re.search(r'(?:^|_)task_ids?\Z', key):
            if key.endswith('task_ids'):
                require(isinstance(value, list), 'MC_MAINTENANCE_A_TASK_ID')
                for task_id in value:
                    add(task_id, reason)
            else:
                add(value, reason)
            return
        if isinstance(value, dict):
            for child, item in value.items():
                references(item, reason, depth + 1, child)
        elif isinstance(value, list):
            for item in value:
                references(item, reason, depth + 1, key)
        elif isinstance(value, str) and value in tasks:
            add(value, reason)

    for task_id, task in tasks.items():
        if task.get('state') not in TERMINAL or task.get('effect_status') != 'verified':
            add(task_id, 'task_unresolved')
            references(task, 'task_unresolved')
    for row in content.get('task_recovery', []):
        if row['status'] != 'verified':
            add(row['task_id'], 'recovery')
            references(row['value'], 'recovery')
    for row in content.get('task_dispositions', []):
        add(row['task_id'], 'disposition')
        references(row['value'], 'disposition')
    goals = {row['goal_id']: row for row in content.get('world_goals', [])}
    for row in goals.values():
        require(row['status'] == row['value'].get('status'), 'MC_MAINTENANCE_A_GOAL_IDENTITY')
        if row['status'] not in {'completed', 'archived'}:
            references(row['value'], 'world_goal')
    for row in content.get('world_goal_tasks', []):
        require(row['goal_id'] in goals, 'MC_MAINTENANCE_A_DEPENDENCY_ORPHAN')
        if goals[row['goal_id']]['status'] not in {'completed', 'archived'}:
            add(row['task_id'], 'world_goal')
    for name in ['world_registry', 'world_bases', 'world_checkpoints']:
        for row in content.get(name, []):
            references(row['value'], name)
    for row in objects:
        kind, value = row['kind'], row['value']
        state = value.get('state')
        if kind == 'history_import':
            require(state != 'running', 'MC_MAINTENANCE_A_HISTORY_UNFINISHED')
        elif kind == 'task':
            continue
        elif kind == 'operation' and state in TERMINAL:
            continue
        elif kind == 'suggestion' and state in {'rejected', 'expired', 'cancelled'}:
            continue
        elif kind == 'narration':
            if state in {'answered', 'expired', 'discarded', 'cancelled', 'failed'}:
                continue
            if value.get('kind') == 'task_result':
                for task_id in set([value.get('source_id'), *value.get('source_ids', [])]):
                    add(task_id, 'narration')
        # Converted suggestions/closed votes remain linked until A's own retention
        # explicitly closes those dependencies. Read-only imported history is excluded.
        references(value, kind)
    for row in content['meta']:
        references(row['value'], 'metadata')
    return {'schema_version': 1, 'game_instance_id': instance, 'snapshot_sha256': h.hexdigest(),
            'a_schema_version': max(row[0] for row in db.execute('SELECT version FROM schema_migrations')),
            'scanned_rows': total_rows, 'scanned_bytes': total_bytes, 'task_ids': sorted(protected),
            'protection_counts': {key: len(value) for key, value in sorted(reasons.items())}}
