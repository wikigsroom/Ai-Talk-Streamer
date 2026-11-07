"""The only Python control host: existing local bridge plus strategic cache/API."""
from pathlib import Path
import argparse
import json
import os
import signal
import sys
import threading
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.strategy import StrategyService
from isaac_jev.strategy_server import StrategyServer
from isaac_jev.runtime import BridgeRuntime
from isaac_jev.models import GameState
from isaac_jev.web_dashboard import LocalDashboard
from start_dsh import bridge_token


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--replay');args=parser.parse_args()
    os.chdir(ROOT)
    stop=threading.Event()
    settings=json.loads((ROOT/'config/strategy.json').read_text(encoding='utf8'))
    window=float(settings.get('decision_seconds',45))
    if not 5<=window<=60:raise SystemExit('strategy.decision_seconds must be between 5 and 60')
    service=StrategyService(ROOT/'logs/strategy',decision_seconds=window)
    runtime=dashboard=None
    if args.replay:
        raw=json.loads(Path(args.replay).read_text(encoding='utf8'))
        if 'raw_state' in raw: raw=raw['raw_state']
        service.configure(enabled=True,live=False)
        service.emit('replay_mode',fixture=Path(args.replay).name,game_connected=False)
        def replay():
            while not stop.wait(.1):
                service.update(raw,GameState.from_message(raw))
        threading.Thread(target=replay,daemon=True).start()
    else:
        config=json.loads((ROOT/'config/decision_provider.json').read_text(encoding='utf8'))
        if config.get('selected_provider')!='local' or config.get('shadow_enabled') is not False:
            raise SystemExit('Real-time controller must remain local with shadow disabled')
        runtime=BridgeRuntime(autopilot=False,log_dir=str(ROOT/'logs/live'))
        runtime.controller.strategy_service=service
        runtime.start()
        dashboard=LocalDashboard(runtime.controller);dashboard.start()
    api=StrategyServer(service,bridge_token());api.start()
    import psutil
    record={'pid':os.getpid(),'created_at':psutil.Process().create_time(),'mode':'replay' if args.replay else 'live_observation','bridge':bool(runtime),'autopilot':False,
            'api':'http://127.0.0.1:9532','started_at':time.time()}
    (ROOT/'strategy-process.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    print(json.dumps(record),flush=True)
    signal.signal(signal.SIGINT,lambda *_:stop.set());signal.signal(signal.SIGTERM,lambda *_:stop.set())
    try: stop.wait()
    finally:
        service.configure(enabled=False)
        if dashboard: dashboard.stop()
        if runtime: runtime.stop()
        api.close();service.close()

if __name__=='__main__': main()
