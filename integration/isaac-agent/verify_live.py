"""Bounded real-game validation, always ending with an acknowledged normal pause."""
from pathlib import Path
import argparse
import json
import time
import win32gui
import win32process
import psutil
from verify_dsh import api
from stack_control import arm, pause, native_state, game_identity
from native_request import request

ROOT=Path(__file__).resolve().parent


def disconnect_test():
    record=json.loads((ROOT/'strategy-process.json').read_text(encoding='utf8'))
    p=psutil.Process(record['pid'])
    if Path(p.cwd())!=ROOT or not any(Path(a).name=='run_strategy.py' for a in p.cmdline()):
        raise RuntimeError('Controller process identity changed')
    before=native_state(); suspended=False
    try:
        p.suspend();suspended=True
        deadline=time.monotonic()+7
        observed=before
        while time.monotonic()<deadline:
            time.sleep(.2);observed=native_state()
            if observed['paused']:break
        time.sleep(.3);stable=native_state()
        ack=json.loads(request('local j=_G.json or require("json");return j.encode(_G.__NativeIsaacController.strategyControl.pauseAck)',timeout=4))
        return {'method':'suspend_verified_controller_not_game', 'before':before,'observed':observed,'stable':stable,
                'ack':ack,'pass':bool(observed['paused'] and stable['paused'] and stable['frame']==observed['frame']
                                     and ack and ack.get('id')=='controller-lease-expired')}
    finally:
        if suspended:p.resume()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=120);parser.add_argument('--fault',action='store_true')
    parser.add_argument('--output',default='live-dsh-verification.json');args=parser.parse_args()
    if Path(args.output).name!=args.output:raise SystemExit('Output must be a filename under logs/build')
    game,_=game_identity();samples=[];result={'source':'native_game','simulated_progress':False,'initial':native_state()}
    start=time.monotonic(); before=api(9533,'/status');first_success=None
    try:
        result['arm']=arm()
        while time.monotonic()-start<args.seconds:
            s=api(9532,'/status',timeout=3);q=api(9532,'/query',timeout=3)['data'];h=win32gui.GetForegroundWindow()
            fg=win32process.GetWindowThreadProcessId(h)[1] if h else 0
            sample={'elapsed_s':round(time.monotonic()-start,2),'frame':q.get('frame'),'room':q.get('identity',{}).get('room'),
                    'health':q.get('health'),'enemies':len(q.get('enemies',[])), 'clear':q.get('room',{}).get('clear'),
                    'paused':q.get('room',{}).get('paused'),'foreground_pid':fg,'game_foreground':fg==game.pid,
                    'pending':s.get('pending'),'executing':s.get('executing'),'receipts':s.get('recent_receipts')}
            if s.get('executing') and (not samples or time.monotonic()-start-samples[-1].get('native_elapsed_s',-10)>2):
                try:sample['native_control']=json.loads(request('return _G.__NativeIsaacController:NativeControlStatus()',timeout=4))
                except Exception as exc:sample['native_diagnostic_error']=str(exc)[:150]
                sample['native_elapsed_s']=time.monotonic()-start
            elif samples:sample['native_elapsed_s']=samples[-1].get('native_elapsed_s',-10)
            samples.append(sample)
            (ROOT/'logs/build/live-current.json').write_text(json.dumps(sample,ensure_ascii=False,indent=2),encoding='utf8')
            successes=[r for r in s.get('recent_receipts',[]) if r.get('status')=='succeeded' and r.get('effect')!='wait']
            if successes and first_success is None:first_success=time.monotonic()
            if q.get('room',{}).get('dead'):result['stop_reason']='player_dead';break
            health=q.get('health',{});total=health.get('red_hearts',0)+health.get('soul_hearts',0)
            if total<=2:result['stop_reason']='low_health_safety_limit';break
            if successes and q.get('room',{}).get('clear') and time.monotonic()-first_success>2:
                result['stop_reason']='non_wait_effect_observed';
                if args.fault:result['controller_disconnect']=disconnect_test()
                break
            time.sleep(.5)
        result.setdefault('stop_reason','bounded_validation_deadline')
    except Exception as error:
        result['error']=str(error)
    finally:
        result['pause']=pause();result['final']=native_state()
        after=api(9533,'/status');result['dsh_turns']=after['turns']-before['turns']
        result['model']=after['model'];result['dsh_version']=after['dshVersion'];result['samples']=samples
        result['non_wait_successes']={r['plan_id']:r for s in samples for r in s['receipts'] if r['status']=='succeeded' and r.get('effect')!='wait'}
        result['background_frames_advanced']=any(b['frame']>a['frame'] and not a['game_foreground'] and not b['game_foreground'] for a,b in zip(samples,samples[1:]))
        result['all_samples_background']=bool(samples) and all(not s['game_foreground'] for s in samples)
        result['elapsed_s']=round(time.monotonic()-start,2)
        result['pass']=bool(result['non_wait_successes'] and result['background_frames_advanced'] and result['pause']['normal_game_pause_acknowledged'] and not result.get('error'))
        (ROOT/'logs/build'/args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:v for k,v in result.items() if k not in {'samples'}},ensure_ascii=False,indent=2))
    if not result['pass']:raise SystemExit(1)


if __name__=='__main__':main()
