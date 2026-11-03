"""Durable single-worker jobs for the independent native maintenance console."""
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
import os
import re
import sqlite3
import threading
import uuid

from mc_maintenance_dependencies import MaintenanceError, canonical, digest, parse, require, safe_path
from mc_maintenance_core import PLAN, SHA, folder

MAX_JOBS, MAX_PENDING, MAX_DB_BYTES = 512, 16, 16 * 1024 * 1024
REQUEST = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
ACTIONS = {'dependencies', 'status', 'preview', 'apply', 'reconcile'}


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_request(value):
    require(isinstance(value, dict), 'MC_MAINTENANCE_REQUEST_INVALID')
    action = value.get('action')
    require(isinstance(action, str) and action in ACTIONS, 'MC_MAINTENANCE_REQUEST_INVALID')
    fields = {'request_id', 'action'} | ({'plan_file', 'plan_sha256'} if action in {'apply', 'reconcile'} else set())
    require(set(value) == fields and isinstance(value.get('request_id'), str) and REQUEST.fullmatch(value['request_id']),
            'MC_MAINTENANCE_REQUEST_INVALID')
    if action in {'apply', 'reconcile'}:
        require(isinstance(value['plan_file'], str) and PLAN.fullmatch(value['plan_file'])
                and isinstance(value['plan_sha256'], str) and SHA.fullmatch(value['plan_sha256']),
                'MC_MAINTENANCE_PLAN_ARGUMENT')
    return value


class ConsoleLock:
    """OS file lock; no PID signalling, stale PID deletion or shared process cleanup."""
    def __init__(self, directory):
        self.path = directory / 'owner.lock'
        if self.path.exists():
            safe_path(self.path)
        self.stream = self.path.open('a+b')
        try:
            safe_path(self.path)
            if self.path.stat().st_size == 0:
                self.stream.write(b'\0'); self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as error:
            self.stream.close()
            raise MaintenanceError('MC_MAINTENANCE_CONSOLE_BUSY') from error

    def close(self):
        if self.stream.closed:
            return
        try:
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()


class JobLedger:
    def __init__(self, directory, installation, *, request_validator=validate_request, uncertain_actions=None):
        self.request_validator = request_validator
        self.uncertain_actions = {'apply'} if uncertain_actions is None else frozenset(uncertain_actions)
        self.directory = folder(directory, 'console')
        self.owner = ConsoleLock(self.directory)
        self.mutex = threading.RLock()
        self.db = None
        try:
            path = self.directory / 'jobs.sqlite3'
            for candidate in [path, *[Path(str(path) + suffix) for suffix in ['-wal', '-shm', '-journal']]]:
                if candidate.exists():
                    safe_path(candidate)
            self.db = sqlite3.connect(path, timeout=0, isolation_level=None, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA foreign_keys=ON')
            with self.transaction():
                tables = self.db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
                if not tables:
                    self.db.execute('CREATE TABLE console_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                    self.db.execute('CREATE TABLE jobs(seq INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT UNIQUE NOT NULL,'
                                    'request_id TEXT UNIQUE NOT NULL,request_sha256 TEXT NOT NULL,request TEXT NOT NULL,'
                                    'binding_sha256 TEXT NOT NULL,action TEXT NOT NULL,state TEXT NOT NULL,'
                                    'outcome TEXT NOT NULL,code TEXT,created_at TEXT NOT NULL,started_at TEXT,'
                                    'finished_at TEXT,result TEXT)')
                    self.db.execute('CREATE TABLE job_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL '
                                    'REFERENCES jobs(job_id),at TEXT NOT NULL,state TEXT NOT NULL,outcome TEXT NOT NULL,code TEXT)')
                    self.db.executemany('INSERT INTO console_meta VALUES(?,?)',
                                        [('schema_version','1'), ('installation', digest(installation))])
                else:
                    require({(row['name'], row['type']) for row in tables} ==
                            {('console_meta','table'), ('jobs','table'), ('job_events','table')},
                            'MC_MAINTENANCE_CONSOLE_SCHEMA')
                    require(dict(self.db.execute('SELECT key,value FROM console_meta')) ==
                            {'schema_version':'1', 'installation':digest(installation)},
                            'MC_MAINTENANCE_CONSOLE_BINDING')
                require(self.db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'MC_MAINTENANCE_CONSOLE_CORRUPT')
                # No restart replays. A running apply may already have committed.
                for row in self.db.execute("SELECT * FROM jobs WHERE state IN ('accepted','running')").fetchall():
                    outcome = 'unknown' if row['state'] == 'running' and row['action'] in self.uncertain_actions else 'not_dispatched' if row['state'] == 'accepted' else 'not_applicable'
                    self._finish(row['job_id'], 'interrupted', outcome, 'MC_MAINTENANCE_CONSOLE_INTERRUPTED', None)
        except Exception:
            self.close()
            raise

    @contextmanager
    def transaction(self):
        with self.mutex:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def capacity(self):
        with self.mutex:
            counts = dict(self.db.execute('SELECT state,count(*) FROM jobs GROUP BY state'))
            return {'jobs':sum(counts.values()), 'pending':counts.get('accepted',0)+counts.get('running',0),
                    'job_limit':MAX_JOBS, 'pending_limit':MAX_PENDING, 'database_byte_limit':MAX_DB_BYTES}

    def enqueue(self, value, binding):
        self.request_validator(value)
        with self.transaction():
            row = self.db.execute('SELECT * FROM jobs WHERE request_id=?', (value['request_id'],)).fetchone()
            if row:
                require(row['request_sha256'] == digest(value), 'MC_MAINTENANCE_REQUEST_CONFLICT')
                return dict(row), True
            capacity = self.capacity()
            require(capacity['pending'] < MAX_PENDING, 'MC_MAINTENANCE_QUEUE_FULL')
            require(capacity['jobs'] < MAX_JOBS and sum(p.stat().st_size for p in self.directory.glob('jobs.sqlite3*'))
                    < MAX_DB_BYTES - 128 * 1024, 'MC_MAINTENANCE_CONSOLE_CAPACITY')
            job = 'job-' + str(uuid.uuid4())
            self.db.execute('INSERT INTO jobs(job_id,request_id,request_sha256,request,binding_sha256,action,state,outcome,created_at) '
                            'VALUES(?,?,?,?,?,?,?,?,?)', (job,value['request_id'],digest(value),canonical(value).decode(),binding,
                                                        value['action'],'accepted','not_dispatched',now()))
            self._event(job,'accepted','not_dispatched',None)
            return dict(self.db.execute('SELECT * FROM jobs WHERE job_id=?',(job,)).fetchone()), False

    def _event(self, job, state, outcome, code):
        self.db.execute('INSERT INTO job_events(job_id,at,state,outcome,code) VALUES(?,?,?,?,?)',(job,now(),state,outcome,code))

    def take(self):
        with self.transaction():
            row = self.db.execute("SELECT * FROM jobs WHERE state='accepted' ORDER BY seq LIMIT 1").fetchone()
            if row is None:
                return None
            outcome = 'unknown' if row['action'] in self.uncertain_actions else 'not_applicable'
            self.db.execute("UPDATE jobs SET state='running',outcome=?,started_at=? WHERE job_id=?",(outcome,now(),row['job_id']))
            self._event(row['job_id'],'running',outcome,None)
            return dict(self.db.execute('SELECT * FROM jobs WHERE job_id=?',(row['job_id'],)).fetchone())

    def _finish(self, job, state, outcome, code, result):
        encoded = canonical(result).decode() if result is not None else None
        require(encoded is None or len(encoded.encode('utf-8')) <= 16 * 1024, 'MC_MAINTENANCE_CONSOLE_RESULT_LIMIT')
        self.db.execute('UPDATE jobs SET state=?,outcome=?,code=?,finished_at=?,result=? WHERE job_id=?',
                        (state,outcome,code,now(),encoded,job))
        self._event(job,state,outcome,code)

    def finish(self, job, state, outcome, code=None, result=None):
        with self.transaction():
            require(self.db.execute('SELECT state FROM jobs WHERE job_id=?',(job,)).fetchone()[0] == 'running',
                    'MC_MAINTENANCE_JOB_STATE')
            self._finish(job,state,outcome,code,result)

    def get(self, key, request=False):
        with self.mutex:
            column = 'request_id' if request else 'job_id'
            row = self.db.execute('SELECT * FROM jobs WHERE '+column+'=?',(key,)).fetchone()
            require(row is not None,'MC_MAINTENANCE_JOB_NOT_FOUND')
            return dict(row)

    def page(self, before=0, through=0):
        with self.mutex:
            current = self.db.execute('SELECT coalesce(max(seq),0) FROM jobs').fetchone()[0]
            through = through or current
            rows = self.db.execute('SELECT * FROM jobs WHERE seq<=? AND (?=0 OR seq<?) ORDER BY seq DESC LIMIT 21',
                                   (through,before,before)).fetchall()
            return {'items':[dict(row) for row in rows[:20]], 'through':through,
                    'next_before':rows[19]['seq'] if len(rows)>20 else None}

    def cancel(self, job):
        with self.transaction():
            row = self.get(job)
            if row['state'] == 'cancelled':
                return row
            require(row['state'] == 'accepted','MC_MAINTENANCE_CANCEL_BLOCKED')
            self._finish(job,'cancelled','not_dispatched',None,None)
            return self.get(job)

    def interrupt_pending(self):
        with self.transaction():
            for row in self.db.execute("SELECT job_id FROM jobs WHERE state='accepted'").fetchall():
                self._finish(row['job_id'],'interrupted','not_dispatched','MC_MAINTENANCE_CONSOLE_STOPPED',None)

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        self.owner.close()
