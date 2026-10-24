"""Render a selected registered voice through an existing native ComfyUI installation."""
import argparse
import copy
import json
from pathlib import Path
import time
import uuid
import requests

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8188')
    parser.add_argument('--voice',choices=['v'+str(i).zfill(2) for i in range(1,11)],default='v01')
    parser.add_argument('--engine',choices=['soulx','moss','firered'],default='soulx')
    parser.add_argument('--text',required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/voices/custom.flac')
    parser.add_argument('--seed',type=int,default=20261026)
    args=parser.parse_args()
    if not args.text.strip():parser.error('--text must contain speech')
    profile=next(item for item in json.loads((ROOT/'assets/voices/female-a-v1/references.json').read_text(encoding='utf-8'))['profiles'] if item['id']==args.voice)
    template=ROOT/('configs/voices/workflows/benchmark-'+args.engine+'-v01.api.json')
    graph=copy.deepcopy(json.loads(template.read_text(encoding='utf-8')))
    session=requests.Session();session.trust_env=False
    base=args.base_url.rstrip('/')
    subfolder='female-a-voice-selection-20261025'
    with (ROOT/profile['reference']).open('rb') as stream:
        response=session.post(base+'/upload/image',files={'image':(args.voice+'.wav',stream,'audio/wav')},data={'type':'input','subfolder':subfolder,'overwrite':'true'},timeout=60)
    response.raise_for_status();uploaded=response.json()
    graph['1']['inputs']['audio']=uploaded.get('subfolder',subfolder)+'/'+uploaded['name']
    dialogue='[S1] '+args.text.strip()
    if args.engine=='soulx':
        graph['3']['inputs']['dialogue_script']=dialogue
        graph['3']['inputs']['json_config']=json.dumps({'speakers':{'S1':{'prompt_audio':'S1_prompt_audio','prompt_text':profile['reference_text']}},'dialogue_script':dialogue},ensure_ascii=False)
        graph['4']['inputs']['seed']=args.seed
    else:
        graph['2']['inputs'].update(dialogue_text=dialogue,S1_text=profile['reference_text'],seed=args.seed)
    graph['8']['inputs']['filename_prefix']='female-a-custom/'+args.engine+'-'+args.voice
    response=session.post(base+'/prompt',json={'prompt':graph,'client_id':uuid.uuid4().hex},timeout=30)
    response.raise_for_status();prompt_id=response.json()['prompt_id'];print('Submitted '+prompt_id,flush=True)
    deadline=time.monotonic()+1200
    while time.monotonic()<deadline:
        response=session.get(base+'/history/'+prompt_id,timeout=30);response.raise_for_status()
        history=response.json().get(prompt_id)
        if history:
            if history.get('status',{}).get('status_str')=='error':raise RuntimeError(json.dumps(history['status'],ensure_ascii=False))
            output=history.get('outputs',{}).get('8',{}).get('audio',[])
            if not output:raise RuntimeError('Completed without a saved audio output')
            response=session.get(base+'/view',params=output[0],timeout=60);response.raise_for_status()
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(response.content)
            args.output.with_suffix('.api.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('Saved complete natural-duration audio: '+str(args.output));return
        time.sleep(3)
    raise TimeoutError('Own render exceeded twenty minutes; inspect its prompt_id before resubmitting. Other queued tasks were not canceled.')


if __name__=='__main__':main()
