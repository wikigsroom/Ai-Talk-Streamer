"""Collect final public runtime evidence without channel credentials."""
from pathlib import Path
import datetime,hashlib,json,platform,subprocess
import psutil,requests
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
client=requests.Session();client.trust_env=False
state=client.get('http://127.0.0.1:8010/api/studio/status',timeout=15).json()
material=client.get('http://127.0.0.1:8010/api/studio/materials',timeout=15).json()
motion=client.get('http://127.0.0.1:8010/api/studio/motion',timeout=15).json()
poses=client.get('http://127.0.0.1:8010/api/studio/poses',timeout=15).json()
bank=json.loads((ROOT/'.setup/motion-bank-result.json').read_text(encoding='utf-8'))
public_state={k:v for k,v in state.items() if k!='channel'}
public_state['cloud_llm_configured']=state.get('channel',{}).get('configured',False)
result={'at':datetime.datetime.now().astimezone().isoformat(),'host':platform.node(),'os':platform.platform(),'ram_gib':round(psutil.virtual_memory().total/1024**3,2),'ram_used_gib':round((psutil.virtual_memory().total-psutil.virtual_memory().available)/1024**3,2),'runtime_platform':'native_windows','studio':public_state,'material_count':material['count'],'material_seconds':material['seconds'],'motion_clips':len(motion.get('clips',[])),'bank':bank}
result['gpu']=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,memory.used,driver_version','--format=csv,noheader'],text=True,timeout=15).strip()
result['assets']={}
active=next((ROOT/'src/LiveTalking/data/avatars'/state['avatar_id']/'full_imgs').glob('*.png'))
for path in [ROOT/'output/imagegen/student-dorm.png',ROOT/'assets/vertical/student-dorm-720x1280.png',active]:
 with Image.open(path) as original:
  image=original.convert('RGB')
  result['assets'][path.relative_to(ROOT).as_posix()]={'size':image.size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rgb_sha256':hashlib.sha256(image.tobytes()).hexdigest()}
result['visual_quality_asserted_by_this_probe']=False
result['independent_pose_images']=poses['count']
result['ok']=platform.system()=='Windows' and state['ready'] and state['tts_ready'] and state['avatar_id']=='student_dorm_motion_bank_v3' and state['viewers']>=1 and material['count']>=48 and material['seconds']>=384 and len(motion.get('clips',[]))>=50 and bank['frames']>=10000 and bank['new_material_ratio']>=20 and poses['count']>=24
(ROOT/'.setup/delivery-snapshot.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
raise SystemExit(0 if result['ok'] else 1)
