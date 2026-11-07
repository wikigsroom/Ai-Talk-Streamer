"""Operator actions with actual native pause acknowledgment before any shutdown."""
from pathlib import Path
import argparse
import json
import time
import uuid
import urllib.request
import psutil
import win32gui
import win32process
from native_request import request
from verify_dsh import api

ROOT=Path(__file__).resolve().parent

def game_identity():
    install=json.loads((ROOT/'game-install.json').read_text(encoding='utf8'))
    record=json.loads((ROOT/'native-bridge-process.json').read_text(encoding='utf8'))
    process=psutil.Process(record['game_pid'])
    if Path(process.exe())!=Path(install['game_root'])/install['executable'] or process.create_time()!=record['game_created_at']:
        raise RuntimeError('Game process identity changed')
    windows=[]
    win32gui.EnumWindows(lambda hwnd,_:windows.append(hwnd) if win32process.GetWindowThreadProcessId(hwnd)[1]==process.pid and 'Binding of Isaac' in win32gui.GetWindowText(hwnd) else None,None)
    if len(windows)!=1:raise RuntimeError('Expected the selected game window')
    return process,windows[0]

def key(name):
    process,hwnd=game_identity()
    return request(op='key',name=name,hwnd=hex(hwnd),timeout=4)

def native_state():
    result=request('local j=_G.json or require("json");local g=Game();local p=Isaac.GetPlayer(0);return j.encode({paused=g:IsPaused(),frame=g:GetFrameCount(),players=g:GetNumPlayers(),dead=p and p:IsDead(),hp=p and p:GetHearts()+p:GetSoulHearts(),stage=g:GetLevel():GetStage(),room=g:GetLevel():GetCurrentRoomIndex()})',timeout=5)
    return json.loads(result)

def pause():
    game_identity()
    before=native_state()
    if not before['paused']:
        identity=uuid.uuid4().hex
        request('local m=_G.__NativeIsaacController;if m and m.strategyControl then m.strategyControl:requestPause("'+identity+'");return "requested" end;return "no_callback"',timeout=4)
        deadline=time.monotonic()+1.5
        while time.monotonic()<deadline:
            time.sleep(.1);observed=native_state()
            if observed['paused']:break
        else:
            key('escape')
            time.sleep(.35);observed=native_state()
        if not observed['paused']:raise RuntimeError('Native normal pause was not acknowledged; controller remains active')
    else: observed=before
    time.sleep(.25);confirmed=native_state()
    if not confirmed['paused'] or confirmed['frame']!=observed['frame']:
        raise RuntimeError('Pause not stable; controller remains active')
    # Only an observed, stable pause permits stopping the controller.
    try:api(9533,'/cancel',{},timeout=3)
    except (OSError,RuntimeError):pass
    try:api(9532,'/control',{'enabled':False})
    except (OSError,RuntimeError):pass
    try:
        payload=json.dumps({'enabled':False}).encode()
        urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:9529/api/autopilot?compact=1',data=payload,headers={'Content-Type':'application/json'}),timeout=4).close()
    except OSError:pass
    result={'normal_game_pause_acknowledged':True,'stable_frame':confirmed['frame'],'native':confirmed,'foreground_changed':False}
    (ROOT/'logs/build/pause-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result

def arm(local_only=False):
    process,_=game_identity()
    progress=request(op='progress',timeout=4)
    if progress.get('slot')!=3 or progress.get('readonly') is not False:raise RuntimeError('Only writable slot 3 is authorized')
    import subprocess
    subprocess.run([str(Path(__import__('sys').executable)),str(ROOT/'check-saves.py')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    state=native_state()
    if state.get('dead') or state.get('hp',0)<=0:raise RuntimeError('No living run to arm')
    protection=json.loads((ROOT/'save-protection.json').read_text(encoding='utf8'))
    protection.update(verified_game_pid=process.pid,verified_game_created_at=process.create_time(),allowed_slot=3,autopilot_allowed=True)
    (ROOT/'save-protection.json').write_text(json.dumps(protection,ensure_ascii=False,indent=2),encoding='utf8')
    try:
        api(9532,'/control',{'enabled':not local_only,'live':not local_only})
        api(9533,'/control',{'automatic':not local_only})
        payload=json.dumps({'enabled':True}).encode()
        with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:9529/api/autopilot?compact=1',data=payload,headers={'Content-Type':'application/json'}),timeout=4) as r:
            local=json.load(r)
        if state['paused']:
            key('escape')
            deadline=time.monotonic()+2.5
            while time.monotonic()<deadline:
                time.sleep(.1)
                if not native_state()['paused']:break
            else:
                raise RuntimeError('Unpause was not acknowledged')
    except Exception:
        # A partial enable (including a LAN host error) must not leave either
        # input owner active when the operator sees a failed arm command.
        pause()
        raise
    return {'armed':True,'mode':'local_only' if local_only else 'local_with_dsh','slot':3,'readonly':False,'autopilot':local.get('autopilot_enabled'),
            'local_frame':local.get('latest_frame'),'progress':progress}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['pause','arm','status','key']);parser.add_argument('--key',choices=['enter','escape','left','right','up','down']);args=parser.parse_args()
    if args.action=='pause':value=pause()
    elif args.action=='arm':value=arm()
    elif args.action=='key':value=key(args.key)
    else:value={'native':native_state(),'progress':request(op='progress')}
    print(json.dumps(value,ensure_ascii=False))
