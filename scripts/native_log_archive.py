"""Preserve an oversized stopped-game console before opening the next session's log."""
from pathlib import Path
import os
import stat
import uuid
from native_operation import OperationError, safe_path

CONSOLE_LIMIT_BYTES = 16 * 1024 * 1024


def prepare_console_log(root, path, *, maximum_bytes=CONSOLE_LIMIT_BYTES):
    root = Path(root).resolve()
    path = safe_path(root, path)
    relative = path.relative_to(root)
    if (len(relative.parts) != 6 or relative.parts[:2] != ('runtime', 'minecraft')
            or relative.parts[-3:] != ('work', 'logs', 'application-console.log')
            or type(maximum_bytes) is not int or not 1 <= maximum_bytes <= CONSOLE_LIMIT_BYTES):
        raise OperationError('MC_CONSOLE_LOG_SCOPE_INVALID')
    result = {'path': relative.as_posix(), 'maximum_bytes': maximum_bytes,
              'rotation_scope': 'STARTUP_ONLY_NOT_A_CONTINUOUS_LOG_SIZE_GUARANTEE',
              'rotated': False, 'previous_bytes': 0, 'archive_path': None,
              'existing_bytes_deleted_or_truncated': False, 'full_file_digest_computed': False}
    try:
        before = path.lstat()
    except FileNotFoundError:
        return result
    if not stat.S_ISREG(before.st_mode):
        raise OperationError('MC_CONSOLE_LOG_NOT_REGULAR')
    result['previous_bytes'] = before.st_size
    if before.st_size < maximum_bytes:
        return result
    archive_root = safe_path(root, path.parent / 'console-archive')
    archive_root.mkdir(exist_ok=True)
    archive_root = safe_path(root, archive_root)
    destination = safe_path(root, archive_root / uuid.uuid4().hex / path.name)
    destination.parent.mkdir(exist_ok=False)
    destination = safe_path(root, destination)
    # Called only after the game service has verified that its old Java player is
    # absent. Windows refuses the rename if another handle disallows deletion.
    # A unique directory preserves every previous archive and avoids replacement.
    os.rename(path, destination)
    after = destination.lstat()
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if signature(before) != signature(after):
        raise OperationError('MC_CONSOLE_LOG_CHANGED_DURING_ARCHIVE')
    result.update(rotated=True, archive_path=destination.relative_to(root).as_posix(),
                  preserved_file_identity_and_size=True, preserved_mtime=True)
    return result
