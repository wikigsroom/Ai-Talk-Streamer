"""Publish reviewed notes/regression evidence, then rebuild report and hashes."""
import json,shutil,subprocess,sys
from pathlib import Path
W=Path(__file__).resolve().parent;R=W.parent.parent;O=R/'outputs/lipsync-k01-k05-60s-20261028'
if not json.loads((O/'suite-status.json').read_text(encoding='utf-8')).get('complete'):raise RuntimeError('Wait for all five recordings and final assets')
for name in ['review-notes.md','atomic-progress-check.json']:
 if not (W/name).exists():raise RuntimeError('Missing reviewed evidence: '+name)
 shutil.copy2(W/name,O/name)
for name in ['page-review.json','page-review-remote.json','page-review-before-fix.json','page-review-before-fix-remote.json','startup-before-fix.json','startup-after-fix.json']:
 if not (W/name).exists():continue
 if name in {'page-review.json','page-review-remote.json'} and not json.loads((W/name).read_text(encoding='utf-8')).get('ok'):raise RuntimeError('Do not publish a failed current browser check as accepted')
 shutil.copy2(W/name,O/name)
for script in ['build_report.py','make_delivery_manifest.py']:
 subprocess.run([sys.executable,'-X','utf8','-B',str(W/script)],cwd=str(R),check=True,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps({'ok':True,'published':['review-notes.md','atomic-progress-check.json'],'raw_model_results_modified':False}))
