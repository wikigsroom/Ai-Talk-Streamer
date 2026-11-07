"""Private byte-preserving save backups and native slot/process admission.

No operation here writes gameplay values, unlocks or save contents. Recovery
does not restore live saves automatically or accept a stale PID/slot receipt.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import time
import uuid

from .common import AdmissionError, file_hash, inside, read_json, write_json


GAME_SHA256 = '530b4d2accef833b8dbf6f1a9f781fe1e051c1916ca5acdb579df05a34640627'
SLOT_FILE = re.compile(r'^(?:rep_)?(?:persistentgamedata|gamestate)([123])(?:\.dat)?$', re.I)


def save_file(path):
    return bool(SLOT_FILE.fullmatch(path.name)) or path.suffix.lower() in {'.sav','.ini'}


class SaveProtection:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.folder = inside(self.root, 'state/isaac-strategy/save-protection')
        self.manifest = self.folder/'baseline.json'

    def prepare(self, roots):
        if self.manifest.exists():
            self.verify()
            existing = read_json(self.manifest)
            if [str(Path(x).resolve()) for x in roots] != existing['roots']:
                raise AdmissionError('SAVE_ROOT_SET_CHANGED')
            return existing
        if not isinstance(roots, list) or not roots:
            raise AdmissionError('SAVE_ROOTS_MUST_BE_OBSERVED_BEFORE_LAUNCH')
        self.folder.mkdir(parents=True, exist_ok=True)
        backup = self.folder/('backup-'+uuid.uuid4().hex)
        files, allowed_slot_exists = [], False
        resolved = []
        for index, name in enumerate(roots):
            source = Path(name).resolve()
            if not source.is_dir():
                raise AdmissionError('SAVE_ROOT_NOT_OBSERVED')
            resolved.append(str(source))
            for path in sorted(source.rglob('*')):
                if not path.is_file() or not save_file(path):
                    continue
                relative = path.relative_to(source)
                target = backup/str(index)/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                sha = file_hash(path)
                shutil.copy2(path, target)
                if file_hash(path) != sha or file_hash(target) != sha:
                    raise AdmissionError('SAVE_CHANGED_DURING_BACKUP')
                match = SLOT_FILE.fullmatch(path.name)
                slot = int(match[1]) if match else None
                if slot == 3:
                    allowed_slot_exists = True
                files.append({'root': index, 'relative': relative.as_posix(),
                              'source': str(path), 'backup': str(target),
                              'sha256': sha, 'bytes': path.stat().st_size, 'slot': slot})
        record = {'schema_version': 1, 'id': uuid.uuid4().hex,
                  'created_utc': datetime.now(timezone.utc).isoformat(),
                  'roots': resolved, 'files': files, 'allowed_slot': 3,
                  'slot_3_already_existed': allowed_slot_exists,
                  'slot_3_recreation_allowed': False, 'automatic_restore_allowed': False,
                  'authorized_root_additions': []}
        write_json(self.manifest, record)
        self.verify()
        return record

    def verify(self):
        if not self.manifest.is_file():
            raise AdmissionError('SAVE_BASELINE_MISSING')
        record = read_json(self.manifest)
        if record.get('allowed_slot') != 3:
            raise AdmissionError('SAVE_AUTHORIZATION_MISMATCH')
        known = set()
        for row in record['files']:
            source, backup = Path(row['source']), Path(row['backup'])
            if not backup.resolve().is_relative_to(self.folder.resolve()) or not backup.is_file() or file_hash(backup) != row['sha256']:
                raise AdmissionError('SAVE_BACKUP_CHANGED')
            known.add(str(source.resolve()))
            # Only slot 3 may evolve through normal gameplay. All other files
            # remain protected except the separately backed-up options file.
            if row.get('slot') != 3:
                if not source.is_file() or file_hash(source) != row['sha256']:
                    raise AdmissionError('PROTECTED_SAVE_CHANGED')
        for name in record['roots']:
            for path in Path(name).rglob('*'):
                if not path.is_file() or str(path.resolve()) in known:
                    continue
                match = SLOT_FILE.fullmatch(path.name)
                # Normal slot-3 files and runtime logs may appear. A newly
                # created slot-1/2 save is a protection failure, not a new baseline.
                if match and int(match[1]) != 3:
                    raise AdmissionError('UNAUTHORIZED_SAVE_SLOT_CREATED')
        return {'protected_unchanged': True, 'baseline_id': record['id'],
                'allowed_slot': 3, 'baseline_files': len(record['files'])}

    def bind_live_slot(self, process, native_progress, observed_state):
        self.verify()
        expected_exe = inside(self.root, 'game/isaac-ng.exe')
        if Path(process.exe()).resolve() != expected_exe or file_hash(expected_exe) != GAME_SHA256:
            raise AdmissionError('GAME_PROCESS_OR_EXECUTABLE_CHANGED')
        if native_progress.get('slot') != 3 or native_progress.get('readonly') is not False:
            raise AdmissionError('WRITABLE_NATIVE_SLOT_3_REQUIRED')
        if observed_state.get('dead') or not observed_state.get('players') or observed_state.get('hp', 0) <= 0:
            raise AdmissionError('LIVING_NATIVE_RUN_REQUIRED')
        receipt = {'pid': process.pid, 'created_at': process.create_time(),
                   'executable_sha256': GAME_SHA256, 'slot': 3, 'readonly': False,
                   'checked_unix': time.time(), 'baseline_id': read_json(self.manifest)['id'],
                   'run_seed': observed_state.get('seed'), 'automatic_resume_allowed': False}
        write_json(self.folder/'current-slot.json', receipt)
        return receipt

    def admit_current(self, process, native_progress):
        self.verify()
        receipt = read_json(self.folder/'current-slot.json')
        if (process.pid != receipt['pid'] or process.create_time() != receipt['created_at']
                or Path(process.exe()).resolve() != inside(self.root, 'game/isaac-ng.exe')
                or native_progress.get('slot') != 3 or native_progress.get('readonly') is not False):
            raise AdmissionError('CURRENT_GAME_SLOT_BINDING_CHANGED')
        return receipt
