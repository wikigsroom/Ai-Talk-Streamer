"""Record only the native game framebuffer; always finish with a normal pause."""
from pathlib import Path
from datetime import datetime
import argparse
import json
import shutil
import time
import win32gui
import win32process
from native_request import request
from stack_control import arm, pause, native_state, game_identity
from verify_dsh import api

ROOT = Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=40)
    parser.add_argument('--mode',choices=['local','dsh'],default='local')
    args=parser.parse_args()
    if not 5<=args.seconds<=120:raise SystemExit('Use a bounded 5..120 second recording')
    folder=ROOT/'recordings'/('demo_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    folder.mkdir(parents=True,exist_ok=False)
    game,_=game_identity();samples=[];frames=[]
    result={'source':'native_game_framebuffer','mode':args.mode,'requested_seconds':args.seconds,
            'simulated':False,'initial':native_state(),'started_at':datetime.now().astimezone().isoformat()}
    started=time.monotonic()
    try:
        result['arm']=arm(local_only=args.mode=='local')
        started=time.monotonic();next_sample=started
        while time.monotonic()-started<args.seconds:
            current=time.monotonic()
            frame=request(op='capture',timeout=5)
            path=folder/('frame-%05d.png'%len(frames))
            shutil.copy2(frame['path'],path)
            # Native capture's generated temporary PNG is disposable after copying.
            Path(frame['path']).unlink()
            frames.append({'file':path.name,'t':round(current-started,4)})
            if current>=next_sample:
                q=api(9532,'/query',timeout=2).get('data') or {}
                host=api(9533,'/status',timeout=2)
                hwnd=win32gui.GetForegroundWindow();fg=win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else 0
                hp=q.get('health') or {}
                samples.append({'elapsed_s':round(current-started,2),'frame':q.get('frame'),
                    'room':q.get('room'),'identity':q.get('identity'),'health':hp,
                    'resources':q.get('resources'),'enemies':len(q.get('enemies',[])),
                    'game_foreground':fg==game.pid,'dsh_turns':host.get('turns'),
                    'receipts':api(9532,'/status',timeout=2).get('recent_receipts')})
                next_sample=current+1
                if q.get('room',{}).get('dead') or hp.get('red_hearts',0)+hp.get('soul_hearts',0)<=2:
                    result['stop_reason']='low_health_or_death';break
            time.sleep(max(0,.2-(time.monotonic()-current)))
        result.setdefault('stop_reason','bounded_recording_finished')
    except Exception as error:
        result['error']=str(error)[:300]
    finally:
        result['pause']=pause();result['final']=native_state()
        result['elapsed_s']=round(time.monotonic()-started,2)
        result['samples']=samples;result['frames']=frames
        result['all_samples_background']=bool(samples) and all(not s['game_foreground'] for s in samples)
        result['background_frames_advanced']=any((b.get('frame') or 0)>(a.get('frame') or 0) and not a['game_foreground'] and not b['game_foreground'] for a,b in zip(samples,samples[1:]))
        result['rooms_observed']=sorted({s.get('identity',{}).get('room') for s in samples if s.get('identity',{}).get('room') is not None})
        (folder/'evidence.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        # Preserve observed frame intervals, rather than speeding up a variable-rate capture.
        lines=['ffconcat version 1.0']
        for index,item in enumerate(frames):
            duration=frames[index+1]['t']-item['t'] if index+1<len(frames) else .2
            lines.extend(["file '"+item['file']+"'",'duration %.4f'%max(.01,duration)])
        if frames:lines.append("file '"+frames[-1]['file']+"'")
        (folder/'frames.ffconcat').write_text('\n'.join(lines)+'\n',encoding='ascii')
        print(json.dumps({'folder':str(folder),'frames':len(frames),'elapsed_s':result['elapsed_s'],
            'background':result['all_samples_background'],'rooms':result['rooms_observed'],
            'pause_acknowledged':result['pause']['normal_game_pause_acknowledged'],
            'error':result.get('error')}))


if __name__=='__main__':main()
