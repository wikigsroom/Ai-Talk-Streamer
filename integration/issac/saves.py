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
WINDOW_POSITION = re.compile(
    rb'(?m)^([ \t]*(WindowPosX|WindowPosY)[ \t]*=[ \t]*)(-?[0-9]{1,11})([ \t]*)(\r?\n|$)')


def save_file(path):
    return bool(SLOT_FILE.fullmatch(path.name)) or path.suffix.lower() in {'.sav','.ini'}


def window_position_only(original, current):
    """Permit only two signed integer values; preserve every other byte.

    In particular, this does not parse/rewrite or rebaseline an INI file. New,
    missing or duplicate keys, changed whitespace/line endings, console settings
    and all non-position options remain protection failures.
    """
    def normalize(content):
        matches=list(WINDOW_POSITION.finditer(content))
        key_count=len(re.findall(rb'(?mi)^[ \t]*(?:WindowPosX|WindowPosY)[ \t]*=',content))
        if (len(matches)!=2 or key_count!=2 or {m[2] for m in matches}!={b'WindowPosX',b'WindowPosY'}
                or any(not -(2**31)<=int(m[3])<2**31 for m in matches)):
            return None
        return WINDOW_POSITION.sub(lambda m:m[1]+b'<position>'+m[4]+m[5],content)
    baseline=normalize(original);observed=normalize(current)
    return baseline is not None and observed is not None and baseline==observed


class SaveProtection:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.folder = inside(self.root, 'state/isaac-strategy/save-protection')
        self.manifest = self.folder/'baseline.json'

    def prepare(self, roots, *, first_boot_root=None):
        if self.manifest.exists():
            self.verify()
            existing = read_json(self.manifest)
            observed=[str(Path(x).resolve()) for x in roots]
            if set(observed)!=set(existing['roots']):
                return self.extend_first_boot_root(existing,observed,first_boot_root)
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

    def game_stopped(self):
        import psutil
        for process in psutil.process_iter(['name']):
            try:
                if (process.info['name'] or '').lower()=='isaac-ng.exe':
                    raise AdmissionError('SAVE_ROOT_EXTENSION_REQUIRES_GAME_STOPPED')
            except psutil.NoSuchProcess:continue

    def extend_first_boot_root(self, existing, observed, expected):
        """Append only the pinned first-boot config directory, before any saves.

        The original baseline ID, protected hashes and all old backups survive.
        A new slot file (including slot 3), unknown file, moved root or live game
        requires investigation; it is never silently accepted as a new baseline.
        """
        self.game_stopped()
        added=set(observed)-set(existing['roots'])
        if (expected is None or set(existing['roots'])-set(observed) or len(added)!=1
                or str(Path(expected).resolve()) not in added):
            raise AdmissionError('SAVE_ROOT_SET_CHANGED')
        expected=Path(expected)
        # A known-folder parent may itself be redirected. The newly observed
        # game directory must not be a junction or link to a different root.
        source=expected.parent.resolve()/expected.name
        if (source.name!='Binding of Isaac Repentance' or source.resolve()!=source
                or not source.is_dir()):
            raise AdmissionError('FIRST_BOOT_CONFIG_ROOT_INVALID')
        paths=sorted(source.iterdir())
        if not paths or any(not p.is_file() or p.is_symlink() or p.name.lower() not in {'options.ini','log.txt'} for p in paths):
            raise AdmissionError('FIRST_BOOT_CONFIG_ONLY_NO_SAVE_FILES_REQUIRED')
        if not any(p.name.lower()=='options.ini' for p in paths):
            raise AdmissionError('FIRST_BOOT_OPTIONS_REQUIRED')
        extension=self.folder/'root-extensions'/uuid.uuid4().hex
        extension.mkdir(parents=True)
        original=extension/'baseline.before.json'
        shutil.copy2(self.manifest,original)
        original_sha=file_hash(self.manifest)
        if file_hash(original)!=original_sha:
            raise AdmissionError('SAVE_BASELINE_BACKUP_FAILED')
        index=len(existing['roots']);snapshots=[];new_rows=[]
        for path in paths:
            target=extension/'files'/path.name;target.parent.mkdir(exist_ok=True)
            sha=file_hash(path);shutil.copy2(path,target)
            if file_hash(path)!=sha or file_hash(target)!=sha:
                raise AdmissionError('SAVE_CHANGED_DURING_BACKUP')
            row={'root':index,'relative':path.name,'source':str(path),'backup':str(target),
                 'sha256':sha,'bytes':path.stat().st_size,'slot':None}
            snapshots.append(row)
            if save_file(path):new_rows.append(row)
        self.game_stopped()
        if set(source.iterdir())!=set(paths) or file_hash(self.manifest)!=original_sha:
            raise AdmissionError('SAVE_ROOT_CHANGED_DURING_EXTENSION')
        updated={**existing,'roots':[*existing['roots'],str(source)],'files':[*existing['files'],*new_rows],
            'authorized_root_additions':[*existing.get('authorized_root_additions',[]),{
                'reason':'pinned_first_boot_config_only_no_slot_files','root':str(source),
                'original_baseline_id':existing['id'],'original_manifest_sha256':original_sha,
                'original_manifest_backup':str(original),'first_boot_files':snapshots,
                'normal_gameplay_values_changed':False,'at_unix':time.time()}]}
        write_json(self.manifest,updated)
        try:self.verify()
        except Exception:
            write_json(self.manifest,existing)
            raise
        return updated

    def verify(self):
        if not self.manifest.is_file():
            raise AdmissionError('SAVE_BASELINE_MISSING')
        record = read_json(self.manifest)
        if record.get('allowed_slot') != 3:
            raise AdmissionError('SAVE_AUTHORIZATION_MISMATCH')
        known = set();window_changes=[]
        for addition in record.get('authorized_root_additions',[]):
            prior=Path(addition['original_manifest_backup'])
            if (not prior.resolve().is_relative_to(self.folder) or not prior.is_file()
                    or file_hash(prior)!=addition['original_manifest_sha256']):
                raise AdmissionError('SAVE_BASELINE_HISTORY_CHANGED')
            for snapshot in addition['first_boot_files']:
                backup=Path(snapshot['backup'])
                if (not backup.resolve().is_relative_to(self.folder) or not backup.is_file()
                        or file_hash(backup)!=snapshot['sha256']):
                    raise AdmissionError('FIRST_BOOT_CONFIG_BACKUP_CHANGED')
        for row in record['files']:
            source, backup = Path(row['source']), Path(row['backup'])
            if not backup.resolve().is_relative_to(self.folder.resolve()) or not backup.is_file() or file_hash(backup) != row['sha256']:
                raise AdmissionError('SAVE_BACKUP_CHANGED')
            known.add(str(source.resolve()))
            # Slot 3 evolves through normal gameplay. Only numeric desktop
            # position values may differ in options.ini; original configuration
            # bytes and backups are never rewritten or rebaselined.
            if row.get('slot') != 3:
                if not source.is_file():
                    raise AdmissionError('PROTECTED_SAVE_CHANGED')
                current_sha=file_hash(source)
                if current_sha!=row['sha256']:
                    if source.name.lower()!='options.ini' or not window_position_only(backup.read_bytes(),source.read_bytes()):
                        raise AdmissionError('PROTECTED_SAVE_CHANGED')
                    window_changes.append({'root':row['root'],'relative':row['relative'],
                        'permitted_option_names':['WindowPosX','WindowPosY'],
                        'baseline_sha256':row['sha256'],'observed_sha256':current_sha})
        for name in record['roots']:
            for path in Path(name).rglob('*'):
                if not path.is_file() or str(path.resolve()) in known:
                    continue
                match = SLOT_FILE.fullmatch(path.name)
                # Normal slot-3 files and runtime logs may appear. A newly
                # created slot-1/2 save is a protection failure, not a new baseline.
                if match and int(match[1]) != 3:
                    raise AdmissionError('UNAUTHORIZED_SAVE_SLOT_CREATED')
                if path.suffix.lower()=='.sav':
                    raise AdmissionError('UNCLASSIFIED_SAVE_FILE_CREATED')
                if path.suffix.lower()=='.ini':
                    raise AdmissionError('UNCLASSIFIED_CONFIGURATION_FILE_CREATED')
        return {'protected_unchanged': True, 'baseline_id': record['id'],
                'allowed_slot': 3, 'baseline_files': len(record['files']),
                'runtime_window_position_changes':window_changes}

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
