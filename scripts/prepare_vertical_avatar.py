"""Prepare a multi-frame MuseTalk avatar from the reviewed local motion video."""
from pathlib import Path
import argparse, datetime, hashlib, json, os, sys
ROOT=Path(__file__).resolve().parents[1]
repo=ROOT/'src/LiveTalking';os.chdir(repo);sys.path.insert(0,str(repo))
os.environ['AVATAR_GPU_ISOLATION']='0';os.environ['AVATAR_GPU_WORKER_CHILD']='1'
import cv2, numpy as np, torch
if os.environ.get('AVATAR_PREP_MAX_GPU_GIB'):
    budget=float(os.environ['AVATAR_PREP_MAX_GPU_GIB'])*1024**3
    torch.cuda.set_per_process_memory_fraction(budget/torch.cuda.get_device_properties(0).total_memory)
from scipy.ndimage import median_filter
from avatars.musetalk import genavatar
from avatars.musetalk.utils import native_landmarks
from avatars.musetalk.utils.preprocessing import fa
from vertical_face_material import compact_mask,native_detections

torch.set_num_threads(1);torch.set_num_interop_threads(1)
parser=argparse.ArgumentParser();parser.add_argument('--profile',default='configs/vertical/avatar-profile.json');args=parser.parse_args()
profile_path=(ROOT/args.profile).resolve();profile_path.relative_to(ROOT)
profile=json.loads(profile_path.read_text(encoding='utf-8'))
if profile.get('preprocess_vae_only'):
    from avatars.musetalk.models.vae import VAE
    genavatar.load_all_model=lambda **kwargs:(VAE(model_path='models/sd-vae',use_float16=True),None,None)
source=(ROOT/profile['source_video']).resolve();source.relative_to(ROOT)
if not source.exists():raise RuntimeError('Reviewed vertical motion source is missing')
capture=cv2.VideoCapture(os.path.relpath(source))
count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT));width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT));fps=capture.get(cv2.CAP_PROP_FPS);capture.release()
if count<150 or (width,height)!=(720,1280) or abs(fps-25)>.1:raise RuntimeError('Expected a real multi-frame 720x1280 / 25 FPS source')
avatar_id=profile['avatar_id'];avatar=repo/'data/avatars'/avatar_id
if avatar.exists():raise RuntimeError('Preserve existing preparation; use a new avatar ID for another revision')
landmark_cache={};original_landmarks=native_landmarks.face_landmarks
if profile.get('landmark_mode')=='tracked_full_resolution':
    from tracked_landmarks import TrackedLandmarks
    original_landmarks=TrackedLandmarks(native_landmarks)
def cached_landmarks(rgb):
    key=hashlib.blake2b(rgb,digest_size=16).digest()
    if key not in landmark_cache:landmark_cache[key]=original_landmarks(rgb)
    return landmark_cache[key]
native_landmarks.face_landmarks=cached_landmarks
fa.get_detections_for_batch=lambda batch:native_detections(batch,cached_landmarks)
original_boxes=genavatar.get_landmark_and_bbox
def smooth_boxes(files,shift):
    boxes,frames=original_boxes(files,shift)
    values=np.asarray(boxes,dtype=np.int32)
    if np.any(values[:,2]<=values[:,0]) or np.any(values[:,3]<=values[:,1]):raise RuntimeError('A source frame has no usable face')
    values=median_filter(values,size=(5,1),mode='nearest')
    boxes_output=ROOT/'outputs/vertical/review'/('prepared-boxes-'+avatar_id+'.json')
    boxes_output.parent.mkdir(parents=True,exist_ok=True)
    boxes_output.write_text(json.dumps(values.tolist()),encoding='utf-8')
    return values.tolist(),frames
genavatar.get_landmark_and_bbox=smooth_boxes
original_mask=genavatar.get_image_prepare_material
def material(frame,box,**kwargs):
    mask,crop=original_mask(frame,box,**kwargs)
    if profile['mask_mode']=='compact':
        landmarks=cached_landmarks(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        if len(landmarks)!=1:raise RuntimeError('Lost the single face during material preparation')
        mask=compact_mask(mask,crop,box,landmarks[0])
    return mask,crop
genavatar.get_image_prepare_material=material
def progress(percent):
    state={'stage':'prepare_vertical_avatar','percent':percent,'avatar_id':avatar_id}
    (ROOT/'.setup/vertical-preparation-progress.json').write_text(json.dumps(state),encoding='utf-8')
    print(json.dumps(state),flush=True)
with torch.inference_mode():
    genavatar.generate_avatar(os.path.relpath(source),avatar_id,bbox_shift=profile['bbox_shift'],extra_margin=10,parsing_mode='jaw',version='v15',progress_callback=progress)
frames=list((avatar/'full_imgs').glob('*.png'));masks=list((avatar/'mask').glob('*.png'))
if len(frames)!=count or len(masks)!=count:raise RuntimeError('Not every motion frame was prepared')
if profile.get('motion_index_source'):
    motion_index=json.loads((ROOT/profile['motion_index_source']).read_text(encoding='utf-8'))
    expected=0
    for clip in motion_index['clips']:
        if clip['start_frame']!=expected:raise RuntimeError('Motion map is not contiguous')
        expected+=clip['frames']
    if expected!=count:raise RuntimeError('Motion map and prepared frames disagree')
    (avatar/'motion-index.json').write_text(json.dumps(motion_index,ensure_ascii=False,indent=2),encoding='utf-8')
if profile.get('activate',True):
    config_path=ROOT/'configs/livetalking.yaml';config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    backup=ROOT/'.setup/livetalking-before-vertical.json'
    if not backup.exists():backup.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    config['avatar_id']=avatar_id;config['batch_size']=8
    config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
result={'ok':True,'at':datetime.datetime.now().astimezone().isoformat(),'avatar_id':avatar_id,'frames':len(frames),'masks':len(masks),'source':str(source),'width':width,'height':height,'fps':fps,'bbox_shift':profile['bbox_shift'],'mask_mode':profile['mask_mode'],'bbox_smoothing_frames':5,'preprocessing_only':True,'talking_head_inference_run':False,'tts_synthesis_run':False}
if profile.get('activate',True):
    (ROOT/'.setup/avatar.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'.setup/vertical-avatar.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
else:
    results=ROOT/'.setup/vertical-material-prepared';results.mkdir(exist_ok=True)
    (results/(avatar_id+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
