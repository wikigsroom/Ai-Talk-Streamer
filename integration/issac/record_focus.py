"""Keep the proven owned game foreground between local-record UI operations.

Isaac's protected PauseOnFocusLost option is deliberately left unchanged.
Changing focus does not resume or rearm a normal operator/fault pause.
"""
from contextlib import contextmanager
import ctypes
import json
from pathlib import Path
import time
import urllib.request

from .common import AdmissionError,file_hash,inside,read_json
from .saves import GAME_SHA256


def game_owner(root):
    import psutil
    row=read_json(inside(root,'state/isaac-strategy/native-session.json'))
    process=psutil.Process(row['game_pid']);executable=inside(root,'game/isaac-ng.exe')
    if (process.create_time()!=row['game_created_at'] or Path(process.exe()).resolve()!=executable
            or row.get('game_sha256')!=GAME_SHA256 or file_hash(executable)!=GAME_SHA256):
        raise AdmissionError('CURRENT_OWNED_GAME_FOCUS_IDENTITY_REQUIRED')
    return process


def foreground(hwnd,pid,*,created_at=None,timeout=2):
    u=ctypes.windll.user32
    u.GetForegroundWindow.restype=ctypes.c_void_p
    u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    u.SetForegroundWindow.argtypes=[ctypes.c_void_p]
    def verify():
        actual=ctypes.c_ulong();u.GetWindowThreadProcessId(hwnd,ctypes.byref(actual))
        if actual.value!=pid:raise AdmissionError('OWNED_FOCUS_WINDOW_CHANGED')
        if created_at is not None:
            import psutil
            try:valid=psutil.Process(pid).create_time()==created_at
            except psutil.NoSuchProcess:valid=False
            if not valid:raise AdmissionError('OWNED_FOCUS_PROCESS_CHANGED')
    verify();started=time.monotonic();deadline=started+timeout
    if u.GetForegroundWindow()!=hwnd and not u.SetForegroundWindow(hwnd):
        # A detached recovery worker may not own the foreground input queue.
        # Temporarily share ordinary queues for activation, then always detach;
        # do not synthesize Alt/game keys or change global foreground settings.
        k=ctypes.windll.kernel32
        u.AttachThreadInput.argtypes=[ctypes.c_ulong,ctypes.c_ulong,ctypes.c_bool]
        u.IsIconic.argtypes=[ctypes.c_void_p]
        u.ShowWindowAsync.argtypes=[ctypes.c_void_p,ctypes.c_int]
        u.BringWindowToTop.argtypes=[ctypes.c_void_p]
        current=k.GetCurrentThreadId();other=u.GetForegroundWindow();ignored=ctypes.c_ulong()
        foreground_thread=u.GetWindowThreadProcessId(other,ctypes.byref(ignored)) if other else 0
        target_thread=u.GetWindowThreadProcessId(hwnd,ctypes.byref(ignored))
        attached=[]
        try:
            verify()
            for thread in dict.fromkeys([foreground_thread,target_thread]):
                if thread and thread!=current and u.AttachThreadInput(current,thread,True):
                    attached.append(thread)
            verify()
            if u.IsIconic(hwnd):u.ShowWindowAsync(hwnd,9)  # ordinary SW_RESTORE
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
        finally:
            for thread in reversed(attached):u.AttachThreadInput(current,thread,False)
    # Win32 accepts activation before the target's input queue applies it.
    # Observe completion with a bound, checking ownership on every sample.
    while True:
        verify()
        if u.GetForegroundWindow()==hwnd:break
        if time.monotonic()>=deadline:raise AdmissionError('OWNED_WINDOW_FOREGROUND_NOT_CONFIRMED')
        time.sleep(.02)
    verify()
    return {'pid':pid,'hwnd':hwnd,'foreground':True,'game_control_changed':False,
            'confirmation_seconds':time.monotonic()-started}


def game_foreground(root):
    process=game_owner(root);u=ctypes.windll.user32;windows=[]
    u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    u.IsWindowVisible.argtypes=[ctypes.c_void_p]
    @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_ssize_t)
    def each(hwnd,_):
        pid=ctypes.c_ulong();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==process.pid and u.IsWindowVisible(hwnd):windows.append(hwnd)
        return True
    u.EnumWindows(each,0)
    if len(windows)!=1:raise AdmissionError('UNIQUE_OWNED_GAME_FOCUS_WINDOW_REQUIRED')
    game_owner(root) # Recheck PID lifetime immediately before changing focus.
    return foreground(windows[0],process.pid,created_at=process.create_time())


@contextmanager
def record_controls(client):
    game=game_owner(client.root);owner=client.owner()
    windows=client.native_window('windows')['windows']
    if len(windows)!=1:raise AdmissionError('ONE_VISIBLE_OWNED_OFFICIAL_WINDOW_REQUIRED')
    window=windows[0]
    if window['pid']!=owner['pid']:
        raise AdmissionError('OFFICIAL_FOCUS_OWNER_CHANGED')
    try:
        foreground(window['hwnd'],window['pid'],created_at=owner['created_at'])
        yield
    finally:
        current=game_owner(client.root)
        if current.pid!=game.pid or current.create_time()!=game.create_time():
            raise AdmissionError('GAME_FOCUS_OWNER_CHANGED_DURING_RECORD_CONTROL')
        game_foreground(client.root)


class RecordingHandoff:
    """An explicit record-start command owns only its own normal pause.

    An existing operator/fault/drink pause is rejected. No exception handler
    resumes the game. The caller must explicitly request resume after the
    record UI has returned focus and all ownership checks still pass.
    """
    def __init__(self,root):
        self.root=Path(root);self.pause_receipt=None
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self,port,path,body=None):
        token=inside(self.root,'private/issac/bridge-token.txt').read_text('ascii').strip()
        req=urllib.request.Request('http://127.0.0.1:'+str(port)+path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','X-Isaac-Token':token})
        with self.http.open(req,timeout=10) as response:return json.load(response)

    def state(self):
        value=self.request(9532,'/query?topic=state');age=value.get('age_ms')
        if (value.get('connected') is not True or type(age) not in (int,float) or not 0<=age<1500
                or not value.get('identity') or type(value.get('data',{}).get('frame')) is not int):
            raise AdmissionError('FRESH_RECORDING_GAME_STATE_REQUIRED')
        return value

    def pause(self):
        if self.pause_receipt is not None:raise AdmissionError('RECORDING_HANDOFF_ALREADY_USED')
        owner=game_owner(self.root);status=self.request(9534,'/status');state=self.state()
        room=state['data'].get('room') or {};revision=status.get('control_revision')
        if (status.get('armed') is not True or status.get('save_slot')!=3 or type(revision) is not int
                or status.get('pause_confirmation_pending') or room.get('paused') is not False
                or room.get('dead') is not False):
            raise AdmissionError('ACTIVE_AUTOMATIC_RUN_REQUIRED_FOR_RECORDING_HANDOFF')
        pause=self.request(9534,'/control',{'action':'pause','expected_revision':revision})
        receipt=pause.get('native_receipt') or {}
        if (pause.get('armed') is not False or pause.get('control_revision')!=revision+1
                or receipt.get('normal_game_pause_acknowledged') is not True
                or receipt.get('pause_hold') is not True or not receipt.get('pause_input_ack',{}).get('id')):
            raise AdmissionError('RECORDING_OWNED_NORMAL_PAUSE_REQUIRED')
        paused=self.state()
        if paused['identity']!=state['identity']:
            raise AdmissionError('RECORDING_GAME_CHANGED_BEFORE_PAUSE')
        self.pause_receipt={'pid':owner.pid,'created_at':owner.create_time(),'identity':paused['identity'],
            'control_revision':pause['control_revision'],'pause':receipt,'created_unix':time.time(),
            'created_monotonic':time.monotonic()}
        self.resume_requested=False
        return self.pause_receipt

    def resume(self):
        proof=self.pause_receipt
        if proof is None or self.resume_requested:raise AdmissionError('UNUSED_RECORDING_OWNED_PAUSE_REQUIRED')
        self.resume_requested=True
        owner=game_owner(self.root)
        if (owner.pid!=proof['pid'] or owner.create_time()!=proof['created_at']
                or not 0<=time.monotonic()-proof['created_monotonic']<=20):
            raise AdmissionError('RECORDING_HANDOFF_OWNER_OR_DEADLINE_CHANGED')
        game_foreground(self.root)
        status=self.request(9534,'/status');state=self.state();room=state['data'].get('room') or {}
        pause=proof['pause'];ack=room.get('pause_ack') or {}
        if (status.get('armed') is not False or status.get('pause_confirmation_pending')
                or status.get('control_revision')!=proof['control_revision']
                or state['identity']!=proof['identity'] or state['data']['frame']!=pause['stable_frame']
                or room.get('paused') is not True or room.get('dead') is not False
                or ack.get('id')!=pause['pause_input_ack']['id']):
            raise AdmissionError('RECORDING_OWNED_PAUSE_NO_LONGER_CURRENT')
        resumed=self.request(9534,'/control',{'action':'resume','expected_revision':proof['control_revision']})
        if resumed.get('armed') is not True:raise AdmissionError('RECORDING_EXPLICIT_RESUME_NOT_CONFIRMED')
        self.resume_confirmed=True
        deadline=time.monotonic()+3
        while True:
            actual=self.state();current=self.request(9534,'/status');room=actual['data'].get('room') or {}
            if current.get('armed') is False and not current.get('last_fault'):
                live=self.wait_live_interval()
                return {'explicit_resume':resumed,'state':live['state'],'handoff':proof,
                        'game_advanced':True,'live_interval':live}
            if (current.get('armed') is not True or current.get('control_revision')!=proof['control_revision']+1
                    or room.get('dead') is not False):
                raise AdmissionError('RECORDING_RESUMED_RUN_NOT_ACTIVE')
            if room.get('paused') is False and actual['data']['frame']>pause['stable_frame']+5:
                return {'explicit_resume':resumed,'state':actual,'handoff':proof,'game_advanced':True}
            if time.monotonic()>=deadline:raise AdmissionError('RECORDING_GAME_ADVANCE_NOT_CONFIRMED')
            time.sleep(.05)

    def wait_live_interval(self,timeout=65):
        """Observe playable progress, allowing only a proven drink interlude.

        This observer sends no control input and never adopts or resumes an
        operator/fault pause. The existing drink coordinator owns its resume.
        """
        from .readiness import verified_drink_pause
        proof=self.pause_receipt
        if not proof or not getattr(self,'resume_confirmed',False):
            raise AdmissionError('RECORDING_EXPLICIT_RESUME_REQUIRED')
        deadline=time.monotonic()+min(65,max(0,timeout));live_since=None;first_frame=None;unknown_since=None
        drinks={};expected_revision=proof['control_revision']+1
        while True:
            owner=game_owner(self.root)
            if owner.pid!=proof['pid'] or owner.create_time()!=proof['created_at']:
                raise AdmissionError('RECORDING_LIVE_GAME_OWNER_CHANGED')
            state=self.state();game=self.request(9534,'/status');room=state['data'].get('room') or {}
            if (any(state['identity'].get(key)!=proof['identity'].get(key)
                    for key in ('controller','seed','restart','bridge')) or room.get('dead') is not False
                    or game.get('last_fault')):
                raise AdmissionError('RECORDING_LIVE_RUN_CHANGED_OR_FAULTED')
            now=time.monotonic()
            if game.get('armed') is True and not game.get('pause_confirmation_pending') and room.get('paused') is False:
                if game.get('control_revision')!=expected_revision:
                    raise AdmissionError('RECORDING_LIVE_CONTROL_REVISION_CHANGED')
                unknown_since=None
                if live_since is None:live_since=now;first_frame=state['data']['frame']
                if now-live_since>=.5 and state['data']['frame']>first_frame+5:
                    return {'state':state,'verified_drinks':list(drinks.values()),'observed_live_progress':True}
            else:
                live_since=None;first_frame=None
                studio=self.request(8062,'/health')
                if verified_drink_pause({'state':state,'game':game,'studio':studio}):
                    action=studio['natural_action'];key=str(action['control_revision'])
                    if key not in drinks:
                        if action['control_revision']!=expected_revision+1:
                            raise AdmissionError('RECORDING_DRINK_CONTROL_REVISION_CHANGED')
                        expected_revision=action['control_revision']+1
                    drinks[key]={'control_revision':action['control_revision'],'identity':action['identity'],
                        'created_unix':action['created_unix'],'expires_unix':action['expires_unix']}
                    unknown_since=None
                else:
                    # Publication follows the actual ordinary pause. Allow a
                    # short observation gap, without touching any controls.
                    if unknown_since is None:unknown_since=now
                    if now-unknown_since>=1.5:
                        raise AdmissionError('RECORDING_UNVERIFIED_PAUSE')
            if now>=deadline:raise AdmissionError('RECORDING_LIVE_INTERVAL_NOT_OBSERVED')
            time.sleep(.1)
