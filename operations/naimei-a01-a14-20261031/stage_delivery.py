"""Stage the named delivery only, preserving earlier untracked character work."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
if subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip()!='naimei':
    raise RuntimeError('NAIMEI_BRANCH_REQUIRED')
files = [
 'assets/naimei/live-v1/content-index.csv','assets/naimei/live-v1/integrity-review.json',
 'assets/naimei/live-v1/voice/fallback/NMV01-f5-check.json','assets/naimei/live-v1/voice/fallback/NMV01-f5-check.wav',
 'backend/platforms/livehime.mjs','backend/platforms/manager.mjs','integration/naimei_studio.py',
 'web/naimei-output.js','scripts/reload_naimei_services.ps1','scripts/validate_naimei_assets.py',
 'tests/platform-livehime.test.mjs','tests/platforms.test.mjs',
 'docs/naimei/A01-A14实施与直播接入.md','docs/naimei/A01-A14验收与阻塞报告.md','docs/naimei/直播接入任务清单.csv',
 'output/review/naimei-live-v1/browser/playback-verification-summary.json',
 'output/review/naimei-live-v1/browser/奶妹-真实链路联调.mp4'
]
operation_files = ['remote_client.py','build_release.py','upload_release.py','sync_review_files.py','install-4090.ps1',
 'live_browser_check.cjs','programme_browser_check.cjs','check_director_ui.cjs','prepare_livehime_check.py',
 'check_flashhead_speech.cjs','render_speech_review.py','finalize_review.py','stage_delivery.py']
files += ['operations/naimei-a01-a14-20261031/'+name for name in operation_files]
for pattern in ['*.mp4','*-contact.jpg','*-mouth-all-frames.jpg','speech-check.json']:
    files += [p.relative_to(root).as_posix() for p in (root/'output/review/naimei-live-v1/flashhead').glob(pattern)]
files += [p.relative_to(root).as_posix() for p in (root/'output/review/naimei-live-v1/browser').glob('*.png')]
assert all((root/p).is_file() and '/state/' not in '/'+p and not p.endswith(('.key','.env','.pem')) for p in files)
subprocess.run(['git','add','--',*sorted(set(files))],cwd=root,check=True)
print('Staged '+str(len(set(files)))+' explicitly selected delivery files')
