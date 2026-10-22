"""Render controlled mouth/crop comparisons before choosing the live profile."""
from pathlib import Path
import datetime, json, os, sys
ROOT=Path(__file__).resolve().parents[1]
repo=ROOT/'src/LiveTalking';os.chdir(repo);sys.path.insert(0,str(repo))
os.environ['AVATAR_GPU_ISOLATION']='0';os.environ['AVATAR_GPU_WORKER_CHILD']='1'
import cv2,numpy as np,soundfile as sf,torch
from scipy.signal import resample_poly
from math import gcd
from PIL import Image,ImageDraw,ImageFont
from avatars.musetalk_avatar import load_model,MuseReal
from avatars.audio_features.whisper import WhisperASR
from avatars.musetalk.utils.preprocessing import get_landmark_and_bbox,fa
from avatars.musetalk.genavatar import FaceParsing
from avatars.musetalk.utils.blending import get_image_prepare_material
from avatars.musetalk.myutil import get_image_blending
from avatars.musetalk.utils import native_landmarks
from vertical_face_material import compact_mask,native_detections

torch.set_num_threads(1);torch.set_num_interop_threads(1)
OUT=ROOT/'outputs/vertical/review';OUT.mkdir(parents=True,exist_ok=True)
source=ROOT/'assets/vertical/student-dorm-720x1280.png'
frame=cv2.imread(os.path.relpath(source))
landmarks=native_landmarks.face_landmarks(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))[0]
native_landmarks.face_landmarks=lambda image:[landmarks]
fa.get_detections_for_batch=lambda batch:native_detections(batch,native_landmarks.face_landmarks)
model=load_model();vae,unet,pe,timesteps,audio_processor=model
wave,rate=sf.read(ROOT/'outputs/验收/tts_zh.wav',dtype='float32')
if wave.ndim>1:wave=wave.mean(axis=1)
if rate!=16000:wave=resample_poly(wave,16000//gcd(16000,rate),rate//gcd(16000,rate)).astype(np.float32)
sample_seconds=[.8,1.3,1.8,2.3,2.8,3.3]
variants=[];pictures=[]
with torch.inference_mode():
    features=audio_processor.audio2feat(wave)
    slicer=WhisperASR.__new__(WhisperASR)
    chunks=[slicer._feature2chunks(features,1,audio_feat_win=[2,3],start=round(t*25),feature_idx_multiplier=2)[0] for t in sample_seconds]
    chunks+=chunks[-1:]*(8-len(chunks))
    fp=FaceParsing(left_cheek_width=90,right_cheek_width=90)
    for shift in (-4,0,4):
        boxes,_=get_landmark_and_bbox([os.path.relpath(source)],shift)
        x1,y1,x2,y2=map(int,boxes[0]);y2=min(frame.shape[0],y2+10);box=(x1,y1,x2,y2)
        crop=cv2.resize(frame[y1:y2,x1:x2],(256,256),interpolation=cv2.INTER_LANCZOS4)
        latent=vae.get_latents_for_unet(crop)
        renderer=MuseReal.__new__(MuseReal)
        renderer.vae,renderer.unet,renderer.pe,renderer.timesteps,renderer.audio_processor=model
        renderer.input_latent_list_cycle=[latent];renderer.batch_size=8
        predicted=renderer.inference_batch(0,chunks)
        mask,crop_box=get_image_prepare_material(frame,box,fp=fp,mode='jaw')
        for mode in ('jaw','compact'):
            chosen_mask=mask if mode=='jaw' else compact_mask(mask,crop_box,box,landmarks)
            row=[]
            for prediction in predicted[:len(sample_seconds)]:
                face=cv2.resize(prediction.astype(np.uint8),(x2-x1,y2-y1))
                output=get_image_blending(frame.copy(),face,box,cv2.cvtColor(chosen_mask,cv2.COLOR_GRAY2BGR),crop_box)
                row.append(Image.fromarray(cv2.cvtColor(output,cv2.COLOR_BGR2RGB)))
            variants.append({'bbox_shift':shift,'mask':mode,'bbox':list(box)})
            pictures.append(row)
            cv2.imwrite(os.path.relpath(OUT/f'mask-{shift}-{mode}.png'),chosen_mask)
face_points=np.asarray(landmarks['chin']+landmarks['left_eyebrow']+landmarks['right_eyebrow'])
left=int(face_points[:,0].min())-20;right=int(face_points[:,0].max())+20
top=int(face_points[:,1].min())-35;bottom=int(face_points[:,1].max())+20
view=(left,top,right,bottom);tile_w,tile_h=184,244
sheet=Image.new('RGB',(7*tile_w,6*tile_h),'#edf0f3');draw=ImageDraw.Draw(sheet)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',15)
original=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
for row,t in enumerate(sample_seconds):
    for col in range(7):
        im=original if col==0 else pictures[col-1][row]
        thumb=im.crop(view);thumb.thumbnail((174,211),Image.Resampling.LANCZOS)
        x,y=col*tile_w,row*tile_h
        sheet.paste(thumb,(x+(tile_w-thumb.width)//2,y+27))
        label='Original' if col==0 else f'{variants[col-1]["bbox_shift"]:+d} {variants[col-1]["mask"]}'
        draw.text((x+6,y+5),f'{label} / {t:.1f}s',font=font,fill='#172437')
sheet.save(OUT/'face-comparison.jpg',quality=96)
record={'at':datetime.datetime.now().astimezone().isoformat(),'source':str(source),'audio':'outputs/验收/tts_zh.wav','sample_seconds':sample_seconds,'variants':variants,'selected':None,'note':'Controlled comparison only; a choice requires visual inspection.'}
(OUT/'face-comparison.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'ok':True,'variants':variants,'contact_sheet':str(OUT/'face-comparison.jpg')}),flush=True)
