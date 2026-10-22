"""Prepare a short upstream demonstration avatar; does not synthesize speech."""
from pathlib import Path
import datetime,json,subprocess,sys,shutil
from runtime_environment import ROOT,environment

def main():
    env=environment()
    for name in ('motion-bank-result.json','vertical-avatar.result.json'):
        result=ROOT/'.setup'/name
        if result.exists() and json.loads(result.read_text(encoding='utf-8')).get('ok'):
            subprocess.run([sys.executable,'-X','utf8','-B',str(ROOT/'deployment/select_portrait.py')],cwd=ROOT,env=env,check=True)
            return
    if (ROOT/'configs/vertical/avatar-profile.json').exists():
        subprocess.run([sys.executable,'-X','utf8','-B',str(ROOT/'scripts/prepare_vertical_avatar.py')],cwd=ROOT,env=env,check=True)
        return
    gpu=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True)
    if int(gpu.splitlines()[0])<12*1024:raise RuntimeError('Avatar preparation needs 12 GiB free GPU memory; existing applications are left running.')
    live=ROOT/'src/LiveTalking'
    python=ROOT/'runtime/livetalking/Scripts/python.exe'
    ffmpeg=next((ROOT/'tools/ffmpeg').rglob('ffmpeg.exe'))
    source=ROOT/'assets/custom/student-dorm.png'
    if source.exists():
        avatar_id='student_dorm_v1';target=source.parent/'preprocess/00000000.png'
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    else:
        avatar_id='demo_musetalk_v15';source=ROOT/'assets/demo/yongen.mp4';target=ROOT/'assets/demo/avatar_input.mp4'
        subprocess.run([str(ffmpeg),'-hide_banner','-y','-i',str(source),'-t','3','-vf',"scale=-2:'min(ih,720)',fps=25",'-an','-c:v','libx264','-preset','fast','-crf','18',str(target)],env=env,cwd=ROOT,check=True)
    subprocess.run([str(python),'-X','utf8','-B','-m','avatars.musetalk.genavatar','--file',str(target),'--avatar_id',avatar_id,'--version','v15'],env=env,cwd=live,check=True)
    avatar=live/'data/avatars'/avatar_id
    required=['coords.pkl','mask_coords.pkl','latents.pt','avator_info.json']
    missing=[name for name in required if not (avatar/name).exists()]
    frames=len(list((avatar/'full_imgs').glob('*.png')));masks=len(list((avatar/'mask').glob('*.png')))
    if missing or frames<1 or frames!=masks:raise RuntimeError(f'Incomplete avatar preparation: {missing}, frames={frames}, masks={masks}')
    config_path=ROOT/'configs/livetalking.yaml';config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    config['avatar_id']=avatar_id;config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    result={'ok':True,'at':datetime.datetime.now().astimezone().isoformat(),'avatar_id':avatar_id,'directory':str(avatar),'frames':frames,'masks':masks,'source':str(source),'preprocessing_only':True,'talking_head_inference_run':False,'tts_synthesis_run':False}
    (ROOT/'.setup/avatar.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
