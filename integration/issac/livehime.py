"""Official signed Livehime only: isolated ownership, UI audit and local recording."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from .common import AdmissionError,Audit,FileLease,digest,file_hash,inside,read_json,write_json
from .deployment import require_candidate

SCENE_CHECKS={'official_client','local_recording_only','canvas_1920_1080','output_30fps',
 'real_game_full_canvas_bottom','transparent_programme_top','title_only_visual_change',
 'circle_264_at_1624_732','one_avatar_variant','chat_right_or_locked_left','captions_at_320_840',
 'programme_url_exact','one_official_audible_source','preview_muted','microphone_disabled',
 'only_game_and_programme_audio','no_obs_client','record_path_inside_issac'}


class Livehime:
    def __init__(self,root):
        self.root=Path(root).resolve();self.candidate=require_candidate(root,hardware=False)
        self.audit=Audit(inside(root,'state/issac-stream/official-client-events.jsonl'))
        self.registration=inside(root,'.setup/issac-livehime-owner.json')
        paths=list(inside(root,'tools/bilibili-livehime').rglob('livehime.exe'))
        if len(paths)!=1:raise AdmissionError('ONE_COPIED_OFFICIAL_LIVEHIME_REQUIRED')
        self.executable=paths[0].resolve()

    def powershell(self,command,timeout=30):
        result=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
            '-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=timeout,creationflags=0x08000000)
        if result.returncode:raise AdmissionError('OFFICIAL_CLIENT_NATIVE_OPERATION_FAILED')
        return json.loads(result.stdout.decode('utf-8-sig'))

    def prepare(self):
        escaped=str(self.executable).replace("'","''")
        result=self.powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $p='"+escaped+"'; $s=Get-AuthenticodeSignature -LiteralPath $p; @{status=[string]$s.Status;version=[Diagnostics.FileVersionInfo]::GetVersionInfo($p).FileVersion}|ConvertTo-Json -Compress")
        if result['status']!='Valid':raise AdmissionError('OFFICIAL_LIVEHIME_SIGNATURE_REQUIRED')
        receipt={'prepared':True,'application':self.executable.relative_to(self.root).as_posix(),
            'application_sha256':file_hash(self.executable),'version':result['version'],
            'application_signature':{'status':'Valid'},'independently_verified_for':'issac',
            'account_login_verified':False,'public_broadcast_started':False,'obs_required':False}
        write_json(inside(self.root,'outputs/platforms/setup/bilibili-livehime.json'),receipt)
        return receipt

    def launch(self):
        import psutil
        if self.registration.exists():
            try:return self.owner()
            except (AdmissionError,psutil.NoSuchProcess):pass
        self.prepare();start=time.time()
        env=dict(os.environ)
        for key,relative in {'APPDATA':'state/issac-stream/livehime/roaming',
            'LOCALAPPDATA':'state/issac-stream/livehime/local','TEMP':'cache/issac/livehime/tmp','TMP':'cache/issac/livehime/tmp'}.items():
            path=inside(self.root,relative);path.mkdir(parents=True,exist_ok=True);env[key]=str(path)
        env['__COMPAT_LAYER']='RunAsInvoker'
        process=subprocess.Popen([str(self.executable)],cwd=self.executable.parent,env=env,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            candidates=[]
            for p in psutil.process_iter(['name','exe','create_time']):
                try:
                    if (p.info['name'] or '').lower()=='livehime.exe' and Path(p.info['exe']).resolve()==self.executable and p.create_time()>=start-1:
                        candidates.append(p)
                except (psutil.AccessDenied,psutil.NoSuchProcess,TypeError):continue
            roots=[p for p in candidates if p.ppid() not in {x.pid for x in candidates}]
            if len(roots)==1:
                p=roots[0];record={'pid':p.pid,'created_at':p.create_time(),'executable':str(self.executable),
                    'executable_sha256':file_hash(self.executable),'launched_unix':start,'candidate_id':self.candidate['candidate_id'],
                    'foreign_clients_preserved':True}
                write_json(self.registration,record);self.audit.append('owned_official_client_launched',**record);return record
            time.sleep(.25)
        raise AdmissionError('ISOLATED_OFFICIAL_CLIENT_NOT_OBSERVED_FOREIGN_CLIENTS_PRESERVED')

    def owner(self):
        import psutil
        row=read_json(self.registration);process=psutil.Process(row['pid'])
        if (row['candidate_id']!=self.candidate['candidate_id'] or process.create_time()!=row['created_at']
            or Path(process.exe()).resolve()!=self.executable or file_hash(self.executable)!=row['executable_sha256']):
            raise AdmissionError('OWNED_OFFICIAL_CLIENT_IDENTITY_CHANGED')
        return row

    def ui(self,action='inspect'):
        row=self.owner()
        script=inside(self.root,'scripts/issac_livehime_ui.ps1')
        result=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe','-NoProfile','-NonInteractive',
            '-ExecutionPolicy','Bypass','-File',str(script),'-ProcessId',str(row['pid']),'-Action',action],
            capture_output=True,timeout=25,creationflags=0x08000000)
        if result.returncode:raise AdmissionError('OFFICIAL_RECORD_CONTROL_NOT_CONFIRMED_USE_VISIBLE_UI_REVIEW')
        value=json.loads(result.stdout.decode('utf-8-sig'));self.audit.append('official_ui',action=action,pid=row['pid'])
        return value

    def screenshot(self,label):
        import win32gui,win32process,win32ui,win32con
        from PIL import Image
        if label not in {'scene_sources','audio_settings','video_settings','recording_started','recording_stopped','programme_review'}:
            raise AdmissionError('FIXED_OFFICIAL_REVIEW_SCREEN_REQUIRED')
        row=self.owner();windows=[]
        def collect(hwnd,_):
            if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1]==row['pid']:
                box=win32gui.GetWindowRect(hwnd)
                if box[2]-box[0]>=640 and box[3]-box[1]>=360:windows.append(hwnd)
        win32gui.EnumWindows(collect,None)
        if len(windows)!=1:raise AdmissionError('ONE_VISIBLE_OWNED_OFFICIAL_WINDOW_REQUIRED')
        hwnd=windows[0];left,top,right,bottom=win32gui.GetWindowRect(hwnd);w,h=right-left,bottom-top
        source=win32gui.GetWindowDC(hwnd);dc=win32ui.CreateDCFromHandle(source);memory=dc.CreateCompatibleDC();bitmap=win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(dc,w,h);memory.SelectObject(bitmap)
            memory.BitBlt((0,0),(w,h),dc,(0,0),win32con.SRCCOPY)
            image=Image.frombuffer('RGB',(w,h),bitmap.GetBitmapBits(True),'raw','BGRX',0,1)
            from PIL import ImageStat,ImageGrab
            if max(ImageStat.Stat(image.resize((64,36))).stddev)<2:
                if win32gui.GetForegroundWindow()!=hwnd:
                    raise AdmissionError('OFFICIAL_WINDOW_PIXELS_UNAVAILABLE_BRING_OWN_WINDOW_TO_FRONT')
                image=ImageGrab.grab(bbox=(left,top,right,bottom),all_screens=True)
                if max(ImageStat.Stat(image.resize((64,36))).stddev)<2:
                    raise AdmissionError('OFFICIAL_WINDOW_CAPTURE_EMPTY')
            path=inside(self.root,'state/issac-acceptance/official-ui')/(label+'-'+uuid.uuid4().hex+'.png')
            path.parent.mkdir(parents=True,exist_ok=True);image.save(path)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle());memory.DeleteDC();dc.DeleteDC();win32gui.ReleaseDC(hwnd,source)
        record={'label':label,'path':path.relative_to(self.root).as_posix(),'sha256':file_hash(path),
            'pid':row['pid'],'created_at':row['created_at'],'candidate_id':self.candidate['candidate_id'],
            'captured_unix':time.time(),'method':'real_owned_official_window_pixels'}
        write_json(path.with_suffix('.json'),record);return record

    def approve_scene(self,relative):
        review=read_json(inside(self.root,relative));owner=self.owner()
        if (review.get('candidate_id')!=self.candidate['candidate_id'] or review.get('official_pid')!=owner['pid']
            or review.get('official_created_at')!=owner['created_at'] or not review.get('reviewer')
            or set(review.get('checks',{}))!=SCENE_CHECKS or not all(v is True for v in review['checks'].values())
            or review.get('programme_url')!='http://127.0.0.1:8062/issac/programme?renderer=livehime'):
            raise AdmissionError('ACTUAL_OFFICIAL_SCENE_REVIEW_REQUIRED')
        labels=set()
        for row in review.get('screenshots',[]):
            path=inside(self.root,row['path']);capture=read_json(path.with_suffix('.json'))
            if (capture!=row or file_hash(path)!=row['sha256'] or row['pid']!=owner['pid']
                or row['candidate_id']!=self.candidate['candidate_id']):raise AdmissionError('OFFICIAL_UI_REVIEW_EVIDENCE_CHANGED')
            labels.add(row['label'])
        if not {'scene_sources','audio_settings','video_settings'}.issubset(labels):
            raise AdmissionError('ACTUAL_SCENE_AUDIO_VIDEO_SCREENS_REQUIRED')
        review['accepted']=True;review['reviewed_unix']=time.time()
        write_json(inside(self.root,'state/issac-acceptance/official-scene.json'),review)
        return {'accepted':True,'official_scene_review_sha256':digest(review),'public_broadcast_started':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('action',choices=['prepare','launch','status','inspect','record-start','record-stop','screenshot','approve-scene'])
    parser.add_argument('--label');parser.add_argument('--review');args=parser.parse_args();client=Livehime(args.root.resolve())
    result=client.prepare() if args.action=='prepare' else client.launch() if args.action=='launch' else client.owner() if args.action=='status' else client.screenshot(args.label) if args.action=='screenshot' else client.approve_scene(args.review) if args.action=='approve-scene' else client.ui(args.action)
    print(json.dumps(result,ensure_ascii=False))
