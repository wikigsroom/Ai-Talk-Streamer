"""Collect owned UI pixels, or normally close a reviewed idle test client."""
import argparse
import ctypes
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from integration.issac.common import AdmissionError,inside,read_json,write_json
from integration.issac.deployment import require_candidate
from integration.issac.livehime import Livehime


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('action',choices=['inspect','close-idle']);parser.add_argument('--review')
    args=parser.parse_args();root=args.root.resolve();candidate=require_candidate(root)
    client=Livehime(root);owner=client.owner()
    windows=client.native_window('windows')['windows']
    if len(windows)!=1:raise AdmissionError('ONE_CURRENT_OWNED_OFFICIAL_WINDOW_REQUIRED')
    window=windows[0];hwnd=window['hwnd']
    row={**candidate,'pid':owner['pid'],'created_at':owner['created_at'],'render_mode':owner['render_mode'],
        'window':window,'at_unix':time.time(),'scope':'render_diagnostics_only',
        'visible_scene_accepted':False,'official_recording_created':False,'public_broadcast_started':False}
    user=ctypes.windll.user32
    user.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
    user.SetForegroundWindow.argtypes=[ctypes.c_void_p];user.ShowWindow.argtypes=[ctypes.c_void_p,ctypes.c_int]
    if args.action=='close-idle':
        review=read_json(inside(root,args.review))
        if (review.get('candidate_id')!=candidate['candidate_id'] or review.get('pid')!=owner['pid']
            or review.get('created_at')!=owner['created_at'] or time.time()-review['at_unix']>1800):
            raise AdmissionError('FRESH_SAME_OWNED_RENDER_REVIEW_REQUIRED')
        # This helper is only for a newly launched diagnostic client. It never
        # closes a client that has a scene/record-start receipt or active UI.
        scene=inside(root,'state/issac-acceptance/official-scene.json')
        if scene.is_file() and read_json(scene).get('candidate_id')==candidate['candidate_id']:
            raise AdmissionError('OFFICIAL_SCENE_CLIENT_PRESERVED')
        events=inside(root,'state/issac-stream/official-client-events.jsonl')
        if events.is_file():
            import json
            for line in events.read_text('utf8').splitlines():
                value=json.loads(line)
                if value.get('pid')==owner['pid'] and value.get('action') in ('record-start','record-stop'):
                    raise AdmissionError('RECORDING_CLIENT_PRESERVED')
        ui=client.ui()
        if ui.get('recording_indicator') is True or ui.get('stop_controls',0):
            raise AdmissionError('POSSIBLY_RECORDING_CLIENT_PRESERVED')
        client.owner();user.PostMessageW(hwnd,0x0010,0,0)
        import psutil
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:
                process=psutil.Process(owner['pid'])
                if process.create_time()!=owner['created_at']:break
            except psutil.NoSuchProcess:break
            time.sleep(.5)
        else:raise AdmissionError('OWNED_CLIENT_DID_NOT_EXIT_NORMALLY_NO_FORCE_CLOSE')
        row['closed_normally']=True;row['foreign_clients_preserved']=True
    else:
        # Ordinary minimize/restore and repaint of this task's verified idle
        # client; this changes neither graphics drivers nor capture protection.
        user.ShowWindow(hwnd,6);time.sleep(.2)
        user.ShowWindow(hwnd,9)
        user.SetForegroundWindow(hwnd)
        user.RedrawWindow.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint]
        user.RedrawWindow(hwnd,None,None,0x585)
        row['ordinary_owned_window_redraw_requested']=True
        time.sleep(1)
        try:row['ui']=client.ui()
        except Exception as error:row['ui_error']=type(error).__name__+': '+str(error)
        try:row['screenshot']=client.screenshot('programme_review')
        except Exception as error:row['screenshot_error']=type(error).__name__+': '+str(error)
    target=inside(root,'state/issac-acceptance/official-render-diagnostics')/(uuid.uuid4().hex+'.json')
    write_json(target,row)
    import json
    print(json.dumps({'diagnostic':target.relative_to(root).as_posix(),**row},ensure_ascii=False))
    if args.action=='inspect' and ('ui_error' in row or 'screenshot_error' in row):raise SystemExit(1)


if __name__=='__main__':main()
