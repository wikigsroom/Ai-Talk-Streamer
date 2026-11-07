"""Continue ordinary slot-3 runs until a verified, progression-enabled Satan kill.

The supervisor only observes progression, switches local automatic control and
requests an ordinary new run after an intermediate ending. It never writes saves,
unlocks, inventory, health, damage, stages or room state.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time
from datetime import datetime
import urllib.request

from native_request import request

ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:9529'


def read_json(path):
    for attempt in range(5):
        try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except (OSError,json.JSONDecodeError):
            if attempt==4: raise
            time.sleep(.03)


def read_with_retry(operation, on_retry=None):
    """Retry transient observation I/O only; never retry guards or mutations."""
    for attempt in range(3):
        try:
            return operation()
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            if attempt == 2:
                raise
            if on_retry:
                on_retry(attempt + 1, error)
            time.sleep(.25 * (attempt + 1))


def controller_status(on_retry=None):
    def read():
        with urllib.request.urlopen(URL+'/api/status?compact=1',timeout=3) as response:
            return json.load(response)
    return read_with_retry(read, on_retry)


def native_progress(on_retry=None):
    return read_with_retry(lambda: request(op='progress',timeout=5), on_retry)


def autopilot(enabled):
    payload=json.dumps({'enabled':enabled}).encode()
    req=urllib.request.Request(URL+'/api/autopilot?compact=1',data=payload,
        headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=5) as response:
        return json.load(response)


def check_progress_guard(progress):
    if progress.get('slot')!=3 or progress.get('readonly') is not False:
        raise RuntimeError('Slot-3 progression eligibility failed: '+json.dumps(progress))
    for key in ('mom_heart_kills','satan_kills'):
        if type(progress.get(key)) is not int or not 0<=progress[key]<=100000:
            raise RuntimeError('Invalid native progression observation')


def check_existing_saves():
    protection=read_json(ROOT/'save-protection.json')
    manifest=read_json(protection['baseline_manifest'])
    checked=0
    for item in manifest['files']:
        path=Path(item['source'])
        if path.suffix.lower()!='.dat': continue
        checked+=1
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError('Existing save changed: '+str(path))
    return checked


def ending_disposition(progress,result,raw,baseline_satan=0,live_seed=None):
    """A victory on another floor must never be reported as the Satan goal."""
    check_progress_guard(progress)
    if not result or result.get('result')!='victory': return 'play'
    if live_seed is not None and raw.get('start_seed')!=live_seed: return 'wait'
    if result.get('start_seed')!=raw.get('start_seed'): return 'wait'
    stage=result.get('stage')
    stage_type=result.get('stage_type',raw.get('stage_type'))
    if stage==10 and stage_type==0 and progress['satan_kills']>baseline_satan:
        return 'complete'
    if stage in (6,8) and progress.get('womb_unlocked'):
        return 'new_run'
    raise RuntimeError('Unverified or unexpected ending; preserve it for inspection')


def main():
    log=ROOT/'logs'/'satan_progression_20261106_1042'
    log.mkdir(exist_ok=True,parents=True)
    def record(kind,**values):
        event={'at':datetime.now().astimezone().isoformat(),'kind':kind,**values}
        with (log/'satan-supervisor.jsonl').open('a',encoding='utf-8') as out:
            out.write(json.dumps(event,ensure_ascii=False)+'\n')
        print(json.dumps(event,ensure_ascii=True),flush=True)
    def retry_notice(attempt,error):
        record('observation_retry',attempt=attempt,error=repr(error))
    progress=native_progress(retry_notice)
    check_progress_guard(progress)
    checked=check_existing_saves()
    baseline_satan=progress['satan_kills']
    if baseline_satan: raise RuntimeError('A Satan mark already exists; inspect before new play')
    record('started',progress=progress,existing_saves_checked=checked)
    seen=None
    pending_seed=None
    ending_seen_at=0
    last_progress=None
    seen_damage=set()
    try:
        while True:
            status=controller_status(retry_notice)
            identity=read_json(ROOT/'controller-process.json')
            raw=read_with_retry(lambda: read_json(Path(identity['log_directory'])/'latest-raw-state.json'),retry_notice)
            progress=native_progress(retry_notice)
            check_progress_guard(progress)
            for damage in raw.get('damage_events',[]):
                identity=(raw.get('start_seed'),damage.get('frame'),damage.get('id'))
                if identity in seen_damage: continue
                seen_damage.add(identity)
                snapshot=log/f"damage-{identity[0]}-{identity[1]}.json"
                if not snapshot.exists():
                    snapshot.write_text(json.dumps({'damage_event':damage,'raw_state':raw},
                        ensure_ascii=False,indent=2),encoding='utf-8')
                    record('damage',seed=identity[0],event=damage,stage=raw.get('stage'),
                        room_index=raw.get('room_index'),hp=raw.get('player',{}).get('hp'))
            if progress!=last_progress:
                record('progression',progress=progress)
                last_progress=progress
            key=(raw.get('start_seed'),raw.get('stage'))
            if key!=seen:
                record('floor',seed=key[0],stage=key[1],player=raw.get('player'),
                    existing_saves_checked=check_existing_saves())
                seen=key
            result=status.get('game_result')
            live_seed=None
            if result and result.get('result')=='victory':
                live_seed=read_with_retry(lambda: json.loads(request(
                    "return require('json').encode({seed=Game():GetSeeds():GetStartSeed()})",timeout=5))['seed'],retry_notice)
            disposition=ending_disposition(progress,result,raw,baseline_satan,live_seed=live_seed)
            if disposition=='complete':
                autopilot(False)
                frame=request(op='capture')
                proof={'progress':progress,'native_game_event':result,'raw_state':raw,
                    'screenshot':frame,'existing_saves_checked':check_existing_saves(),
                    'remote_calls':status.get('remote_call_count')}
                (log/'satan-victory.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
                record('satan_complete',progress=progress,seed=raw.get('start_seed'))
                return
            if disposition=='new_run':
                if pending_seed!=raw['start_seed']:
                    pending_seed=raw['start_seed']; ending_seen_at=time.monotonic()
                    proof={'progress':progress,'native_game_event':result,'raw_state':raw}
                    (log/f"milestone-{pending_seed}.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
                    record('intermediate_ending',progress=progress,result=result)
                elif time.monotonic()-ending_seen_at>=8:
                    # An actual ending has already stopped automatic control.
                    # Only the game's ordinary restart command is permitted.
                    check_existing_saves()
                    check_progress_guard(request(op='progress'))
                    identity=json.loads(request("return require('json').encode({seed=Game():GetSeeds():GetStartSeed()})"))
                    if identity['seed']!=pending_seed:
                        continue
                    request("Isaac.ExecuteCommand('restart'); return 'ordinary restart requested'")
                    deadline=time.monotonic()+20
                    while time.monotonic()<deadline:
                        live=json.loads(request("return require('json').encode({seed=Game():GetSeeds():GetStartSeed(),players=Game():GetNumPlayers(),frame=Game():GetFrameCount()})"))
                        if live['seed']!=pending_seed and live['players']==1 and live['frame']>=2: break
                        time.sleep(.3)
                    else: raise RuntimeError('New ordinary run did not start')
                    check_progress_guard(request(op='progress'))
                    if request('return tostring(__NativeIsaacController:NativeResume())')!='true':
                        raise RuntimeError('Native controller could not resume the living player')
                    autopilot(True)
                    # Do not inspect the old ending again until both the
                    # bridge and Python have acknowledged the new seed.
                    deadline=time.monotonic()+20
                    while time.monotonic()<deadline:
                        current=read_json(log/'latest-raw-state.json')
                        if current.get('start_seed')==live['seed'] and current.get('frame',-1)>=2:
                            break
                        time.sleep(.1)
                    else: raise RuntimeError('New-run observation was not acknowledged')
                    record('ordinary_new_run',previous_seed=pending_seed,seed=live['seed'])
                    pending_seed=None
            time.sleep(3)
    except BaseException as error:
        try: autopilot(False)
        except Exception: pass
        record('stopped_for_inspection',error=repr(error))
        raise


if __name__=='__main__': main()
