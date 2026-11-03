"""Owned native Minecraft service. It cannot enable AUTO or start a broadcast."""
from pathlib import Path
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import platform
import sys
import time

from native_operation import atomic_json, read_json, safe_path, registered_worker
from native_windows_process import NativeJob, identity_alive
from native_windows_display import NativeDisplayLease
import mc_neoforge as mc

ROOT = Path(__file__).resolve().parents[1]
CONFIG = 'configs/mc-player.private.json'
STOP = '.setup/mc-game-stop.json'
PROCESS = '.setup/mc-game-process.json'


def configuration(root):
    value = read_json(safe_path(root, root / CONFIG))
    if value.get('schema_version') == 1:
        mc.require(set(value) == {'schema_version', 'server'} and isinstance(value['server'], str),
                   'MC_GAME_SERVICE_CONFIG')
        return {**value, 'mode': 'multiplayer', 'world': None}
    mc.require(value.get('schema_version') == 2 and value.get('mode') in ('singleplayer', 'multiplayer'),
               'MC_GAME_SERVICE_CONFIG')
    if value['mode'] == 'singleplayer':
        mc.require(set(value) == {'schema_version', 'mode', 'world'}
                   and (value['world'] is None or isinstance(value['world'], str)), 'MC_GAME_SERVICE_CONFIG')
        return {**value, 'server': None}
    mc.require(set(value) == {'schema_version', 'mode', 'server'} and isinstance(value['server'], str),
               'MC_GAME_SERVICE_CONFIG')
    # launch_plan validates the exact world/address before creating a child.
    value = {**value, 'world': None}
    return value


def close_window(identity):
    mc.require(identity_alive(identity), 'MC_GAME_SERVICE_PROCESS_CHANGED')
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
    user.EnumWindows.restype = wt.BOOL
    user.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user.PostMessageW.restype = wt.BOOL
    sent = []
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(window, unused):
        pid = wt.DWORD(); user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == identity['pid'] and identity_alive(identity):
            if user.PostMessageW(window, 0x0010, 0, 0):
                sent.append(int(window))
        return True
    mc.require(user.EnumWindows(visit, 0), 'MC_GAME_SERVICE_WINDOW_ENUMERATION')
    return len(sent)


def run(root=ROOT):
    root = Path(root).resolve()
    mc.require(os.name == 'nt' and platform.node().casefold() == 'desktop-2qqpn1h',
               'MC_GAME_TEST_REQUIRES_REMOTE_3080_NOT_LOCAL_MACHINE')
    config = configuration(root)
    source = Path(mc.read(root / mc.RECEIPT)['source'])
    java, args, work = mc.launch_plan(root, source, config['server'], integration_probe=False,
                                    mode=config['mode'], world=config['world'])
    bridge = read_json(work / 'config/ai-talk-streamer-bridge.json')
    mc.require(bridge == {'enabled': True, 'endpoint': 'ws://127.0.0.1:3092/api/dsh/game/bridge'},
               'MC_GAME_SERVICE_CANONICAL_DSH_REQUIRED')
    import psutil
    mc.require(psutil.virtual_memory().available >= 8 * 1024**3, 'MC_NEOFORGE_FREE_RAM_BELOW_8_GIB')
    end = time.monotonic() + 5
    record = {}
    while time.monotonic() < end:
        record = read_json(safe_path(root, root / '.setup/mc-game-owner.json'))
        if registered_worker(record, __file__): break
        time.sleep(.05)
    mc.require(registered_worker(record, __file__), 'MC_GAME_SERVICE_OWNER_MISSING')
    existing = read_json(root / PROCESS)
    mc.require(not existing or not identity_alive(existing['process']), 'MC_GAME_SERVICE_ALREADY_RUNNING')
    for process in psutil.process_iter(['name', 'cmdline']):
        if (process.info['name'] or '').casefold() in ('java.exe', 'javaw.exe'):
            mc.require(not any(str(work.parent).casefold() in a.casefold()
                       for a in process.info.get('cmdline') or []), 'MC_NEOFORGE_PLAYER_ALREADY_RUNNING')
    logs = safe_path(root, work / 'logs'); logs.mkdir(exist_ok=True)
    (work.parent / 'tmp').mkdir(exist_ok=True)
    argfile = safe_path(root, work.parent / 'application-launch.args')
    argfile.write_text('\n'.join(map(mc.java_quote, args)), encoding='mbcs')
    result = {'classification': 'NATIVE_APPLICATION_PLAYER_LIFECYCLE_NOT_AUTOMATIC_AUTHORITY',
              'automatic_input_authorized': False, 'public_broadcast_started': False,
              'world_mode': config['mode'], 'local_world': config['world'],
              'owner': {k: record[k] for k in ('pid', 'creation_ticks')},
              'argv_sha256': hashlib.sha256(argfile.read_bytes()).hexdigest(), 'graceful_close_requested': False}
    job = NativeJob(); child = None; display = NativeDisplayLease()
    try:
        display.acquire()
        result['display_keep_awake'] = display.proof()
        from native_log_archive import prepare_console_log
        result['console_log'] = prepare_console_log(root, logs / 'application-console.log')
        with (logs / 'application-console.log').open('ab') as stream:
            child = job.spawn([str(java), '@' + str(argfile)], cwd=work, stdout=stream, stderr=stream)
            result['process'] = child.identity(); atomic_json(root, root / PROCESS, result)
            while child.poll() is None:
                if display.refresh():
                    result['display_keep_awake'] = display.proof()
                    atomic_json(root, root / PROCESS, result)
                stop = read_json(safe_path(root, root / STOP))
                if stop.get('owner') == result['owner']:
                    result['close_window_count'] = close_window(child.identity())
                    result['graceful_close_requested'] = True
                    end = time.monotonic() + 30
                    while child.poll() is None and time.monotonic() < end:
                        time.sleep(.1)
                    if child.poll() is None:
                        result['bounded_job_cleanup_required'] = True; job.rollback()
                    break
                time.sleep(.2)
            result['exit_code'] = child.wait(timeout=15)
    finally:
        try:
            if job.active(): job.rollback()
            result['all_owned_processes_closed'] = job.active() == 0
            job.close()
            if child: child.close()
        finally:
            try:
                display.release()
            finally:
                result['display_keep_awake'] = display.proof()
                atomic_json(root, root / '.setup/mc-game-exit.json', result)
    return result


if __name__ == '__main__':
    run()
