"""Encode completed replacement jobs; visual acceptance is always separate."""
from pathlib import Path
import json,subprocess,sys
from urllib.request import build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'configs/vertical/materials'
catalog=json.loads((folder/'retry-catalog.json').read_text(encoding='utf-8'))
opener=build_opener(ProxyHandler({}));results=[]
for mid,item in catalog.items():
    if item.get('experimental'):
        results.append({'id':mid,'status':'experimental_not_in_delivery'})
        continue
    encoded=folder/(mid+'.encoded.json')
    if encoded.exists() and (ROOT/item['source_video']).exists():continue
    receipt=folder/(mid+'.job.json')
    if not receipt.exists():continue
    job=json.loads(receipt.read_text(encoding='utf-8'));pid=job['prompt_id']
    with opener.open('http://127.0.0.1:8188/history/'+pid,timeout=15) as response:history=json.load(response)
    if not history:results.append({'id':mid,'status':'running_or_queued'});continue
    record=history[pid]
    (folder/(mid+'.history.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    if record.get('status',{}).get('status_str')!='success':results.append({'id':mid,'status':'render_failed'});continue
    run=subprocess.run([sys.executable,'-X','utf8','-B',str(ROOT/'scripts/encode_material_take.py'),mid],cwd=ROOT)
    results.append({'id':mid,'status':'generated_awaiting_review' if run.returncode==0 else 'encode_failed'})
print(json.dumps({'results':results},ensure_ascii=False),flush=True)
