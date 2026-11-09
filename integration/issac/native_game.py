"""One pinned game process, read-only observations and ordinary bounded input.

Only fixed trusted Lua snippets and the reviewed native controller generator
reach Frida. No request/model argument can supply Lua, console commands, a DLL
path, arbitrary keyboard input or gameplay values.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from pathlib import Path
import struct
import threading
import time
import uuid

from .common import AdmissionError, Audit, file_hash, inside, read_json, write_json
from .game_policy import RunGoal
from .saves import GAME_SHA256, SaveProtection


OBSERVE = '''if Game==nil then error("GAME_API_NOT_READY") end
local g=Game();local n=g and g:GetNumPlayers() or 0;local p=n>0 and Isaac.GetPlayer(0)
local stage,room,seed=0,0,0
if p then stage=g:GetLevel():GetStage();room=g:GetLevel():GetCurrentRoomIndex();seed=g:GetSeeds():GetStartSeed() end
return string.format('{"paused":%s,"frame":%d,"players":%d,"dead":%s,"hp":%d,"stage":%d,"room":%d,"seed":%d,"controller_installed":%s}',
tostring(g and g:IsPaused() or false),g and g:GetFrameCount() or 0,n,tostring(p and p:IsDead() or false),p and p:GetHearts()+p:GetSoulHearts() or 0,
stage,room,seed,tostring(_G.__NativeIsaacController~=nil))'''

PAUSE_STATUS = '''local g=Game();local m=_G.__NativeIsaacController
local c=m and m.strategyControl
return json.encode({paused=g:IsPaused(),frame=g:GetFrameCount(),
    pause_hold=c and c.pauseHold==true or false,pause_ack=c and c.pauseAck or nil})'''


def ordinary_pause_proved(status):
    ack=status.get('pause_ack') or {}
    return (status.get('paused') is True and status.get('pause_hold') is True
            and ack.get('ordinary_pause_input_issued') is True and ack.get('paused') is True
            and isinstance(ack.get('id'),str) and bool(ack['id'])
            and type(status.get('frame')) is int and ack.get('frame')==status['frame'])


class NativeGame:
    def __init__(self, root, protection=None):
        self.root = Path(root).resolve()
        self.protection = protection or SaveProtection(root)
        self.lock = threading.RLock()
        self.session = None
        self.script = None
        self.process = None
        self.created_at = None
        self.session_id = uuid.uuid4().hex
        self.audit = Audit(inside(root,'state/isaac-strategy/native-events.jsonl'))
        self.installed_goal = None
        self.capture_lock=threading.Lock()
        self.frame_requests={}

    def attach(self, pid):
        import psutil
        import frida
        with self.lock:
            if self.session:
                self.verify_process()
                if pid != self.process.pid:
                    raise AdmissionError('ANOTHER_GAME_ALREADY_ATTACHED')
                return self.status()
            process = psutil.Process(pid)
            executable = inside(self.root,'game/isaac-ng.exe')
            if Path(process.exe()).resolve()!=executable or file_hash(executable)!=GAME_SHA256:
                raise AdmissionError('PINNED_GAME_EXECUTABLE_REQUIRED')
            with executable.open('rb') as stream:
                if stream.read(2)!=b'MZ':
                    raise AdmissionError('GAME_PE_HEADER_INVALID')
                stream.seek(0x3c)
                stream.seek(struct.unpack('<I',stream.read(4))[0])
                if stream.read(4)!=b'PE\0\0' or struct.unpack('<H',stream.read(2))[0]!=0x014c:
                    raise AdmissionError('GAME_X86_REQUIRED')
            self.process=process
            self.created_at=process.create_time()
            session=frida.attach(pid)
            script=session.create_script(inside(self.root,'integration/isaac-agent/native_bridge.js').read_text(encoding='utf-8'))
            script.on('message', self.on_message)
            try:
                script.load()
            except Exception:
                session.detach()
                self.process=None
                raise AdmissionError('NATIVE_BRIDGE_ATTACH_FAILED') from None
            self.session,self.script=session,script
            record={'session_id':self.session_id,'game_pid':pid,'game_created_at':self.created_at,
                    'game_sha256':GAME_SHA256,'bridge_sha256':file_hash(inside(self.root,'integration/isaac-agent/native_bridge.js')),
                    'attached_at':time.time(),'control_armed':False}
            write_json(inside(self.root,'state/isaac-strategy/native-session.json'),record)
            self.audit.append('attached',**record)
            return self.status()

    def on_message(self, message, _data):
        if message.get('type')=='error':
            self.audit.append('bridge_error',code='FRIDA_SCRIPT_ERROR')
        elif message.get('type')=='send':
            payload=message.get('payload')
            if isinstance(payload,dict) and payload.get('event')=='native_frame':
                with self.capture_lock:
                    request=self.frame_requests.get(payload.get('id'))
                    if request is not None:
                        request['metadata']=payload;request['bytes']=_data;request['event'].set()
            if isinstance(payload,dict) and payload.get('event')!='native_frame':
                self.audit.append('native_bridge_event',payload=payload)

    def verify_process(self):
        if (not self.process or self.process.create_time()!=self.created_at
                or Path(self.process.exe()).resolve()!=inside(self.root,'game/isaac-ng.exe')):
            raise AdmissionError('GAME_PROCESS_IDENTITY_CHANGED')

    def rpc(self, method, *args, timeout=4):
        self.verify_process()
        if not self.script:
            raise AdmissionError('NATIVE_BRIDGE_NOT_ATTACHED')
        async def invoke():
            return await asyncio.wait_for(getattr(self.script.exports_async,method)(*args), timeout)
        try:
            return asyncio.run(invoke())
        except Exception as error:
            self.audit.append('native_rpc_failed',method=method,exception_type=type(error).__name__,
                              private_diagnostic=str(error)[:1200],session_id=self.session_id)
            raise AdmissionError('NATIVE_BRIDGE_REQUEST_FAILED') from None

    def status(self):
        with self.lock:
            value=self.rpc('status')
            return {'attached':True,'pid':self.process.pid,'created_at':self.created_at,
                    'session_id':self.session_id,'lua_ready':bool(value.get('lua')),
                    'game_sha256':GAME_SHA256,'installed_goal':self.installed_goal,
                    'bridge_counters':value.get('counters'),
                    'performance':value.get('performance')}

    def observe(self,timeout=5):
        with self.lock:
            value=json.loads(self.rpc('evaluate',OBSERVE,timeout=timeout))
            if (not isinstance(value,dict) or any(type(value.get(k)) is not bool for k in ('paused','dead','controller_installed'))
                    or any(type(value.get(k)) is not int for k in ('frame','players','hp','stage','room','seed'))
                    or not 0<=value['players']<=4):
                raise AdmissionError('NATIVE_STATE_RESPONSE_INVALID')
            return value

    def bootstrap_modules(self):
        config=read_json(inside(self.root,'configs/issac/native-modules.json'))
        for row in config['files']:
            path=inside(self.root,row['path'])
            if path.stat().st_size!=row['bytes'] or file_hash(path)!=row['sha256']:
                raise AdmissionError('PINNED_GAME_LUA_MODULE_CHANGED')
        # Lua's Windows C-module loader can use the ANSI API. An ASCII relative
        # path avoids corrupting this installation's Chinese directory name;
        # the native process must actually have our pinned game working dir.
        self.verify_process()
        if Path(self.process.cwd()).resolve()!=inside(self.root,'game'):
            raise AdmissionError('PINNED_GAME_WORKING_DIRECTORY_REQUIRED')
        literal='"resources/scripts"'
        source=('local d='+literal+';package.path=d.."/?.lua;"..d.."/?/init.lua";'
                'package.cpath=d.."/?.dll";local j=require("json");local s=require("socket");'
                'assert(type(j.encode)=="function" and type(s.tcp)=="function");'
                '_G.json=j;return "pinned modules ready"')
        if self.rpc('evaluate',source,timeout=6)!='pinned modules ready':
            raise AdmissionError('NATIVE_GAME_MODULE_BOOTSTRAP_NOT_CONFIRMED')
        self.audit.append('pinned_modules_ready',files=config['files'],session_id=self.session_id)

    def capture_jpeg(self):
        from PIL import Image
        request={'event':threading.Event()};identifier=uuid.uuid4().hex
        with self.capture_lock:
            if self.frame_requests:raise AdmissionError('ONE_GAME_FRAME_INSPECTION_AT_A_TIME')
            self.frame_requests[identifier]=request
        try:
            self.rpc('capture',identifier,timeout=4)
            if not request['event'].wait(1):raise AdmissionError('REAL_GAME_FRAME_NOT_RECEIVED')
            row=request['metadata'];w,h=row['width'],row['height']
            if not 64<=w<=4096 or not 64<=h<=4096 or len(request['bytes'])!=w*h*4:
                raise AdmissionError('NATIVE_OPENGL_FRAME_SHAPE_INVALID')
            image=Image.frombytes('RGBA',(w,h),request['bytes']).transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert('RGB')
            stream=io.BytesIO();image.save(stream,format='JPEG',quality=85)
            return stream.getvalue()
        finally:
            with self.capture_lock:self.frame_requests.pop(identifier,None)

    def progress(self):
        with self.lock:
            result=self.rpc('progress')
            if result.get('error') or result.get('ready') is False or type(result.get('slot')) is not int:
                raise AdmissionError('GAME_NATIVE_SAVE_ABI_NOT_CONFIRMED')
            return result

    def menu_key(self, name):
        if name not in {'enter','escape','left','right','up','down'}:
            raise AdmissionError('ORDINARY_MENU_OR_PAUSE_KEY_REQUIRED')
        import win32gui
        import win32process
        with self.lock:
            self.verify_process()
            found=[]
            def visit(hwnd, _):
                if win32process.GetWindowThreadProcessId(hwnd)[1]==self.process.pid and 'Binding of Isaac' in win32gui.GetWindowText(hwnd):
                    found.append(hwnd)
            win32gui.EnumWindows(visit,None)
            if len(found)!=1:
                raise AdmissionError('UNIQUE_GAME_WINDOW_REQUIRED')
            result=self.rpc('key',name,hex(found[0]))
            self.audit.append('ordinary_menu_key',key=name,session_id=self.session_id)
            return result

    def pause(self):
        with self.lock:
            deadline=time.monotonic()+6
            def budget():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise AdmissionError('NORMAL_PAUSE_INPUT_ACK_PENDING')
                return min(.75,remaining)
            import psutil
            try:
                ended=not self.process or not self.process.is_running() or self.process.status()==psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                ended=True
            if ended:
                return {'game_process_ended':True,'no_active_run':True}
            before=self.observe(timeout=budget())
            if before['players']==0 or before['dead']:
                return {'normal_game_pause_acknowledged':False,'no_active_run':True,'input_armed':False}
            if not before['controller_installed']:
                raise AdmissionError('NATIVE_PAUSE_INPUT_CALLBACK_REQUIRED')
            observed=json.loads(self.rpc('evaluate',PAUSE_STATUS,timeout=budget()))
            if not ordinary_pause_proved(observed):
                nonce=uuid.uuid4().hex
                source=('local m=_G.__NativeIsaacController;assert(m and m.strategyControl);'
                        'm.strategyControl:requestPause("'+nonce+'");return "requested"')
                if self.rpc('evaluate',source,timeout=budget())!='requested':
                    raise AdmissionError('NATIVE_PAUSE_REQUEST_NOT_ACKNOWLEDGED')
                while time.monotonic()<deadline:
                    time.sleep(.1)
                    observed=json.loads(self.rpc('evaluate',PAUSE_STATUS,timeout=budget()))
                    if ordinary_pause_proved(observed):break
                else:
                    # The native hold remains latched and retries the ordinary
                    # pause input when an intro/transition stops swallowing it.
                    # Never enqueue a blind Escape that can later unpause it.
                    raise AdmissionError('NORMAL_PAUSE_INPUT_ACK_PENDING')
            time.sleep(.25)
            confirmed=json.loads(self.rpc('evaluate',PAUSE_STATUS,timeout=budget()))
            if (not ordinary_pause_proved(confirmed) or not ordinary_pause_proved(observed)
                    or confirmed['frame']!=observed['frame']
                    or confirmed['pause_ack']['id']!=observed['pause_ack']['id']):
                self.audit.append('pause_failed',session_id=self.session_id)
                raise AdmissionError('STABLE_NATIVE_NORMAL_PAUSE_NOT_CONFIRMED')
            actual=self.observe(timeout=budget())
            if not actual['paused'] or actual['frame']!=confirmed['frame']:
                raise AdmissionError('STABLE_NATIVE_NORMAL_PAUSE_NOT_CONFIRMED')
            receipt={'normal_game_pause_acknowledged':True,'stable_frame':confirmed['frame'],
                     'native':actual,'pause_input_ack':confirmed['pause_ack'],'pause_hold':True,
                     'game_pid':self.process.pid,'game_created_at':self.created_at,
                     'session_id':self.session_id,'foreground_changed':False,'at_unix':time.time()}
            self.audit.append('pause_confirmed',**receipt)
            write_json(inside(self.root,'state/isaac-strategy/pause-receipt.json'),receipt)
            return receipt

    def install_controller(self, goal=None):
        with self.lock:
            observed=self.observe()
            progress=self.progress()
            self.protection.bind_live_slot(self.process,progress,observed)
            self.bootstrap_modules()
            goal=goal or RunGoal()
            identity={'start_seed':observed['seed'],'restart_count':0,'bridge':self.session_id}
            goal.validate(identity)
            if observed['controller_installed']:
                self.pause()
            module_path=inside(self.root,'integration/isaac-agent/build_native_controller.py')
            spec=importlib.util.spec_from_file_location('issac_native_generator',module_path)
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            output=inside(self.root,'state/isaac-strategy/native-controller.lua')
            module.build(run_goal=goal.name,output=output)
            result=self.rpc('evaluate',output.read_text(encoding='utf-8'),timeout=8)
            if result!='native controller installed':
                raise AdmissionError('NATIVE_CONTROLLER_INSTALL_NOT_CONFIRMED')
            self.installed_goal=goal.name
            self.audit.append('normal_input_controller_installed',run_goal=goal.name,
                              controller_sha256=file_hash(output),session_id=self.session_id)
            return {'installed':True,'goal':goal.name,'controller_sha256':file_hash(output),'autopilot':False}

    def resume(self):
        with self.lock:
            progress=self.progress()
            self.protection.admit_current(self.process,progress)
            state=self.observe()
            if state['dead'] or state['hp']<=0:
                raise AdmissionError('NO_LIVING_RUN_TO_RESUME')
            result=self.rpc('evaluate','local m=_G.__NativeIsaacController;return tostring(m and m.NativeResume and m:NativeResume() or false)')
            if str(result).lower()!='true':
                raise AdmissionError('NATIVE_CONTROLLER_RESUME_NOT_CONFIRMED')
            if state['paused']:
                self.menu_key('escape')
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    time.sleep(.1)
                    if not self.observe()['paused']:
                        return {'unpaused':True,'session_id':self.session_id}
                raise AdmissionError('NATIVE_UNPAUSE_NOT_CONFIRMED')
            return {'unpaused':True,'session_id':self.session_id}

    def close(self):
        with self.lock:
            if self.session:
                import psutil
                try:
                    ended=not self.process or not self.process.is_running() or self.process.status()==psutil.STATUS_ZOMBIE
                except psutil.NoSuchProcess:
                    ended=True
                if ended:
                    try:
                        self.session.detach()
                    except Exception:
                        pass
                    self.script=self.session=None
                    self.audit.append('game_process_ended',session_id=self.session_id)
                    return
                # Failure leaves the observation/control owner alive. It must
                # not advertise a clean stop while the game can still run.
                self.pause()
                self.session.detach()
                self.script=self.session=None
