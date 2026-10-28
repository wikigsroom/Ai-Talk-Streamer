"""Inventory or delete only retired K03/K04/K05 installations after K02 activation.

Default inventories model files and writes a receipt. --apply removes the exact allowlist, never follows a
reparse point, never downloads anything, and preserves historical test media.
Run with the retained native LiveTalking Python; it supplies psutil.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat


TARGETS = (
    'models/lipsync-benchmark/feather',
    'models/lipsync-benchmark/latent',
    'models/lipsync-benchmark/wav2lip',
    'runtime/lipsync-benchmark/feather',
    'runtime/lipsync-benchmark/latent',
    'cache/lipsync-benchmark',
    'src/lipsync-benchmark/feather/feather_hubert.pth',
    'src/lipsync-benchmark/feather/data_utils/checkpoint_epoch_335.pth.tar',
    'src/lipsync-benchmark/feather/data_utils/scrfd_2.5g_kps.onnx',
)
PROTECTED = ('src/LiveTalking', 'runtime/livetalking', 'runtime/tts',
    'assets', 'state', 'backups', 'outputs', 'Ai-Talk-Streamer',
    'models/tts-benchmark', 'runtime/tts-benchmark')


def safe_target(root, relative):
    if relative not in TARGETS:
        raise ValueError('Deletion target is outside the reviewed allowlist')
    root = Path(root).resolve(strict=True)
    path = root/relative
    if path == root or not path.resolve().is_relative_to(root):
        raise ValueError('Deletion target escapes project root')
    # Check ancestors before traversing. Windows junctions are not is_symlink().
    for part in (path, *path.parents):
        if part == root:
            break
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Reparse point in deletion path: '+str(part))
    for name in PROTECTED:
        if path.is_relative_to(root/name):
            raise ValueError('Deletion overlaps a protected path')
    return path


def inventory(root, relative):
    target = safe_target(root, relative)
    rows = []
    if not target.exists():
        return {'path':relative, 'exists':False, 'files':[], 'logical_bytes':0}
    paths = [target] if target.is_file() else target.rglob('*')
    for path in paths:
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse point inside deletion tree: '+str(path))
        if stat.S_ISREG(info.st_mode):
            rows.append({'path':path.relative_to(root).as_posix(), 'bytes':info.st_size,
                'mtime_ns':info.st_mtime_ns, 'links':info.st_nlink})
    rows.sort(key=lambda item:item['path'])
    return {'path':relative, 'exists':True, 'files':rows,
        'logical_bytes':sum(item['bytes'] for item in rows)}


def history_fingerprint(root):
    """Hash metadata of every history file; hash the approved audio/video bytes."""
    records = []
    for name in ('outputs/lipsync-k01-k05-60s-20261028',
                 'Ai-Talk-Streamer/docs/analysis/lipsync-k01-k05-20261028'):
        folder = root/name
        if not folder.exists():
            continue
        for path in folder.rglob('*'):
            if path.is_file():
                info = path.stat()
                records.append((path.relative_to(root).as_posix(), info.st_size, info.st_mtime_ns))
    raw = []
    for folder in ('outputs/lipsync-k01-k05-60s-20261028',
                   'Ai-Talk-Streamer/docs/analysis/lipsync-k01-k05-20261028'):
        for name in ('audio/common-60s.wav', 'K02/K02-60s.mp4'):
            path = root/folder/name
            if path.is_file():
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024), b''):
                        digest.update(chunk)
                raw.append((path.relative_to(root).as_posix(), digest.hexdigest()))
    records.sort()
    return {'metadata_sha256':hashlib.sha256(json.dumps(records).encode()).hexdigest(),
        'files':len(records), 'selected_raw_sha256':raw}


def assert_inactive(root):
    import psutil
    blocked = []
    benchmark = str(root/'operations/k01-k05-60s-20261028').casefold()
    for process in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
        if process.pid == os.getpid():
            continue
        try:
            args = process.info['cmdline'] or []
            exe = process.info['exe'] or ''
            text = ' '.join(args).replace('/', '\\').casefold()
            dedicated = any(str(root/name).casefold() in text or
                (exe and Path(exe).is_relative_to(root/name)) for name in TARGETS)
            bench_job = benchmark in text and not any(name in text for name in
                ('serve_remote_review.py', 'range_http.py', 'refresh_review_server.py'))
            if dedicated or bench_job:
                blocked.append({'pid':process.pid, 'name':process.info['name']})
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            if (process.info['name'] or '').lower() in ('python.exe', 'pythonw.exe', 'ffmpeg.exe'):
                raise RuntimeError('Cannot verify ownership of a media/Python process')
    if blocked:
        raise RuntimeError('Retired model job still active; no deletion: '+json.dumps(blocked))


def remove_readonly(function, filename, exc_info):
    if not isinstance(exc_info[1], PermissionError):
        raise exc_info[1]
    os.chmod(filename, stat.S_IWRITE | stat.S_IREAD)
    function(filename)


def cleanup(root, apply=False):
    root = Path(root).resolve(strict=True)
    if apply:
        activation = json.loads((root/'.setup/k02/activation.json').read_text('utf-8-sig'))
        if activation.get('profile', {}).get('id') != 'K02':
            raise RuntimeError('Activate K02 before deleting candidate installations')
        assert_inactive(root)
    rows = [inventory(root, name) for name in TARGETS]
    before = history_fingerprint(root)
    free_before = shutil.disk_usage(root).free
    receipt = {'at':datetime.datetime.now().astimezone().isoformat(),
        'mode':'apply' if apply else 'inventory', 'selection':'K02',
        'targets':rows, 'logical_bytes':sum(row['logical_bytes'] for row in rows),
        'disk_free_before':free_before, 'deleted':[], 'history_before':before,
        'models_restored_or_downloaded':False, 'processes_terminated':False}
    out = root/'.setup/k02'
    out.mkdir(parents=True, exist_ok=True)
    pending = out/'cleanup-plan.json'
    pending.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    if apply:
        # Finish all preflight checks before the first mutation. Re-check each
        # full tree immediately before deletion to catch changes since inventory.
        for row in rows:
            if inventory(root, row['path']) != row:
                raise RuntimeError('Deletion tree changed after inventory')
        for row in rows:
            target = safe_target(root, row['path'])
            if not row['exists']:
                continue
            if inventory(root, row['path']) != row:
                raise RuntimeError('Deletion tree changed before removal')
            if target.is_dir():
                shutil.rmtree(target, onerror=remove_readonly)
            else:
                try:
                    target.unlink()
                except PermissionError:
                    target.chmod(stat.S_IWRITE | stat.S_IREAD)
                    target.unlink()
            receipt['deleted'].append(row['path'])
            (out/'cleanup-progress.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        receipt['history_after'] = history_fingerprint(root)
        receipt['history_unchanged'] = before == receipt['history_after']
        receipt['targets_absent'] = all(not (root/name).exists() for name in TARGETS)
        receipt['disk_free_after'] = shutil.disk_usage(root).free
        receipt['disk_free_delta'] = receipt['disk_free_after']-free_before
        receipt['ok'] = receipt['history_unchanged'] and receipt['targets_absent']
        (out/'cleanup-result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        if not receipt['ok']:
            raise RuntimeError('Cleanup verification failed; inspect project-local receipt')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = cleanup(args.root, args.apply)
    print(json.dumps({key:value for key,value in result.items() if key not in ('targets',)}, ensure_ascii=False))
