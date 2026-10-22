from pathlib import Path
import datetime,json,pickle
ROOT=Path(__file__).resolve().parents[1]
avatar_id='student_dorm_v1'
for result_name in ('motion-bank-result.json','vertical-avatar.result.json'):
    path=ROOT/'.setup'/result_name
    if path.exists():
        ready=json.loads(path.read_text(encoding='utf-8'))
        if ready.get('ok'):
            avatar_id=ready['avatar_id'];break
avatar=ROOT/'src/LiveTalking/data/avatars'/avatar_id
for file in ('latents.pt','coords.pkl','mask_coords.pkl','avator_info.json'):
    if not (avatar/file).exists():raise RuntimeError('Missing selected avatar file: '+file)
images=list((avatar/'full_imgs').glob('*.png'));masks=list((avatar/'mask').glob('*.png'))
if not images or len(images)!=len(masks):raise RuntimeError('Selected motion avatar has missing frames or masks')
if avatar_id!='student_dorm_v1' and len(images)<150:raise RuntimeError('A vertical motion avatar must retain its multi-frame source')
config_path=ROOT/'configs/livetalking.yaml';config=json.loads(config_path.read_text(encoding='utf-8-sig'))
config['avatar_id']=avatar_id;config['batch_size']=8;config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
result={'ok':True,'at':datetime.datetime.now().astimezone().isoformat(),'avatar_id':avatar_id,'directory':str(avatar),'frames':len(images),'masks':len(masks),'source':str(ROOT/'assets/custom/student-dorm.png'),'preprocessing_only':True,'talking_head_inference_run':False,'tts_synthesis_run':False,'selection':'User selected original daytime image'}
(ROOT/'.setup/avatar.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
