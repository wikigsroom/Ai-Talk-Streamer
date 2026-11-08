"""Own only the voice, real mouth/page and one isolated rehearsal browser."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integration.issac.common import AdmissionError, FileLease, inside, port_available, read_json, write_json
from integration.issac.deployment import require_candidate
from integration.issac.preparation import relocate_native_environments, runtime_environment
from integration.issac.offline_dependencies import install_voice_dependencies
from integration.issac.shutdown import media_rehearsal_stops


def main(root):
    import psutil
    candidate=require_candidate(root)
    owner=FileLease(inside(root,'state/issac-stream/media30-controller.lock')).acquire()
    work=inside(root,'operations/media30-live');work.mkdir(parents=True,exist_ok=True)
    stop,voice_stop=media_rehearsal_stops(root,candidate['candidate_id'])
    stop.parent.mkdir(parents=True,exist_ok=True)
    if stop.exists() or voice_stop.exists():raise AdmissionError('REVIEW_PRIOR_MEDIA30_STOP_BEFORE_A_NEW_RUN')
    if not all(port_available(p) for p in (9893,8072,9223)):
        raise AdmissionError('MEDIA_REHEARSAL_PORT_OCCUPIED_PRESERVED')
    relocate_native_environments(root);install_voice_dependencies(root)
    config=read_json(inside(root,'configs/issac/runtime.json'))
    http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    children=[];logs=[]
    def status(stage,**extra):
        write_json(work/'status.json',{'stage':stage,'pid':os.getpid(),'candidate':candidate,'at_unix':time.time(),
            'children':children,'stop_request':str(stop),'game_started':False,'strategy_model_loaded':False,'public_broadcast_started':False,**extra})
    def start(name,exe,args,kind,stopfile=None):
        log=(work/(name+'.log')).open('ab');logs.append(log)
        env=runtime_environment(root,kind)
        if stopfile:env['ISSAC_STOP_FILE']=str(stopfile)
        process=subprocess.Popen([str(exe),*args],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,creationflags=0x08000000)
        identity=psutil.Process(process.pid)
        row={'name':name,'pid':process.pid,'created_at':identity.create_time(),'executable':str(exe)}
        children.append(row)
        return process
    def get():
        with http.open('http://127.0.0.1:8072/status',timeout=3) as response:return json.load(response)
    failed=False
    try:
        status('starting_frozen_ncm01')
        voice=start('voice',inside(root,config['native_paths']['voice_python']),['-X','utf8','-B','-m','integration.issac.voice','--root',str(root)],'voice',voice_stop)
        deadline=time.monotonic()+1800
        while True:
            if voice.poll() is not None:raise AdmissionError('NCM01_CHILD_EXITED')
            try:
                with http.open('http://127.0.0.1:9893/health',timeout=3) as response:health=json.load(response)
            except OSError:health={}
            if health.get('error') or health.get('initialization',{}).get('stage')=='failed':raise AdmissionError('NCM01_INITIALIZATION_FAILED')
            if health.get('ready'):break
            if time.monotonic()>deadline:raise AdmissionError('NCM01_PREPARATION_DEADLINE')
            status('preparing_ncm01');time.sleep(2)
        page=start('live-page',inside(root,config['native_paths']['media_python']),['-X','utf8','-B','-m','integration.issac.media_rehearsal','--root',str(root)],'engine',stop)
        deadline=time.monotonic()+2400
        while True:
            if page.poll() is not None:raise AdmissionError('LIVE_PAGE_CHILD_EXITED')
            try:health=get()
            except OSError:health={}
            if health.get('error'):raise AdmissionError(health['error'])
            status('preparing_live_page',media=health)
            if health.get('ready'):break
            if time.monotonic()>deadline:raise AdmissionError('REAL_MOUTH_PREPARATION_DEADLINE')
            time.sleep(2)
        chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        if not chrome.is_file():raise AdmissionError('EXISTING_NATIVE_CHROME_REQUIRED')
        browser=start('rehearsal-browser',chrome,['--user-data-dir='+str(inside(root,'state/issac-stream/media30-browser')),
            '--remote-debugging-port=9223','--no-first-run','--no-default-browser-check','--start-maximized',
            '--app=http://127.0.0.1:8072/'],'browser')
        status('waiting_for_record_button',media=health)
        deadline=time.monotonic()+1800
        while time.monotonic()<deadline and not stop.exists():
            if voice.poll() is not None or page.poll() is not None:raise AdmissionError('MEDIA_CHILD_ENDED_DURING_RECORDING')
            health=get();status('recording_or_waiting_for_button',media=health)
            if len(health.get('completed',{}))==3:
                status('recordings_complete',media=health)
                break
            time.sleep(2)
        else:raise AdmissionError('MEDIA_REHEARSAL_BUTTON_OR_RECORDING_DEADLINE')
        # Wait for normal browser close requested via its own CDP target/UI.
        # This controller never closes an unrelated browser or user application.
        deadline=time.monotonic()+1800
        while time.monotonic()<deadline and not stop.exists():time.sleep(1)
    except Exception as error:
        failed=True
        status('failed',error=str(error));(work/'private-error.log').write_text(traceback.format_exc(),'utf8')
    finally:
        stop.write_text('media-only stop','ascii');voice_stop.write_text('media-only stop','ascii')
        for row in children:
            if row['name']=='rehearsal-browser':continue
            try:
                process=psutil.Process(row['pid'])
                if process.create_time()!=row['created_at']:continue
                process.wait(timeout=90)
            except psutil.NoSuchProcess:pass
            except psutil.TimeoutExpired:
                status('owned_cleanup_not_confirmed',name=row['name'])
                # Preserve evidence and leave identity-based review to caller.
        for log in logs:log.close()
        owner.close()
    if failed:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args()
    main(args.root.resolve())
