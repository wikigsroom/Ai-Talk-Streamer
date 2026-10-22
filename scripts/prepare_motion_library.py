"""Prepare currently selected reviewed takes, including later replacements."""
from pathlib import Path
import argparse,datetime,json,os,subprocess,sys,time,traceback
from runtime_environment import environment
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--ids',nargs='*');args=parser.parse_args()
path=ROOT/'.setup/material-preparation-progress.json'
public=ROOT/'outputs/vertical/materials/preparation-progress.json'
state={'status':'running','pid':os.getpid(),'items':{}}

def write_json(target,value):
    temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(target)

def save():
    state['prepared']=sum(i.get('status')=='prepared' for i in state['items'].values())
    state['updated_at']=datetime.datetime.now().astimezone().isoformat()
    write_json(path,state);write_json(public,state)

try:
    while True:
        catalog=json.loads((ROOT/'configs/vertical/materials/catalog.json').read_text(encoding='utf-8'))
        reviews=json.loads((ROOT/'configs/vertical/materials/reviews.json').read_text(encoding='utf-8'))
        items=[i for i in catalog['items'] if not args.ids or i['id'] in args.ids]
        if not items:raise RuntimeError('No selected material IDs')
        state['target']=len(items);state['items']={};eligible=[]
        for item in items:
            name=item['id'];avatar='mat_'+name
            result=ROOT/'.setup/vertical-material-prepared'/(avatar+'.json')
            reviewed=reviews.get(name,{}).get('accepted',False)
            prepared=result.exists() and json.loads(result.read_text(encoding='utf-8')).get('ok')
            if reviewed and prepared:status='prepared'
            elif not (ROOT/item['source_video']).exists():status='waiting_for_generation'
            elif not reviewed:status='waiting_for_review'
            else:status='ready_to_prepare';eligible.append(item)
            state['items'][name]={'status':status,'avatar_id':avatar}
        if all(i['status']=='prepared' for i in state['items'].values()):
            state.update(status='complete',current=None,waiting_for_generation=False);save();break
        if not eligible:
            state.update(current=None,waiting_for_generation=True);save();time.sleep(5);continue
        item=eligible[0];name=item['id'];avatar='mat_'+name
        state.update(current=name,waiting_for_generation=False)
        state['items'][name]={'status':'preparing','avatar_id':avatar};save()
        profile={'avatar_id':avatar,'source_video':item['source_video'],'bbox_shift':4,'mask_mode':'compact','landmark_mode':'tracked_full_resolution','preprocess_vae_only':True,'activate':False}
        profile_path=ROOT/'configs/vertical/materials'/(name+'.prepare.json');write_json(profile_path,profile)
        env=environment();env['AVATAR_PREP_MAX_GPU_GIB']='3'
        command=[str(ROOT/'runtime/livetalking/Scripts/python.exe'),'-X','utf8','-B',str(ROOT/'scripts/prepare_vertical_avatar.py'),'--profile',str(profile_path.relative_to(ROOT))]
        run=subprocess.run(command,cwd=ROOT,env=env)
        result=ROOT/'.setup/vertical-material-prepared'/(avatar+'.json')
        if run.returncode or not result.exists():raise RuntimeError('Material preparation failed: '+name)
        print('PREPARED REVIEWED TAKE '+name,flush=True)
except Exception:
    state.update(status='failed',error=traceback.format_exc());save();print(state['error'],flush=True);raise SystemExit(1)
