"""Assemble reviewed prepared clips without loading the entire image bank into RAM."""
from pathlib import Path
import datetime,hashlib,json,os,pickle,subprocess,torch
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT/'src/LiveTalking';AVATARS=REPO/'data/avatars'
catalog=json.loads((ROOT/'configs/vertical/materials/catalog.json').read_text(encoding='utf-8'))
reviews=json.loads((ROOT/'configs/vertical/materials/reviews.json').read_text(encoding='utf-8'))
items=catalog['items']
if len(items)<48 or any(not reviews.get(i['id'],{}).get('accepted') for i in items):raise RuntimeError('All 48 new clips must pass visual review before activation')
avatar_id='student_dorm_motion_bank_v3';target=AVATARS/avatar_id
if target.exists():raise RuntimeError('Preserve the existing bank; inspect it before another assembly')
sources=[('student_dorm_vertical_v2',None)]+[('mat_'+i['id'],i) for i in items]
for folder,item in sources:
 if not (AVATARS/folder/'latents.pt').exists():raise RuntimeError('A clip has not been prepared: '+folder)
target.mkdir();(target/'full_imgs').mkdir();(target/'mask').mkdir()
latents=[];coords=[];mask_coords=[];clips=[];offset=0
for folder,item in sources:
 source=AVATARS/folder
 images=sorted((source/'full_imgs').glob('*.png'));masks=sorted((source/'mask').glob('*.png'))
 with (source/'coords.pkl').open('rb') as stream:boxes=pickle.load(stream)
 with (source/'mask_coords.pkl').open('rb') as stream:mask_boxes=pickle.load(stream)
 values=torch.load(source/'latents.pt',map_location='cpu',weights_only=True)
 expected=400 if item is None else 200
 if not len(images)==len(masks)==len(boxes)==len(mask_boxes)==len(values)==expected:raise RuntimeError('Inconsistent prepared material: '+folder)
 if item is not None:
  posters=ROOT/'outputs/vertical/materials/posters';posters.mkdir(exist_ok=True)
  keyframes=ROOT/'outputs/vertical/materials/keyframes';keyframes.mkdir(exist_ok=True)
  with Image.open(images[75]) as picture:
   pose=picture.convert('RGB');pose.save(keyframes/(item['id']+'.png'))
   poster=pose.copy();poster.thumbnail((180,320),Image.Resampling.LANCZOS);poster.save(posters/(item['id']+'.jpg'),quality=92)
 for index,(image,mask) in enumerate(zip(images,masks)):
  # Native NTFS hard links retain original files while avoiding another full PNG copy.
  os.link(image,target/'full_imgs'/f'{offset+index:08d}.png')
  os.link(mask,target/'mask'/f'{offset+index:08d}.png')
 coords.extend(boxes);mask_coords.extend(mask_boxes);latents.extend(values)
 if item is None:
  clips.extend([{'id':'idle_a','title':'自然呼吸与眨眼','category':'idle','start_frame':offset,'frames':200},{'id':'idle_b','title':'轻点头与倾听','category':'idle','start_frame':offset+200,'frames':200}])
 else:clips.append({'id':item['id'],'title':item['title'],'category':item['category'],'start_frame':offset,'frames':expected})
 offset+=expected
with (target/'coords.pkl').open('wb') as stream:pickle.dump(coords,stream)
with (target/'mask_coords.pkl').open('wb') as stream:pickle.dump(mask_coords,stream)
torch.save(latents,target/'latents.pt')
manifest={'avatar_id':avatar_id,'fps':25,'frames':offset,'clips':clips}
(target/'motion-index.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'configs/vertical/materials/motion-index.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(target/'avator_info.json').write_text(json.dumps({'avatar_id':avatar_id,'bbox_shift':4,'source':'reviewed local video motion library','clips':len(clips),'frames':offset},indent=2),encoding='utf-8')
ffmpeg=next((ROOT/'tools/ffmpeg').rglob('ffmpeg.exe'));ffprobe=ffmpeg.with_name('ffprobe.exe')
videos=[ROOT/'assets/vertical/idle-loop-720x1280.mp4']+[ROOT/i['source_video'] for i in items]
listing=ROOT/'configs/vertical/materials/concatenate.txt'
listing.write_text('\n'.join("file '"+str(p).replace('\\','/').replace("'","'\\''")+"'" for p in videos),encoding='utf-8')
video=ROOT/'assets/vertical/motion-library-720x1280.mp4'
subprocess.run([str(ffmpeg),'-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(video)],check=True,timeout=120)
media=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries','stream=width,height,r_frame_rate,nb_frames:format=duration','-of','json',str(video)],text=True))
if int(media['streams'][0]['nb_frames'])!=offset:raise RuntimeError('Archive video and prepared bank frame counts disagree')
config_path=ROOT/'configs/livetalking.yaml';config=json.loads(config_path.read_text(encoding='utf-8-sig'))
(ROOT/'.setup/livetalking-before-motion-bank.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
config.update(avatar_id=avatar_id,batch_size=8)
config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
result={'ok':True,'at':datetime.datetime.now().astimezone().isoformat(),'avatar_id':avatar_id,'new_clips':len(items),'new_seconds':len(items)*8,'total_clips':len(clips),'total_seconds':offset/25,'frames':offset,'new_material_ratio':len(items)/2,'total_material_ratio':len(clips)/2,'width':720,'height':1280,'fps':25,'image_cache_per_store':48,'eager_frame_loading':False,'mask_mode':'compact','bbox_shift':4,'source_video':str(video),'media':media}
asset_path=ROOT/'output/imagegen/asset-manifest.json'
if asset_path.exists():
    assets=json.loads(asset_path.read_text(encoding='utf-8'))
    assets['legacy_horizontal']={k:assets[k] for k in ('live_plate','live_sha256','crop_box','remote_upload','live_pixel_sha256') if k in assets}
    for key in assets['legacy_horizontal']:assets.pop(key,None)
    assets.update(live_plate='assets/vertical/motion-library-720x1280.mp4',live_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),live_asset_type='reviewed_video_library',active_avatar_id=avatar_id,width=720,height=1280,fps=25,new_motion_clips=len(items),total_motion_clips=len(clips),vertical_generation_manifest='output/imagegen/vertical-manifest.json')
    asset_path.write_text(json.dumps(assets,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'.setup/motion-bank-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'.setup/avatar.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
