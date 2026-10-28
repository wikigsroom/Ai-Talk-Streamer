"""Hash the review deliverables; reference large training/model data separately."""
import json,hashlib,datetime,os
from pathlib import Path
R=Path('C:/dev/虚拟数字人直播');O=R/'outputs/lipsync-k01-k05-60s-20261028'
ROOT_FILES={'index.html','protocol.md','report.md','report.html','README.md','viewer_server.py','review-notes.md','results.json','results.csv','input-manifest.json','verification-summary.json','setup-progress.json','environments.json','backend-import-smoke.json','model-file-inventory.json','suite-status.json','runtime-link.json','vgg-setup.json','package-size.json','benchmark-hardware.json','wav2lip-source.json','review-assets.json','atomic-progress-check.json','viewer-reload.json'}
ROOT_FILES.add('verification-reuse.json')
ROOT_FILES.update({'page-review.json','page-review-remote.json','page-review-before-fix.json','page-review-before-fix-remote.json','startup-before-fix.json','startup-after-fix.json'})
SELECTED_FOLDERS={'audio','K01','K02','K03','K04','K05','TRAIN','K03-training','K03-fit-probe','K03-native-fit-probe','K05-fit-probe','K05-resident-fit-probe','attempts'}
EXCLUDED_PARTS={'pipeline-temp','full_body_img','landmarks','test-landmarks','test-imgs'}
files=[]
def file_hash(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
 return h.hexdigest()
for p in sorted(O.rglob('*')):
 if not p.is_file():continue
 rel=p.relative_to(O);parts=set(rel.parts);name=p.name
 if parts&EXCLUDED_PARTS or name.endswith(('.tmp','.part')):continue
 keep=(len(rel.parts)==1 and (name in ROOT_FILES or p.suffix in {'.svg','.png','.jpg','.gif','.mp4'}))
 keep=keep or (rel.parts[0] in SELECTED_FOLDERS and p.suffix in {'.json','.jpg','.png','.mp4','.wav','.txt','.log'})
 keep=keep or str(rel).replace('\\','/') in {'training/audio.wav','training/provenance.json','inputs/source-motion-60s.mp4'}
 keep=keep or (rel.parts[:2]==('inputs','source-evidence') and p.suffix in {'.png','.json'})
 keep=keep or (rel.parts[:2] in {('diagnostics','k05-fit'),('diagnostics','k05-resident-fit')} and p.suffix=='.mp4')
 # Intermediate K05 output is a diagnostic, not the final bounded portrait clip.
 if name=='generated-face-composite.mp4':keep=False
 if keep:files.append({'path':rel.as_posix(),'bytes':p.stat().st_size,'sha256':file_hash(p)})
data={'generated_at':datetime.datetime.now().astimezone().isoformat(),'complete':json.loads((O/'results.json').read_text(encoding='utf-8'))['complete'],'files':files,'file_count':len(files),'bytes':sum(f['bytes'] for f in files),'excludes':['8,000-frame training image cache','model weights / optimizer checkpoints','native Python runtimes and wheel cache','intermediate LatentSync composites and temp video'],'no_archive':True,'no_pdf':True}
tmp=O/'delivery-manifest.tmp';tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,O/'delivery-manifest.json')
print(json.dumps({'complete':data['complete'],'files':data['file_count'],'bytes':data['bytes']}),flush=True)
