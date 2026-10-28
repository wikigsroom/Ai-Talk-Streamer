"""Preserve the task-local failed attempt before a checkpoint resume."""
import json,time,shutil,hashlib
from pathlib import Path
R=Path('C:/dev/虚拟数字人直播');O=R/'outputs/lipsync-k01-k05-60s-20261028'
status=json.loads((O/'suite-status.json').read_text(encoding='utf-8'))
failure=json.loads((O/'K03-training/result.json').read_text(encoding='utf-8'))
if failure.get('ok') or not failure.get('timestamp'):raise RuntimeError('A genuine failed attempt record is required')
row=next(r for r in status['stages'] if r['script']=='train_feather.py' and r['status']=='failed')
dest=O/'attempts'/('K03-training-'+str(int(failure['timestamp'])));dest.mkdir(parents=True,exist_ok=True)
paths=['suite-status.json','K03-training/result.json','K03-training/resources.json','K03/training-history.json','K03/progress.json']
records=[]
for name in paths:
 p=O/name;q=dest/name;q.parent.mkdir(parents=True,exist_ok=True)
 if q.exists() and q.read_bytes()!=p.read_bytes():raise RuntimeError('An archived attempt must not be overwritten with different evidence')
 if not q.exists():shutil.copyfile(p,q)
 records.append({'path':name,'bytes':q.stat().st_size,'sha256':hashlib.sha256(q.read_bytes()).hexdigest()})
history=json.loads((O/'K03/training-history.json').read_text(encoding='utf-8'))
record={'archived_at':time.time(),'archive':dest.relative_to(O).as_posix(),'failure':failure['error'],'completed_epochs':history[-1]['epoch'],'stage_started_at':row['started_at'],'stage_finished_at':row['finished_at'],'stage_wall_seconds':row['finished_at']-row['started_at'],'wall_boundary':'suite launch boundary to child exit; includes task wrapper/publication overhead','random_state_note':'Upstream checkpoints restore model/optimizer/epoch but do not preserve all Python/NumPy/CUDA RNG states. The resumed invocation reseeds20261028; this is not bit-identical to uninterrupted training.','files':records}
target=O/'K03/training-attempts.json';previous=json.loads(target.read_text(encoding='utf-8')) if target.exists() else []
if not any(r['archive']==record['archive'] for r in previous):previous.append(record)
target.write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'archive':record['archive'],'completed_epochs':record['completed_epochs'],'stage_wall_seconds':record['stage_wall_seconds']},ensure_ascii=False),flush=True)
