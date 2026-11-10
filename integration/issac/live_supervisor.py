"""Independent native Windows recovery owner, enabled by an explicit live request.

The supervisor survives the stack it repairs. It never issues a public stop or
changes models, credentials, protected saves or gameplay values. A hard failure
restarts the owned stack/game/official encoder and restores the same programme.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import traceback
import urllib.request
import urllib.error

from .common import AdmissionError, Audit, FileLease, file_hash, inside, read_json, write_json
from .continuity import uninterrupted


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


def operator_paused(controller):
    return (controller.get('manual_override') is True
            or (controller.get('live_cycle') or {}).get('phase') == 'operator_paused')


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
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # Keep the local admission reason instead of masking every 409 as
            # an opaque HTTPError. Never echo arbitrary upstream/private text.
            try:code=json.loads(error.read(8192)).get('error')
            except (ValueError,AttributeError):code=None
            if not isinstance(code,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,159}',code):
                code='LOCAL_HTTP_'+str(error.code)
            raise AdmissionError('RECOVERY_API_'+code) from None

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
                   'protected_saves_must_remain_unchanged': True,
                   'game_pause_allowed':not uninterrupted(self.root),
                   'restart_living_game_allowed':not uninterrupted(self.root)}
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
        manual = operator_paused(controller)
        requested = cycle.get('phase') == 'restart_required'
        if uninterrupted(self.root):requested=requested or bool((cycle.get('alert') or {}).get('component_repair_requested'))
        if manual or requested:
            return False, manual, requested
        studio = None
        if cycle.get('phase') == 'natural_paused':
            from .readiness import verified_drink_pause
            studio = self.api(8062, '/health')
            view = self.api(9532, '/query?topic=state')
            if not verified_drink_pause({'state': view, 'game': controller, 'studio': studio}):
                return False, False, False
        elif not cycle.get('enabled'):
            return False, False, False
        if cycle.get('phase') == 'playing' and not controller.get('armed'):
            return False, False, False
        if cycle.get('phase') != 'playing' and cycle.get('phase_seconds', 0) > 90:
            return False, False, True
        core = self.api(3104, '/api/dsh/issac/core/status')
        studio = studio or self.api(8062, '/health')
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
        if uninterrupted(self.root):raise AdmissionError('FULL_STACK_STOP_DURING_LIVE_FORBIDDEN')
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
        if uninterrupted(self.root):raise AdmissionError('RESTART_OF_RUNNING_GAME_FORBIDDEN')
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

    def game_menu(self):
        from .menu_observation import recognize_menu
        request = urllib.request.Request('http://127.0.0.1:9534/frame.jpg')
        with self.opener.open(request, timeout=8) as response:
            image = response.read(4*1024*1024+1)
        return recognize_menu(image, read_json(inside(self.root, 'configs/issac/menu-signatures.json')))

    def restore_game(self):
        from .record_focus import game_foreground
        from .saves import SaveProtection
        self.api(9541, '/action', {'action': 'launch_game'})
        time.sleep(5)
        # Application /status exposes identity records under children.
        game = next(row for row in read_json(inside(self.root, 'state/issac-stream/application.json'))['processes'] if row['name'] == 'isaac-game')
        self.api(9534, '/control', {'action': 'attach', 'pid': game['pid']})
        def observe():
            return self.api(9534, '/control', {'action': 'observe'})
        def key(name):
            self.api(9534, '/control', {'action': 'menu', 'key': name})
            time.sleep(.75)
        before = observe()
        if before['progress']['slot'] != 0 or before['observation']['players'] != 0:
            raise AdmissionError('FRESH_GAME_TITLE_REQUIRED_FOR_SLOT3_SELECTION')
        focus = game_foreground(self.root, timeout=20)
        self.audit.append('recovery_game_foreground_confirmed',step='native_menu',focus=focus)
        deadline, title_keys, file_keys, intro_keys = time.monotonic()+120, 0, 0, 0
        # A fresh game first plays a film. Waiting for the actual title avoids
        # the old fixed sequence consuming Enter on the film and arrows on the
        # title. Only the separately recognized observed film gets one ordinary
        # skip key. Neither an unknown frame nor a fade authorizes any key.
        self.report('restoring_slot3', step='waiting_for_known_native_menu')
        while time.monotonic() < deadline:
            current = observe()
            if current['progress']['slot'] != 0 or current['observation']['players'] != 0:
                raise AdmissionError('RECOVERY_UNEXPECTED_NATIVE_FILE_SELECTION')
            menu = self.game_menu()
            if menu['page'] == 'file_select':
                if menu['selected_file'] == 3:
                    self.audit.append('recovery_file3_visually_confirmed', **menu)
                    break
                if file_keys >= 4:
                    raise AdmissionError('RECOVERY_FILE3_HIGHLIGHT_NOT_CONFIRMED')
                key('right')
                file_keys += 1
            elif menu['page'] == 'title':
                if title_keys >= 3:
                    raise AdmissionError('RECOVERY_TITLE_INPUT_NOT_ACCEPTED')
                key('space')
                title_keys += 1
            elif menu['page'] == 'opening_film':
                if intro_keys == 0:
                    self.audit.append('recovery_observed_opening_skip', **menu)
                    key('space')
                    intro_keys += 1
                else:
                    time.sleep(.5)
            else:
                time.sleep(.5)
        else:
            raise AdmissionError('RECOVERY_NATIVE_MENU_NOT_RECOGNIZED')
        SaveProtection(self.root).verify()
        key('enter')
        deadline = time.monotonic()+5
        while True:
            selected = observe()
            slot = selected['progress']['slot']
            if slot == 3 and selected['progress']['readonly'] is False:
                break
            if slot not in (0, 3) or time.monotonic() >= deadline:
                raise AdmissionError('RECOVERY_NATIVE_SLOT3_NOT_CONFIRMED')
            time.sleep(.25)
        self.audit.append('recovery_native_slot3_confirmed', slot=3, readonly=False)
        deadline = time.monotonic()+20
        for _ in range(4):
            selected = observe()
            if selected['progress']['slot'] != 3 or selected['progress']['readonly'] is not False:
                raise AdmissionError('RECOVERY_NATIVE_SLOT3_CHANGED')
            if selected['observation']['players'] == 1:
                break
            key('enter')
        while time.monotonic() < deadline:
            current = observe()
            if current['observation']['players'] == 1 and not current['observation']['dead']:
                self.api(9534, '/control', {'action': 'install'}, timeout=20)
                if not uninterrupted(self.root):
                    self.api(9534, '/control', {'action': 'recovery_pause'}, timeout=12)
                return
            time.sleep(.5)
        raise AdmissionError('RECOVERY_LIVING_NATIVE_RUN_NOT_CONFIRMED')

    def official_child(self, row, directory):
        import psutil
        try:
            process = psutil.Process(row['pid'])
            if process.create_time() != row['created_at']:
                return None  # The owned lifetime ended; preserve the new owner.
            path = Path(row['executable']).resolve()
            if (Path(process.exe()).resolve() != path or not path.is_relative_to(directory)
                    or file_hash(path) != row['executable_sha256']):
                raise AdmissionError('RECOVERY_OFFICIAL_CHILD_IDENTITY_CHANGED')
            return process
        except psutil.NoSuchProcess:
            return None

    def remember_official_children(self, old=None):
        import psutil
        from .official_window import identity
        old = old or read_json(inside(self.root, '.setup/issac-livehime-owner.json'))
        directory = Path(old['executable']).resolve().parent
        ledger_path = inside(self.root, 'state/issac-stream/live-supervisor-official-children.json')
        ledger = read_json(ledger_path) if ledger_path.exists() else {}
        rows = ledger.get('children', []) if all(ledger.get(k) == old.get(k) for k in
            ('pid', 'created_at', 'executable_sha256')) else []
        try:
            process = identity(self.root, old)
            children = process.children(recursive=True)
        except psutil.NoSuchProcess:
            return rows
        current = []
        for child in children:
            try:
                path = Path(child.exe()).resolve()
                if path.is_relative_to(directory):
                    row = next((r for r in rows if r['pid'] == child.pid and
                        r['created_at'] == child.create_time() and Path(r['executable']).resolve() == path), None)
                    current.append(row or {'pid': child.pid, 'created_at': child.create_time(),
                        'executable': str(path), 'executable_sha256': file_hash(path)})
            except psutil.NoSuchProcess:
                pass
        try:identity(self.root, old)
        except psutil.NoSuchProcess:
            current = rows + [row for row in current if row not in rows]
            write_json(ledger_path, {k: old[k] for k in ('pid', 'created_at', 'executable_sha256')} | {'children': current})
            return current
        write_json(ledger_path, {k: old[k] for k in ('pid', 'created_at', 'executable_sha256')} | {'children': current})
        return current

    def restart_official_client(self):
        import psutil
        from .livehime import Livehime
        from .official_window import identity
        old = read_json(inside(self.root, '.setup/issac-livehime-owner.json'))
        directory = Path(old['executable']).resolve().parent
        rows = self.remember_official_children(old)
        try:
            process = identity(self.root, old)
            process.terminate()
            try:process.wait(12)
            except psutil.TimeoutExpired:
                process = identity(self.root, old)
                process.kill();process.wait(8)
        except psutil.NoSuchProcess:
            pass
        # Await recorded same-lifetime children before the singleton check. A
        # parent-bound ledger also survives a parent exit during recovery.
        for row in rows:
            child = self.official_child(row, directory)
            if child:
                try:
                    child.terminate()
                    try:child.wait(8)
                    except psutil.TimeoutExpired:
                        child = self.official_child(row, directory)
                        if child:child.kill();child.wait(8)
                except psutil.NoSuchProcess:
                    pass
        result = Livehime(self.root).launch()
        self.remember_official_children()
        return result

    def preflight_live_game(self):
        # Catch delayed native exits before publishing a black game source.
        # This is a verified normal pause; no gameplay input is issued.
        for _ in range(5):
            if operator_paused(self.api(9534, '/status')):
                raise AdmissionError('RECOVERY_CANCELLED_BY_OPERATOR')
            current = self.api(9534, '/control', {'action': 'observe'}, timeout=8)
            if (current['progress']['slot'] != 3 or current['progress']['readonly'] is not False
                    or current['observation']['players'] != 1 or current['observation']['dead']):
                raise AdmissionError('RECOVERY_LIVING_SLOT3_REQUIRED_BEFORE_PUBLIC_LIVE')
            time.sleep(1)

    def restore_official(self):
        from .livehime import Livehime
        # No stop-broadcast request is ever sent. The same isolated profile,
        # sources, title, account and browser/audio source are reloaded.
        client = Livehime(self.root)
        client.owner()
        window = client.native_window('windows')['windows']
        if len(window) != 1:
            raise AdmissionError('RECOVERY_OFFICIAL_WINDOW_REQUIRED')
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            script = inside(self.root, 'scripts/issac_broadcast_resume.ps1')
            command=[r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
                '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                '-ProcessId', str(window[0]['pid']), '-WindowHandle', str(window[0]['hwnd'])]
            if uninterrupted(self.root):command.append('-PreserveGameForeground')
            result = subprocess.run(command,
                capture_output=True, timeout=12, creationflags=0x08000000)
            if result.returncode:
                self.audit.append('official_resume_waiting_for_named_control', returncode=result.returncode,
                                  private_diagnostic=result.stderr.decode('utf8', errors='replace')[-1500:])
            else:
                observed = json.loads(result.stdout.decode('utf-8-sig'))
                if observed.get('already_running') is True and self.platform_live():
                    return
            time.sleep(3)
        raise AdmissionError('RECOVERY_PUBLIC_STREAM_NOT_CONFIRMED')

    def recover(self):
        if uninterrupted(self.root):return self.repair_live_components()
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
        # Finish unloading the old capture client before the new game and its
        # native bridge exist; CYCLE19 exited during the opposite sequence.
        self.report('restoring_official_client')
        self.restart_official_client()
        self.report('restoring_slot3')
        self.restore_game()
        self.api(3104, '/api/dsh/issac/rehearsal/start', {}, timeout=35)
        self.api(3104, '/api/dsh/platforms/bilibili/collector/start', {}, timeout=12)
        self.preflight_live_game()
        self.report('restoring_public_stream')
        self.restore_official()
        if operator_paused(self.api(9534, '/status')):
            raise AdmissionError('RECOVERY_CANCELLED_BY_OPERATOR')
        focus = game_foreground(self.root)
        self.audit.append('recovery_game_foreground_confirmed',step='live_resume',focus=focus)
        self.api(9534, '/control', {'action': 'recovery_live'}, timeout=20)
        SaveProtection(self.root).verify()
        self.audit.append('owned_full_stack_restart_completed', attempt=self.state.restarts,
                          memory_cleared=False, model_changed=False, public_stop_requested=False)
        self.state.bad_since = None
        self.state.platform_off = 0
        self.report('monitoring', restart_completed=True, attempt=self.state.restarts)

    def repair_live_components(self):
        """Repair programme owners independently; never stop or pause the game."""
        import psutil
        from .preparation import runtime_environment
        self.authorized();self.state.restarts+=1
        self.report('repairing_components',attempt=self.state.restarts,game_pause_requested=False,game_stop_requested=False)
        try:app=self.api(9541,'/status')
        except Exception:
            with inside(self.root,'state/issac-stream/live-supervisor-stack.log').open('ab') as output:
                subprocess.Popen([str(inside(self.root,'runtime/isaac-native/Scripts/python.exe')),'-X','utf8','-B',
                    '-m','integration.issac.application','--root',str(self.root),'--adopt-running'],cwd=self.root,
                    env=runtime_environment(self.root,'game'),stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,
                    creationflags=0x08000200)
            deadline=time.monotonic()+30
            while True:
                try:app=self.api(9541,'/status');break
                except Exception:
                    if time.monotonic()>=deadline:raise AdmissionError('ADOPTIVE_APPLICATION_START_FAILED')
                    time.sleep(.5)
        checks=[('gpu-geometry',9540,'/health'),('game-controller',9534,'/status'),('voice',9893,'/health'),
                ('flashhead',8040,'/health'),('studio',8062,'/health'),('narrator',3104,'/api/dsh/issac/core/status')]
        geometry=read_json(inside(self.root,'configs/issac/gpu-geometry.json'))
        checks[0]=('gpu-geometry',geometry['health_port'],'/health')
        controller_replaced=False
        try:prior_controller=self.api(9534,'/status')
        except Exception:prior_controller={}
        fault=((prior_controller.get('live_cycle') or {}).get('alert') or {}).get('code') or prior_controller.get('last_fault')
        forced={'CORE_TURN_STALLED':'narrator','GAME_BRIDGE_STALE':'game-controller',
            'GAME_SIMULATION_STALLED':'game-controller','LOCAL_CONTROLLER_REPAIR_REQUIRED':'game-controller'}
        for name,port,path in checks:
            row=(app.get('children') or {}).get(name) or {}
            try:health=self.component_health(name,port,path)
            except Exception:health={}
            ready=health.get('service')=='issac-native-game' or health.get('ready') is True
            if row.get('alive') and ready and name!=forced.get(fault):continue
            self.api(9541,'/action',{'action':'restart_component','component':name},timeout=25)
            controller_replaced=controller_replaced or name=='game-controller'
            deadline=time.monotonic()+900
            while True:
                try:
                    health=self.component_health(name,port,path)
                    if health.get('service')=='issac-native-game' or health.get('ready') is True:break
                    if health.get('stage')=='failed':raise AdmissionError('COMPONENT_REPAIR_INITIALIZATION_FAILED')
                except (OSError,ValueError):pass
                if time.monotonic()>=deadline:raise AdmissionError('COMPONENT_REPAIR_READY_DEADLINE')
                time.sleep(1)
        controller=self.api(9534,'/status')
        if operator_paused(controller):
            self.report('monitoring',action='respect_operator_pause',game_pause_requested=False)
            return
        registry=read_json(inside(self.root,'state/issac-stream/application.json'))
        game=next((row for row in registry['processes'] if row['name']=='isaac-game' and self.owned_process(row)),None)
        if game is None:
            if not controller_replaced:
                self.api(9541,'/action',{'action':'restart_component','component':'game-controller'},timeout=25)
                deadline=time.monotonic()+30
                while True:
                    try:
                        if self.api(9534,'/status').get('service')=='issac-native-game':break
                    except Exception:pass
                    if time.monotonic()>=deadline:raise AdmissionError('REPLACEMENT_CONTROLLER_READY_DEADLINE')
                    time.sleep(.5)
            self.restore_game()
            registry=read_json(inside(self.root,'state/issac-stream/application.json'))
            game=next(row for row in registry['processes'] if row['name']=='isaac-game')
            controller_replaced=True
        if controller_replaced or not controller.get('native_attached') or not controller.get('armed'):
            self.api(9534,'/control',{'action':'adopt_live','pid':game['pid']},timeout=25)
        self.api(3104,'/api/dsh/issac/rehearsal/start',{},timeout=35)
        self.ensure_bilibili_collector()
        try:
            from .official_window import identity
            identity(self.root,read_json(inside(self.root,'.setup/issac-livehime-owner.json')))
        except psutil.NoSuchProcess:self.restart_official_client()
        if not self.platform_live():self.restore_official()
        self.api(9534,'/control',{'action':'components_ready'},timeout=8)
        self.state.bad_since=None;self.state.platform_off=0
        self.audit.append('live_components_repaired',attempt=self.state.restarts,game_pid=game['pid'],
            game_created_at=game['created_at'],game_pause_requested=False,game_stop_requested=False)
        self.report('monitoring',healthy=True,public_live=True,restarts=self.state.restarts,
            game_pause_requested=False,game_stop_requested=False)

    def component_health(self,name,port,path):
        health=self.api(port,path)
        if name=='narrator' and health.get('ready') is not True:
            host=self.api(3104,'/health')
            if host.get('dsh_ready') is True:
                proof=self.api(3104,'/api/dsh/probe',{},timeout=45)
                from .core_model import model_identity_matches
                if proof.get('passed') is not True or not model_identity_matches(self.root,proof):
                    raise AdmissionError('APPROVED_CHANNEL_PERSONA_PROBE_REQUIRED')
                health=self.api(port,path)
        return health

    def ensure_bilibili_collector(self):
        try:return self.api(3104,'/api/dsh/platforms/bilibili/collector/start',{},timeout=12)
        except AdmissionError as error:
            if str(error)!='RECOVERY_API_COLLECTOR_ALREADY_RUNNING':raise
            value=self.api(3104,'/api/dsh/platforms')
            current=(value.get('collectors') or {}).get('bilibili') or {}
            if current.get('state')!='CONNECTED' or current.get('error'):raise
            return {'already_connected':True,'state':'CONNECTED'}

    def run(self):
        self.authorized()
        with FileLease(inside(self.root, 'state/issac-stream/live-supervisor.lock')):
            backoff = 5
            while True:
                self.authorized()
                try:
                    self.remember_official_children()
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
                        traceback.print_exc()
                        self.audit.append('owned_restart_retry', exception_type=type(error).__name__,
                            code=str(error) if isinstance(error, AdmissionError) else 'RECOVERY_STEP_FAILED',
                            focus_diagnostic=getattr(error,'focus_diagnostic',None),
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
