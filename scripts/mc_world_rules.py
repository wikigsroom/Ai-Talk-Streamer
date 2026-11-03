"""Apply only the explicitly requested keepInventory rule to a stopped local save.

Patch the original NBT string bytes, preserving every other uncompressed byte.
No dependency installation, inventory changes or game commands are involved.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import io
import json
import os
import platform
import struct


def rule_span(raw):
    cursor = 0
    found = []

    def take(size):
        nonlocal cursor
        if size < 0 or cursor + size > len(raw):
            raise ValueError('NBT_TRUNCATED')
        start = cursor
        cursor += size
        return raw[start:cursor]

    def size32():
        value = struct.unpack('>i', take(4))[0]
        if not 0 <= value <= 1_000_000:
            raise ValueError('NBT_COLLECTION_LIMIT')
        return value

    def string():
        return take(struct.unpack('>H', take(2))[0])

    def payload(kind, path, depth):
        if depth > 64:
            raise ValueError('NBT_DEPTH_LIMIT')
        if kind in (1, 2, 3, 4, 5, 6):
            take({1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}[kind])
        elif kind in (7, 11, 12):
            take(size32() * {7: 1, 11: 4, 12: 8}[kind])
        elif kind == 8:
            start = cursor
            value = string()
            if path == (b'Data', b'GameRules', b'keepInventory'):
                found.append((start, cursor, value))
        elif kind == 9:
            child = take(1)[0]
            for index in range(size32()):
                payload(child, (*path, str(index).encode()), depth + 1)
        elif kind == 10:
            names = set()
            while (child := take(1)[0]) != 0:
                name = string()
                if name in names:
                    raise ValueError('NBT_DUPLICATE_TAG')
                names.add(name)
                payload(child, (*path, name), depth + 1)
        else:
            raise ValueError('NBT_TAG_TYPE')

    if take(1) != b'\x0a':
        raise ValueError('NBT_ROOT_COMPOUND_REQUIRED')
    string()  # Minecraft's named root is not a child of Data.
    payload(10, (), 0)
    if cursor != len(raw) or len(found) != 1 or found[0][2] not in (b'false', b'true'):
        raise ValueError('KEEP_INVENTORY_RULE_NOT_UNAMBIGUOUS')
    return found[0]


def enable_keep_inventory(path, backup):
    path, backup = Path(path), Path(backup)
    original = path.read_bytes()
    if len(original) > 16 * 1024 * 1024:
        raise ValueError('LEVEL_DAT_SIZE_LIMIT')
    with gzip.GzipFile(fileobj=io.BytesIO(original)) as source:
        raw = source.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError('LEVEL_DAT_EXPANDED_LIMIT')
    start, stop, before = rule_span(raw)
    result = {'rule': 'keepInventory', 'before': before.decode(), 'after': 'true',
              'changed': before != b'true', 'only_requested_rule_changed': True,
              'before_sha256': hashlib.sha256(original).hexdigest()}
    if before == b'true':
        return {**result, 'after_sha256': result['before_sha256']}
    if backup.exists():
        raise ValueError('RULE_BACKUP_ALREADY_EXISTS')
    backup.parent.mkdir(parents=True, exist_ok=True)
    with backup.open('xb') as saved:
        saved.write(original)
        saved.flush()
        os.fsync(saved.fileno())
    changed = raw[:start] + b'\x00\x04true' + raw[stop:]
    assert rule_span(changed)[2] == b'true'
    encoded = gzip.compress(changed, mtime=0)
    temp = path.with_name('.level.dat.keep-inventory.tmp')
    try:
        with temp.open('xb') as out:
            out.write(encoded)
            out.flush()
            os.fsync(out.fileno())
        if path.read_bytes() != original:
            raise ValueError('WORLD_CHANGED_DURING_RULE_EDIT')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    assert gzip.decompress(path.read_bytes()) == changed
    assert backup.read_bytes() == original
    return {**result, 'after_sha256': hashlib.sha256(encoded).hexdigest(), 'backup_verified': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if os.name != 'nt' or platform.node() != 'DESKTOP-2QQPN1H':
        raise ValueError('REMOTE_3080_NATIVE_WINDOWS_REQUIRED')
    from mc_application import NativeServices
    service = NativeServices(root)
    for name in (*service.PORTS, 'minecraft'):
        state = service.ownership(name, reject=True)
        if state['owned'] or state['port_open']:
            raise ValueError('WORLD_RULE_EDIT_REQUIRES_STOPPED_APPLICATION')
    work = root / 'runtime/minecraft/mc-friends-s1-neoforge-21.1.248/work'
    world = (work / 'saves/MC Live Offline 083/level.dat').resolve()
    if not world.is_relative_to(root) or not world.is_file():
        raise ValueError('ORIGINAL_OFFLINE_WORLD_REQUIRED')
    history = root / '.setup/mc-native-089-rollback'
    value = enable_keep_inventory(world, history / 'level.dat.before-keep-inventory')
    value.update(ok=True, device=platform.node(), world='MC Live Offline 083', live_inventory_edited=False)
    (history / 'keep-inventory089.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(value))


if __name__ == '__main__':
    main()
