"""Independent native Windows recovery owner, enabled by an explicit live request.

The supervisor survives the stack it repairs. It never issues a public stop or
changes models, credentials, protected saves or gameplay values. A hard failure
restarts the owned stack/game/official encoder and restores the same programme.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request

from .common import AdmissionError, Audit, FileLease, file_hash, inside, read_json, write_json


class SupervisorState:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.bad_since = None
        self.platform_off = 0
        self.restarts = 0

    def assess(self, healthy, live, *, manual_pause=False, restart_requested=False):
        if manual_pause:
            self.bad_since = None
            return 'respect_operator_pause'
        if live is True:
            self.platform_off = 0
        elif live is False:
            self.platform_off += 1
        if healthy:
            self.bad_since = None
        elif self.bad_since is None:
            self.bad_since = self.clock()
        if (restart_requested or self.platform_off >= 2
                or self.bad_since is not None and self.clock()-self.bad_since >= 20):
            return 'restart_owned_stack'
        return 'observe'


class LiveSupervisor:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.audit = Audit(inside(root, 'state/issac-stream/live-supervisor-events.jsonl'))
        self.path = inside(root, 'state/issac-stream/live-supervisor.json')
        self.authorization = inside(root, '.setup/issac-live-supervisor.json')
        self.token = inside(root, 'private/issac/bridge-token.txt').read_text('ascii').strip()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.state = SupervisorState()

    def report(self, phase, **values):
        write_json(self.path, {'at_unix': time.time(), 'phase': phase, **values,
                              'public_stop_allowed': False, 'automatic_recovery': True})

    def api(self, port, path, body=None, *, timeout=3):
        request = urllib.request.Request('http://127.0.0.1:'+str(port)+path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'X-Isaac-Token': self.token})
        with self.opener.open(request, timeout=timeout) as response:
            return json.load(response)

    def platform_live(self):
        request = urllib.request.Request('https://api.live.bilibili.com/room/v1/Room/get_info?room_id=595139',
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://live.bilibili.com/595139'})
        with self.opener.open(request, timeout=5) as response:
            value = json.load(response)
        if value.get('code') != 0 or value.get('data', {}).get('room_id') != 595139:
            raise AdmissionError('ACTUAL_PUBLIC_ROOM_STATUS_REQUIRED')
        return value['data']['live_status'] == 1

    def arm(self):
        from .deployment import require_candidate
        from .official_window import identity
        candidate = require_candidate(self.root, hardware=False)
        owner = read_json(inside(self.root, '.setup/issac-livehime-owner.json'))
        identity(self.root, owner)
        receipt = {'user_requested_live_broadcast': True, 'room_id': 595139,
                   'candidate_id': candidate['candidate_id'], 'armed_at_unix': time.time(),
                   'restart_owned_programmes': True, 'public_stop_allowed': False,
                   'protected_saves_must_remain_unchanged': True}
        write_json(self.authorization, receipt)
        self.audit.append('live_supervisor_armed', candidate_id=candidate['candidate_id'], room_id=595139)
        return receipt

    def authorized(self):
        receipt = read_json(self.authorization)
        candidate = read_json(inside(self.root, '.setup/candidate.json'))
        if (receipt.get('user_requested_live_broadcast') is not True or receipt.get('room_id') != 595139
                or receipt.get('candidate_id') != candidate['id'] or not receipt.get('restart_owned_programmes')):
            raise AdmissionError('CURRENT_EXPLICIT_LIVE_RECOVERY_REQUIRED')
        return receipt

    def healthy(self):
        app = self.api(9541, '/status')
        if app.get('error') or not str(app.get('stage', '')).startswith('running'):
            return False, False, True
        if any(not child.get('alive') for name, child in app.get('children', {}).items() if name != 'isaac-game'):
            return False, False, True
        controller = self.api(9534, '/status')
        cycle = controller.get('live_cycle') or {}
        manual = cycle.get('phase') == 'operator_paused'
        requested = cycle.get('phase') == 'restart_required'
        if manual or requested:
            return False, manual, requested
        if not cycle.get('enabled'):
            return False, False, False
        if cycle.get('phase') == 'playing' and not controller.get('armed'):
            return False, False, False
        if cycle.get('phase') != 'playing' and cycle.get('phase_seconds', 0) > 90:
            return False, False, True
        core = self.api(3104, '/api/dsh/issac/core/status')
        studio = self.api(8062, '/health')
        player = self.api(3104, '/api/dsh/platforms').get('output_player') or {}
        good = core.get('ready') is True and studio.get('ready') is True and player.get('connected') is True and player.get('audio_state') == 'running'
        return good, False, False

    def owned_process(self, row):
        import psutil
        try:
            process = psutil.Process(row['pid'])
        except psutil.NoSuchProcess:
            return None
        path = Path(row['executable']).resolve()
        if (process.create_time() != row['created_at'] or Path(process.exe()).resolve() != path
                or not path.is_relative_to(self.root) or file_hash(path) != row['executable_sha256']):
            raise AdmissionError('RECOVERY_OWNED_PROCESS_IDENTITY_CHANGED')
        return process

    def stop_owned_stack_for_restart(self):
        import psutil
        app = read_json(inside(self.root, 'state/issac-stream/application.json'))
        try:
            self.api(9541, '/action', {'action': 'stop'}, timeout=5)
        except Exception:
            pass
        deadline = time.monotonic()+65
        workers = [row for row in app.get('processes', []) if row['name'] != 'isaac-game']
        while time.monotonic() < deadline:
            if not any(self.owned_process(row) for row in workers):
                break
            time.sleep(.5)
        # A wedged child cannot prevent the independent repair forever. Each
        # process lifetime and executable is rechecked; never kill by name.
        for row in workers:
            process = self.owned_process(row)
            if process:
                process.terminate()
                try:
                    process.wait(8)
                except psutil.TimeoutExpired:
                    process.kill()
                    process.wait(5)
            launcher_id = row.get('launcher_pid')
            if launcher_id and launcher_id != row['pid']:
                try:
                    launcher = psutil.Process(launcher_id)
                    if (launcher.create_time() == row['launcher_created_at']
                            and Path(launcher.exe()).resolve() == Path(row['launcher_executable']).resolve()
                            and Path(launcher.exe()).resolve().is_relative_to(self.root/'runtime')):
                        launcher.terminate()
                        launcher.wait(5)
                except psutil.NoSuchProcess:
                    pass
        try:
            parent = psutil.Process(app['pid'])
            if (parent.create_time() == app['created_at'] and Path(parent.exe()).resolve().is_relative_to(self.root/'runtime')
                    and 'integration.issac.application' in parent.cmdline()):
                parent.terminate()
                parent.wait(8)
        except psutil.NoSuchProcess:
            pass

    def restart_owned_game(self):
        import psutil
        import win32gui
        import win32process
        from .saves import GAME_SHA256, SaveProtection
        SaveProtection(self.root).verify()
        row = read_json(inside(self.root, 'state/isaac-strategy/native-session.json'))
        try:
            process = psutil.Process(row['game_pid'])
        except psutil.NoSuchProcess:
            return
        executable = inside(self.root, 'game/isaac-ng.exe')
        if (process.create_time() != row['game_created_at'] or Path(process.exe()).resolve() != executable
                or file_hash(executable) != GAME_SHA256):
            raise AdmissionError('RECOVERY_PINNED_GAME_IDENTITY_CHANGED')
        windows = []
        def visit(hwnd, _):
            if win32process.GetWindowThreadProcessId(hwnd)[1] == process.pid:
                windows.append(hwnd)
        win32gui.EnumWindows(visit, None)
        for hwnd in windows:
            win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # ordinary window close; keep native autosave
        try:
            process.wait(12)
        except psutil.TimeoutExpired:
            # A genuinely frozen game cannot process its ordinary close. Slot3
            # resumes its last game-written room autosave; no saves are edited.
            if process.create_time() != row['game_created_at']:
                raise AdmissionError('RECOVERY_GAME_LIFETIME_CHANGED')
            process.terminate()
            process.wait(8)
        SaveProtection(self.root).verify()

    def start_stack(self):
        from .preparation import runtime_environment
        executable = inside(self.root, 'runtime/isaac-native/Scripts/python.exe')
        log = inside(self.root, 'state/issac-stream/live-supervisor-stack.log')
        with log.open('ab') as output:
            process = subprocess.Popen([str(executable), '-X', 'utf8', '-B', '-m', 'integration.issac.application',
                '--root', str(self.root)], cwd=self.root, env=runtime_environment(self.root, 'game'),
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, creationflags=0x08000200)
        deadline = time.monotonic()+900
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AdmissionError('RECOVERY_STACK_START_FAILED')
            try:
                app = self.api(9541, '/status')
                if app.get('error'):
                    raise AdmissionError('RECOVERY_COMPONENT_START_FAILED')
                if app.get('stage') == 'running_candidate_not_accepted':
                    return
            except (OSError, ValueError):
                pass
            time.sleep(2)
        raise AdmissionError('RECOVERY_STACK_READY_DEADLINE')

    def restore_game(self):
        self.api(9541, '/action', {'action': 'launch_game'})
        time.sleep(5)
        app = self.api(9541, '/status')
        # Application /status exposes identity records under children.
        game = next(row for row in read_json(inside(self.root, 'state/issac-stream/application.json'))['processes'] if row['name'] == 'isaac-game')
        self.api(9534, '/control', {'action': 'attach', 'pid': game['pid']})
        def observe():
            return self.api(9534, '/control', {'action': 'observe'})
        def key(name):
            self.api(9534, '/control', {'action': 'menu', 'key': name})
            time.sleep(.4)
        before = observe()
        if before['progress']['slot'] != 0 or before['observation']['players'] != 0:
            raise AdmissionError('FRESH_GAME_TITLE_REQUIRED_FOR_SLOT3_SELECTION')
        # The pinned executable always boots at its title with file1 selected.
        # Fixed ordinary title/file3 sequence; admit no gameplay until native
        # progress confirms writable slot3 and all original saves still match.
        key('enter')
        key('right')
        key('right')
        key('enter')
        selected = observe()
        if selected['progress']['slot'] != 3 or selected['progress']['readonly'] is not False:
            raise AdmissionError('RECOVERY_NATIVE_SLOT3_NOT_CONFIRMED')
        deadline = time.monotonic()+20
        for _ in range(4):
            if observe()['observation']['players'] == 1:
                break
            key('enter')
        while time.monotonic() < deadline:
            current = observe()
            if current['observation']['players'] == 1 and not current['observation']['dead']:
                self.api(9534, '/control', {'action': 'install'}, timeout=20)
                self.api(9534, '/control', {'action': 'pause'}, timeout=12)
                return
            time.sleep(.5)
        raise AdmissionError('RECOVERY_LIVING_NATIVE_RUN_NOT_CONFIRMED')

    def restore_official(self):
        import psutil
        from .livehime import Livehime
        from .official_window import identity
        old = read_json(inside(self.root, '.setup/issac-livehime-owner.json'))
        try:
            process = identity(self.root, old)
        except psutil.NoSuchProcess:
            process = None
        if process:
            children = process.children(recursive=True)
            process.terminate()
            process.wait(12)
            for child in children:
                try:
                    if Path(child.exe()).resolve().is_relative_to(Path(old['executable']).parent):
                        child.terminate()
                except psutil.NoSuchProcess:
                    pass
        # No stop-broadcast request is ever sent. The same isolated profile,
        # sources, title, account and browser/audio source are reloaded.
        client = Livehime(self.root)
        owner = client.launch()
        window = client.native_window('windows')['windows']
        if len(window) != 1:
            raise AdmissionError('RECOVERY_OFFICIAL_WINDOW_REQUIRED')
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            script = inside(self.root, 'scripts/issac_broadcast_resume.ps1')
            result = subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
                '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                '-ProcessId', str(window[0]['pid']), '-WindowHandle', str(window[0]['hwnd'])],
                capture_output=True, timeout=12, creationflags=0x08000000)
            if result.returncode:
                self.audit.append('official_resume_waiting_for_named_control')
            else:
                observed = json.loads(result.stdout.decode('utf-8-sig'))
                if observed.get('already_running') is True and self.platform_live():
                    return
            time.sleep(3)
        raise AdmissionError('RECOVERY_PUBLIC_STREAM_NOT_CONFIRMED')

    def recover(self):
        from .saves import SaveProtection
        from .record_focus import game_foreground
        self.authorized()
        SaveProtection(self.root).verify()
        self.state.restarts += 1
        self.audit.append('owned_full_stack_restart_started', attempt=self.state.restarts)
        self.report('restarting_stack', attempt=self.state.restarts)
        self.stop_owned_stack_for_restart()
        self.restart_owned_game()
        self.start_stack()
        self.report('restoring_slot3')
        self.restore_game()
        self.api(3104, '/api/dsh/issac/rehearsal/start', {}, timeout=35)
        self.api(3104, '/api/dsh/platforms/bilibili/collector/start', {}, timeout=12)
        self.report('restoring_public_stream')
        self.restore_official()
        game_foreground(self.root)
        self.api(9534, '/control', {'action': 'live'}, timeout=20)
        SaveProtection(self.root).verify()
        self.audit.append('owned_full_stack_restart_completed', attempt=self.state.restarts,
                          memory_cleared=False, model_changed=False, public_stop_requested=False)
        self.state.bad_since = None
        self.state.platform_off = 0
        self.report('monitoring', restart_completed=True, attempt=self.state.restarts)

    def run(self):
        self.authorized()
        with FileLease(inside(self.root, 'state/issac-stream/live-supervisor.lock')):
            backoff = 5
            while True:
                self.authorized()
                try:
                    healthy, manual, requested = self.healthy()
                except Exception:
                    healthy, manual, requested = False, False, False
                try:
                    live = self.platform_live()
                except Exception:
                    live = None
                action = self.state.assess(healthy, live, manual_pause=manual, restart_requested=requested)
                self.report('monitoring', healthy=healthy, public_live=live, action=action,
                            restarts=self.state.restarts)
                if action == 'restart_owned_stack':
                    try:
                        self.recover()
                        backoff = 5
                    except Exception as error:
                        self.audit.append('owned_restart_retry', exception_type=type(error).__name__,
                            code=str(error) if isinstance(error, AdmissionError) else 'RECOVERY_STEP_FAILED',
                            next_retry_seconds=backoff)
                        self.report('retrying_recovery', next_retry_seconds=backoff,
                                    error_code=str(error) if isinstance(error, AdmissionError) else 'RECOVERY_STEP_FAILED')
                        time.sleep(backoff)
                        backoff = min(120, backoff*2)
                        continue
                time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('action', choices=['arm', 'watch', 'recover'])
    args = parser.parse_args()
    supervisor = LiveSupervisor(args.root)
    if args.action == 'arm':
        supervisor.arm()
        print(json.dumps({'armed': True, 'public_stop_allowed': False}))
    elif args.action == 'recover':
        supervisor.recover()
    else:
        supervisor.run()


if __name__ == '__main__':
    main()
