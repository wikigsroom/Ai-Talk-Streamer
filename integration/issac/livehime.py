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

RENDER_ARGUMENTS={
    'software-ui':['--disable-gpu','--disable-gpu-compositing',
                   '--disable-gpu-rasterization','--disable-direct-composition'],
    'd3d11-ui':['--use-gl=angle','--use-angle=d3d11','--disable-direct-composition'],
    'native-ui':[]}


def render_arguments(root,mode=None):
    config=read_json(inside(root,'configs/issac/official-rendering.json'))
    mode=mode or config['default_mode']
    if mode not in RENDER_ARGUMENTS:raise AdmissionError('BOUNDED_OFFICIAL_RENDER_MODE_REQUIRED')
    return mode,list(RENDER_ARGUMENTS[mode])


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

    def native_window(self,action,*,pending=False,label=None):
        executable=inside(self.root,'runtime/isaac-native/Scripts/python.exe')
        args=[str(executable),'-X','utf8','-B','-m','integration.issac.official_window','--root',str(self.root),action]
        if pending:args.append('--pending')
        if label:args.extend(['--label',label])
        result=subprocess.run(args,cwd=self.root,capture_output=True,timeout=25,creationflags=0x08000000)
        if result.returncode:
            self.audit.append('official_window_probe_failed',action=action,private_diagnostic=result.stderr.decode('utf8',errors='replace')[-1500:])
            raise AdmissionError('OWNED_OFFICIAL_WINDOW_NOT_CONFIRMED')
        return json.loads(result.stdout.decode('utf-8-sig'))

    def launch(self,render_mode=None):
        import psutil
        mode,graphics=render_arguments(self.root,render_mode)
        if self.registration.exists():
            old=read_json(self.registration)
            try:
                process=psutil.Process(old['pid'])
                if process.create_time()==old['created_at']:
                    if old.get('render_mode')!=mode:
                        raise AdmissionError('LIVE_OWNED_CLIENT_REQUIRES_NORMAL_CLOSE_BEFORE_RENDERER_CHANGE')
                    return self.owner()  # never replace/adopt a live old candidate
            except psutil.NoSuchProcess:pass
            archive=inside(self.root,'operations/official-client-history')/(uuid.uuid4().hex+'.json')
            archive.parent.mkdir(parents=True,exist_ok=True);self.registration.replace(archive)
        pending=inside(self.root,'.setup/issac-livehime-launch.json')
        if pending.exists():
            old=read_json(pending)
            try:
                if psutil.Process(old['pid']).create_time()==old['created_at']:
                    raise AdmissionError('PREVIOUS_OWNED_OFFICIAL_LAUNCH_REQUIRES_REVIEW')
            except psutil.NoSuchProcess:pass
        # The official client may enforce a global singleton. Do not discover
        # that by forwarding a launch into an unrelated user's live session.
        for proc in psutil.process_iter(['name','exe']):
            try:
                if (proc.info['name'] or '').lower()=='livehime.exe':
                    raise AdmissionError('EXISTING_OFFICIAL_CLIENT_PRESERVED_EXCLUSIVE_WINDOW_REQUIRED')
            except (psutil.NoSuchProcess,psutil.AccessDenied):continue
        self.prepare();start=time.time();env=dict(os.environ)
        base=inside(self.root,'state/issac-stream/livehime')
        from .windows_profile import configure,verify_in_child
        configure(env,base/'profile')
        known_folders=verify_in_child(self.root,env,base/'profile')
        handle=subprocess.Popen([str(self.executable),*graphics],cwd=self.executable.parent,env=env,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000)
        process=psutil.Process(handle.pid)
        record={'pid':process.pid,'created_at':process.create_time(),'executable':str(self.executable),
                'executable_sha256':file_hash(self.executable),'launched_unix':start,'candidate_id':self.candidate['candidate_id'],
                'known_folder_proof':known_folders,
                'render_mode':mode,'requested_render_arguments':graphics,'visible_ui_accepted':False,
                'foreign_clients_preserved':True,'ready':False,'profile_isolation_verified':False}
        write_json(pending,record)
        return self.wait_ready(handle,process,record)

    def wait_ready(self,handle,process,record):
        deadline=time.monotonic()+90;stable=None;since=None;profile_pending=False;last_report=0
        while time.monotonic()<deadline:
            if handle.poll() is not None:
                self.audit.append('official_launcher_exited_before_ready',pid=process.pid,exit_code=handle.returncode)
                raise AdmissionError('OFFICIAL_LAUNCHER_EXITED_BEFORE_STABLE_WINDOW')
            windows=self.native_window('windows',pending=True)['windows']
            key=tuple((w['hwnd'],w['pid'],w['created_at']) for w in windows)
            if len(windows)==1 and key==stable:
                if time.monotonic()-since>=5:
                    proof=self.native_window('profile',pending=True)
                    if not proof['verified']:
                        profile_pending=True
                        if proof.get('foreign_profile_files'):
                            self.audit.append('official_foreign_profile_observed',private_profile_evidence=proof)
                            raise AdmissionError('OFFICIAL_RUNTIME_PROFILE_ISOLATION_NOT_CONFIRMED')
                        if time.monotonic()-last_report>=10:
                            self.audit.append('waiting_for_actual_official_profile',private_profile_evidence=proof)
                            last_report=time.monotonic()
                        time.sleep(.4)
                        continue
                    record.update(ready=True,profile_isolation_verified=True,profile_proof=proof,
                                  window=windows[0],stable_window_seconds=5,ready_unix=time.time())
                    write_json(self.registration,record)
                    self.audit.append('owned_official_client_ready',pid=process.pid,window_pid=windows[0]['pid'])
                    return record
            else:stable=key;since=time.monotonic()
            time.sleep(.4)
        if profile_pending:raise AdmissionError('OFFICIAL_RUNTIME_PROFILE_ISOLATION_NOT_CONFIRMED')
        raise AdmissionError('ISOLATED_OFFICIAL_CLIENT_NOT_OBSERVED_FOREIGN_CLIENTS_PRESERVED')

    def owner(self):
        import psutil
        row=read_json(self.registration);process=psutil.Process(row['pid'])
        if (row['candidate_id']!=self.candidate['candidate_id'] or process.create_time()!=row['created_at']
            or Path(process.exe()).resolve()!=self.executable or file_hash(self.executable)!=row['executable_sha256']
            or row.get('ready') is not True or row.get('profile_isolation_verified') is not True):
            raise AdmissionError('OWNED_OFFICIAL_CLIENT_IDENTITY_OR_READY_STATE_CHANGED')
        return row

    def ui(self,action='inspect'):
        row=self.owner();observed=self.native_window('windows')['windows']
        if len(observed)!=1:raise AdmissionError('ONE_VISIBLE_OWNED_OFFICIAL_WINDOW_REQUIRED')
        window=observed[0]
        if action=='record-start':
            scene=read_json(inside(self.root,'state/issac-acceptance/official-scene.json'))
            if scene.get('accepted') is not True or scene.get('candidate_id')!=self.candidate['candidate_id'] or scene.get('official_pid')!=row['pid']:
                raise AdmissionError('CURRENT_OFFICIAL_SCENE_REVIEW_REQUIRED_BEFORE_RECORDING')
        script=inside(self.root,'scripts/issac_livehime_ui.ps1')
        result=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe','-NoProfile','-NonInteractive',
            '-ExecutionPolicy','Bypass','-File',str(script),'-ProcessId',str(window['pid']),'-WindowHandle',str(window['hwnd']),'-Action',action],
            capture_output=True,timeout=25,creationflags=0x08000000)
        if result.returncode:raise AdmissionError('OFFICIAL_RECORD_CONTROL_NOT_CONFIRMED_USE_VISIBLE_UI_REVIEW')
        value=json.loads(result.stdout.decode('utf-8-sig'));self.audit.append('official_ui',action=action,pid=row['pid'])
        return value

    def screenshot(self,label):
        self.owner()
        return self.native_window('screenshot',label=label)

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
    parser.add_argument('--label');parser.add_argument('--review');parser.add_argument('--render-mode',choices=list(RENDER_ARGUMENTS))
    args=parser.parse_args();client=Livehime(args.root.resolve())
    result=client.prepare() if args.action=='prepare' else client.launch(args.render_mode) if args.action=='launch' else client.owner() if args.action=='status' else client.screenshot(args.label) if args.action=='screenshot' else client.approve_scene(args.review) if args.action=='approve-scene' else client.ui(args.action)
    print(json.dumps(result,ensure_ascii=False))
