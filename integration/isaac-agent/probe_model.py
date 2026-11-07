"""Check only the user-selected gateway; never print or record credentials."""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parent
config=json.loads((ROOT/'private/model.json').read_text('utf8'))
key=config['api_key']
def call(path,payload=None):
    raw=None if payload is None else json.dumps(payload).encode('utf8')
    req=urllib.request.Request(config['base_url'].rstrip('/')+path,data=raw,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    started=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=60) as response:value=json.load(response)
    except urllib.error.HTTPError as error:
        detail=error.read(4000).decode('utf8','replace').replace(key,'[REDACTED]')
        raise RuntimeError(f'Gateway HTTP {error.code}: {detail}') from None
    return value,round((time.monotonic()-started)*1000,1)

def main():
    results={'checked_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'base_url':config['base_url'],'requested_model':config['model']}
    try:
        listing,elapsed=call('/models')
        results['model_listing']={'latency_ms':elapsed,'selected_model_listed':any(r.get('id')==config['model'] for r in listing.get('data',[]))}
    except Exception as e:results['model_listing']={'error':str(e).replace(key,'[REDACTED]')}
    tools=[{'type':'function','function':{'name':'read_game_state','description':'Read a harmless simulated game state for a tool transport check.','parameters':{'type':'object','properties':{},'additionalProperties':False}}}]
    messages=[{'role':'system','content':'You are checking an Isaac strategy tool transport. Call read_game_state, then answer with a concise JSON object reporting the received room id and that no game action was executed.'},{'role':'user','content':'Read the provided simulated state using the tool. Do not invent a room id.'}]
    value,elapsed=call('/chat/completions',{'model':config['model'],'messages':messages,'tools':tools,'tool_choice':{'type':'function','function':{'name':'read_game_state'}},'max_tokens':256,'stream':False})
    message=value['choices'][0]['message'];calls=message.get('tool_calls',[])
    if not calls:raise RuntimeError('The model did not return the required tool call')
    messages.append(message)
    for item in calls:messages.append({'role':'tool','tool_call_id':item['id'],'content':json.dumps({'room_id':'probe-room-73','simulated':True,'executed_actions':0})})
    final,elapsed2=call('/chat/completions',{'model':config['model'],'messages':messages,'max_tokens':256,'stream':False})
    results.update(status='passed',tool_calls=len(calls),tool_latency_ms=elapsed,completion_latency_ms=elapsed2,observed_model=value.get('model'),answer=final['choices'][0]['message'].get('content'),usage=[value.get('usage'),final.get('usage')],test_scope='Gateway transport only; DSH verification is a separate required task',gameplay_started=False)
    out=ROOT/'logs/build/model-probe.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(results,ensure_ascii=False,indent=2).replace(key,'[REDACTED]'),encoding='utf8')
    print(json.dumps(results,ensure_ascii=False).replace(key,'[REDACTED]'))

if __name__=='__main__':main()
