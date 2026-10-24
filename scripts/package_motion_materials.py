"""Package only reviewed media and reproducible prompts, excluding all credentials."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
catalog=json.loads((ROOT/'configs/vertical/materials/catalog.json').read_text(encoding='utf-8'))
reviews=json.loads((ROOT/'configs/vertical/materials/reviews.json').read_text(encoding='utf-8'))
if len(catalog['items'])<48 or any(not reviews.get(i['id'],{}).get('accepted') for i in catalog['items']):raise RuntimeError('Unreviewed clips cannot enter the delivery package')
files=['configs/characters/female-a.json','docs/CHARACTERS.md','assets/vertical/student-dorm-720x1280.png','output/imagegen/student-dorm.png','output/imagegen/student-dorm-vertical-reference.png','configs/vertical/materials/catalog.json','configs/vertical/materials/reviews.json','configs/vertical/materials/motion-index.json','README.md','README.zh-CN.md','docs/USAGE.md','docs/MATERIALS.md']
poses=json.loads((ROOT/'output/imagegen/motion-poses/delivery.json').read_text(encoding='utf-8'))
if not poses.get('ok') or poses['count']<24:raise RuntimeError('Reviewed independent pose photographs are missing')
files.extend(['output/imagegen/motion-poses/manifest.json','output/imagegen/motion-poses/reviews.json','output/imagegen/motion-poses/delivery.json'])
for pose in poses['items']:
    native=ROOT/pose['native']
    if hashlib.sha256(native.read_bytes()).hexdigest()!=pose['sha256']:raise RuntimeError('Pose image changed after review')
    files.extend([pose['native'],pose['delivery'],pose['prompt']])
for base in ('idle_a','idle_b'):
    files.extend([f'outputs/vertical/source/{base}.mp4',f'configs/vertical/{base}_export.api.json',f'configs/vertical/{base}.prompt.txt'])
manifest=[]
for item in catalog['items']:
    files.extend([item['source_video'],item['workflow'],item['prompt'],'configs/vertical/materials/'+item['id']+'.history.json','outputs/vertical/materials/posters/'+item['id']+'.jpg','outputs/vertical/materials/keyframes/'+item['id']+'.png','outputs/vertical/materials/review/'+item['id']+'.jpg'])
    for detail in ('-hands.jpg','-head.jpg'):
        evidence='outputs/vertical/materials/review/'+item['id']+detail
        if (ROOT/evidence).is_file():files.append(evidence)
    path=ROOT/item['source_video']
    manifest.append({'id':item['id'],'title':item['title'],'category':item['category_label'],'seconds':item['duration_seconds'],'video':item['source_video'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
if len({m['sha256'] for m in manifest})!=len(manifest):raise RuntimeError('Duplicate encoded video found; do not count copies as new material')
for review in reviews.values():
    evidence=review.get('evidence','')
    if evidence and not review.get('accepted') and (ROOT/evidence).is_file():files.append(evidence)
files=list(dict.fromkeys(files))
path=ROOT/'outputs/vertical/materials/delivery-manifest.json';path.write_text(json.dumps({'character_id':'female-a','archive_label':'女A','character_name':'林知夏','scene_id':'female-a-daylight-dorm','clips':len(manifest),'seconds':sum(m['seconds'] for m in manifest),'reference_baseline_clips':2,'reference_baseline_seconds':16,'new_material_multiplier':len(manifest)/2,'independent_pose_images':poses['count'],'pose_manifest':'output/imagegen/motion-poses/delivery.json','items':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
files.append(path.relative_to(ROOT).as_posix())
archive=ROOT/'outputs/vertical/portrait-motion-materials.zip'
with zipfile.ZipFile(archive,'w',allowZip64=True) as bundle:
 for relative in files:
  source=(ROOT/relative).resolve();source.relative_to(ROOT)
  if not source.is_file():raise RuntimeError('Delivery material missing: '+relative)
  if source.name in ('channel.env','.env') or source.suffix in ('.key',):raise RuntimeError('Credential exclusion guard')
  bundle.write(source,relative,compress_type=zipfile.ZIP_DEFLATED if source.suffix in ('.json','.txt','.md') else zipfile.ZIP_STORED)
result={'ok':True,'archive':str(archive),'bytes':archive.stat().st_size,'entries':len(files),'clips':len(manifest),'seconds':sum(m['seconds'] for m in manifest),'multiplier':len(manifest)/2,'independent_pose_images':poses['count']}
(ROOT/'.setup/material-package-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
