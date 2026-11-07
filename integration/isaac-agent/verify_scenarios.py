"""Twelve real DSH/Luna decisions over labelled replay cases; never attaches to Isaac."""
from pathlib import Path
import json
import sys
import threading
import time
import statistics
import argparse
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from isaac_jev.strategy import StrategyService, DOMAINS
from isaac_jev.strategy_server import StrategyServer
from isaac_jev.models import GameState
from strategy_fixtures import scenario
from start_dsh import bridge_token
from verify_dsh import api


def usage_totals():
    # Official assistant/message records only: other records repeat the same
    # usage. totalTokens includes cacheReadTokens in this provider's accounting.
    totals={k:0 for k in ('inputTokens','outputTokens','totalTokens','cacheReadTokens','cacheWriteTokens')}
    totals['assistantMessages']=0
    for path in (ROOT/'.dsh-home/sessions').rglob('session.v4.jsonl'):
        for line in path.read_text(encoding='utf8').splitlines():
            try: row=json.loads(line)
            except ValueError: continue
            if row.get('type')!='assistant/message':continue
            usage=row.get('data',{}).get('usage')
            if not isinstance(usage,dict):continue
            totals['assistantMessages']+=1
            for key in totals:
                if key!='assistantMessages':totals[key]+=int(usage.get(key,0) or 0)
    return totals

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--domains',nargs='+',choices=list(DOMAINS),default=list(DOMAINS))
    parser.add_argument('--decision-seconds',type=float,default=45)
    parser.add_argument('--output',default='dsh-12-domain-verification.json');args=parser.parse_args()
    if Path(args.output).name!=args.output:raise SystemExit('Output must be a filename under logs/build')
    if not 5<=args.decision_seconds<=60:raise SystemExit('Decision window must be 5..60 seconds')
    service=StrategyService(ROOT/'logs/scenarios',decision_seconds=args.decision_seconds)
    server=StrategyServer(service,bridge_token());server.start()
    stop=threading.Event();raw_holder=[None];guard=threading.RLock()
    def refresh():
        while not stop.wait(.1):
            with guard:
                if raw_holder[0]: service.update(raw_holder[0],GameState.from_message(raw_holder[0]))
    thread=threading.Thread(target=refresh,daemon=True);thread.start()
    results=[]
    try:
        api(9533,'/control',{'automatic':False})
        for index,domain in enumerate(args.domains):
            # Session-file accounting can be slow on Windows. Complete it
            # before creating the expiring decision, never inside its budget.
            preparation=time.monotonic()
            usage_before=usage_totals()
            before=api(9533,'/status')
            raw=scenario(domain);raw['start_seed']+=index+1
            preparation_ms=round((time.monotonic()-preparation)*1000,1)
            with guard:
                service.configure(enabled=False)
                raw_holder[0]=raw
                service.configure(enabled=True,live=False);service.update(raw,GameState.from_message(raw))
                decision=service.decision()
            start=time.monotonic()
            error=None
            try:
                turn=api(9533,'/run',{'prompt':f'这是新的离线回放测试，重点决策域 {domain}（{DOMAINS[domain]}）。使用插件附上的已绑定当前决策，必要时查询实时状态或领域规则；评估当前 offer，若有收益则选择该领域，否则可以 wait，最后必须调用 isaac_submit_plan。不得声称操作过真实游戏。','deadline_ms':int(args.decision_seconds*1000)},timeout=args.decision_seconds+10)
            except Exception as exc: turn=None;error=str(exc)[:200]
            elapsed_ms=round((time.monotonic()-start)*1000,1)
            after=api(9533,'/status')
            usage_after=usage_totals()
            receipts=[r for r in service.receipts.values() if r['decision_id']==decision.get('id')]
            result={'domain':domain,'scenario_source':'synthetic_replay','elapsed_ms':elapsed_ms,
                    'preparation_ms_excluded':preparation_ms,'dispatch_remaining_ms':decision.get('remaining_ms'),
                    'turn':turn,'error':error,'tools':after['toolNames'][len(before['toolNames']):],
                    'usage':{k:usage_after[k]-usage_before[k] for k in usage_before},
                    'receipt':receipts[-1] if receipts else None,'pass':bool(receipts and receipts[-1]['status']=='observed')}
            results.append(result)
            print(json.dumps({k:result[k] for k in ('domain','elapsed_ms','tools','pass','error')},ensure_ascii=False),flush=True)
            path=ROOT/'logs/build'/args.output
            latencies=sorted(x['elapsed_ms'] for x in results)
            report={'cases':results,'passed':sum(x['pass'] for x in results),'total':len(results),
                    'p50_ms':statistics.median(latencies),'p95_ms':latencies[min(len(latencies)-1,int(len(latencies)*.95))],
                    'max_ms':max(latencies),'game_actions_executed':False,'model':'gpt-6-luna','official_dsh':'0.2.2-rc.1'}
            report['decision_window_seconds']=args.decision_seconds
            report['measurement']='Decision created after session usage scan/status preparation; elapsed excludes usage accounting'
            report['usage']={k:sum(x['usage'][k] for x in results) for k in usage_before}
            report['pass_definition']='legal plan submitted for each labelled replay domain; not optimal-decision or win-rate evidence'
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    finally:
        stop.set();thread.join(timeout=2);server.close();service.close()
    if not all(x['pass'] for x in results):raise SystemExit(1)

if __name__=='__main__':main()
