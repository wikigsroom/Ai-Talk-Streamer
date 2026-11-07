"""Real DSH turn against an explicitly labelled synthetic scenario (no game actions)."""
from pathlib import Path
import json
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parent

def api(port,path,body=None,timeout=35):
    from start_dsh import bridge_token
    token=bridge_token()
    data=json.dumps(body,ensure_ascii=False).encode('utf8') if body is not None else None
    request=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=data,
        headers={'Content-Type':'application/json','X-Isaac-Token':token})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        detail=error.read(4096).decode('utf8','replace').replace(token,'[PRIVATE]')
        from start_dsh import private_config
        detail=detail.replace(private_config()['api_key'],'[PRIVATE]')
        raise RuntimeError(f'Local API HTTP {error.code}: {detail[:300]}') from None

def main():
    api(9533,'/control',{'automatic':False})
    api(9532,'/control',{'enabled':False})
    api(9532,'/control',{'enabled':True,'live':False})
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        d=api(9532,'/decision')
        if d.get('pending'):break
        time.sleep(.05)
    before=api(9533,'/status')
    result=api(9533,'/run',{'prompt':'当前是明确标注的离线回放。先用 isaac_get_decision 查看当前场景，选择有益的拾取 offer，并用 isaac_submit_plan 提交。不要只回答文字。','deadline_ms':22000})
    after=api(9533,'/status');status=api(9532,'/status')
    receipts=[r for r in status['recent_receipts'] if r['decision_id']==d['id']]
    value={'test':'actual_official_DSH_with_LAN_gpt6luna','source':'synthetic_replay_no_game',
           'official_dsh_ready':after['ready'],'version':after['dshVersion'],'model':after['model'],'provider':after['provider'],
           'result':result,'tools_this_turn':after['toolNames'][len(before['toolNames']):],
           'receipts':receipts,'pass':bool(receipts and receipts[-1]['status']=='observed'),
           'error':after.get('lastError'),'frame_copy_p95_ms':status['state_copy_p95_ms']}
    (ROOT/'logs/build/dsh-model-verification.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(value,ensure_ascii=False,indent=2))
    if not value['pass']:raise SystemExit(1)

if __name__=='__main__':main()
