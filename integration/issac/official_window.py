"""Read/capture only a proven owned official window, using native game Python."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import uuid
from .common import AdmissionError,file_hash,inside,read_json,write_json

LABELS={'scene_sources','audio_settings','video_settings','recording_started','recording_stopped','programme_review'}


def identity(root,row):
    import psutil
    process=psutil.Process(row['pid'])
    executable=Path(row['executable']).resolve()
    if (not executable.is_relative_to(inside(root,'tools/bilibili-livehime'))
            or executable.name.lower()!='livehime.exe' or Path(process.exe()).resolve()!=executable
            or process.create_time()!=row['created_at'] or file_hash(executable)!=row['executable_sha256']):
        raise AdmissionError('OWNED_OFFICIAL_WINDOW_PROCESS_REQUIRED')
    return process


def inspect(root,row):
    import psutil,win32gui,win32process
    process=identity(root,row)
    owned={process.pid:process}
    for child in process.children(recursive=True):
        try:
            if Path(child.exe()).resolve().is_relative_to(inside(root,'tools/bilibili-livehime')):owned[child.pid]=child
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    windows=[]
    def collect(hwnd,_):
        pid=win32process.GetWindowThreadProcessId(hwnd)[1]
        if pid not in owned or not win32gui.IsWindowVisible(hwnd):return
        box=win32gui.GetWindowRect(hwnd)
        if box[2]-box[0]>=640 and box[3]-box[1]>=360:
            windows.append({'hwnd':hwnd,'pid':pid,'created_at':owned[pid].create_time(),'title':win32gui.GetWindowText(hwnd),
                            'rect':list(box),'foreground':win32gui.GetForegroundWindow()==hwnd})
    win32gui.EnumWindows(collect,None)
    return {'root_pid':process.pid,'windows':windows,'observed_unix':time.time()}


def profile(root,row):
    import psutil
    process=identity(root,row);base=inside(root,'state/issac-stream/livehime')
    files=[];foreign=[]
    for proc in [process,*process.children(recursive=True)]:
        try:
            for item in proc.open_files():
                path=Path(item.path).resolve()
                if path.is_relative_to(base):files.append(str(path))
                elif 'livehime' in path.as_posix().lower() and not path.is_relative_to(Path(root).resolve()):foreign.append(str(path))
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    # Environment redirection alone does not prove what KnownFolder APIs used.
    profile_roots=[base/name for name in ('roaming','local','profile')]
    settings={'.ini','.json','.sqlite','.sqlite3','.db','.xml','.conf','.config'}
    produced=[p for folder in profile_roots for p in folder.rglob('*') if p.is_file()
              and p.suffix.lower() in settings and p.stat().st_mtime>=row['launched_unix']-1]
    opened_settings=[p for p in files if Path(p).suffix.lower() in settings and any(Path(p).is_relative_to(f) for f in profile_roots)]
    return {'verified':bool(opened_settings or produced) and not foreign,'profile_runtime_files':len(produced),
            'observed_profile_files':files[:40],'foreign_profile_files':foreign[:40],
            'environment_only_is_not_isolation':True,'observed_unix':time.time()}


def capture(root,row,label):
    import win32gui,win32process,win32ui,win32con
    from PIL import Image,ImageStat,ImageGrab
    if label not in LABELS:raise AdmissionError('FIXED_OFFICIAL_REVIEW_SCREEN_REQUIRED')
    windows=inspect(root,row)['windows']
    if len(windows)!=1:raise AdmissionError('ONE_VISIBLE_OWNED_OFFICIAL_WINDOW_REQUIRED')
    window=windows[0];hwnd=window['hwnd'];left,top,right,bottom=window['rect'];w,h=right-left,bottom-top
    source=win32gui.GetWindowDC(hwnd);dc=win32ui.CreateDCFromHandle(source);memory=dc.CreateCompatibleDC();bitmap=win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(dc,w,h);memory.SelectObject(bitmap)
        memory.BitBlt((0,0),(w,h),dc,(0,0),win32con.SRCCOPY)
        image=Image.frombuffer('RGB',(w,h),bitmap.GetBitmapBits(True),'raw','BGRX',0,1)
        if max(ImageStat.Stat(image.resize((64,36))).stddev)<2:
            if win32gui.GetForegroundWindow()!=hwnd:raise AdmissionError('OFFICIAL_WINDOW_PIXELS_UNAVAILABLE_BRING_OWN_WINDOW_TO_FRONT')
            image=ImageGrab.grab(bbox=(left,top,right,bottom),all_screens=True)
            if win32gui.GetForegroundWindow()!=hwnd or max(ImageStat.Stat(image.resize((64,36))).stddev)<2:
                raise AdmissionError('OFFICIAL_WINDOW_CAPTURE_EMPTY_OR_FOREGROUND_CHANGED')
        path=inside(root,'state/issac-acceptance/official-ui')/(label+'-'+uuid.uuid4().hex+'.png')
        path.parent.mkdir(parents=True,exist_ok=True);image.save(path)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle());memory.DeleteDC();dc.DeleteDC();win32gui.ReleaseDC(hwnd,source)
    record={'label':label,'path':path.relative_to(root).as_posix(),'sha256':file_hash(path),
            'pid':row['pid'],'created_at':row['created_at'],'window_pid':window['pid'],'window_hwnd':hwnd,
            'candidate_id':row['candidate_id'],'captured_unix':time.time(),'method':'real_owned_official_window_pixels'}
    write_json(path.with_suffix('.json'),record);return record


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('action',choices=['windows','profile','screenshot']);parser.add_argument('--pending',action='store_true');parser.add_argument('--label')
    args=parser.parse_args();root=args.root.resolve()
    row=read_json(inside(root,'.setup/issac-livehime-launch.json' if args.pending else '.setup/issac-livehime-owner.json'))
    candidate=read_json(inside(root,'.setup/candidate.json'))
    if row['candidate_id']!=candidate['id']:raise AdmissionError('CURRENT_OFFICIAL_WINDOW_CANDIDATE_REQUIRED')
    result=inspect(root,row) if args.action=='windows' else profile(root,row) if args.action=='profile' else capture(root,row,args.label)
    print(json.dumps(result,ensure_ascii=False))
