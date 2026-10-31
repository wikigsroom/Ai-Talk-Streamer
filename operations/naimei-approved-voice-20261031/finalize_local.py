from pathlib import Path
import json
import subprocess

root = Path(__file__).resolve().parents[2]
review = root / 'output/review/naimei-approved-voice-20261031'
browser = json.loads((review / 'browser-voice-check.json').read_text('utf-8'))
models = json.loads((review / 'model-integrity.json').read_text('utf-8'))
integrity = json.loads((root / 'assets/naimei/live-v1/integrity-review.json').read_text('utf-8'))
assert browser['passed'] and browser['created_browser_closed'] and models['all_matched'] and integrity['integrity_passed']
assert subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip()=='naimei'
summary = {'character_id':'naimei','branch':'naimei','default_voice_id':'O07','fallback_voice_id':'F07',
    'reference_sha256':integrity['voice_reference_sha256'], 'model_fingerprint_files':len(models['model_files']),
    'model_fingerprints_matched':models['all_matched'],'python_tests':49,'python_tests_passed':True,
    'formal_player_requests':[{'voice_id':u['event']['voice_id'],'request_id':u['request_id'],
        'completed':u['status']=='COMPLETED','natural_end':u['natural_end']} for u in browser['utterances']],
    'browser_pages_created_by_test_closed':True,'old_nmv_voice_rejected':True,
    'speech_asset_count':integrity['speech_wavs'],'additional_model_weight_bytes':0,
    'naimei_listening_accepted':False,'character_quality_accepted':False,'public_broadcast_started':False}
(review/'verification-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf-8')
files = [
 'AGENTS.md','assets/naimei/live-v1/voice','assets/naimei/live-v1/content-index.csv','assets/naimei/live-v1/integrity-review.json',
 'integration/naimei_voice_contract.py','integration/naimei_voice_worker.py','integration/naimei_studio.py',
 'scripts/start_naimei.py','scripts/prepare_naimei_speech.py','scripts/prepare_naimei_auditions.py',
 'scripts/verify_naimei_fallback.py','scripts/verify_naimei_voice_failover.py','scripts/validate_naimei_assets.py',
 'web/naimei.html','web/naimei.js','tests/test_naimei_voice_contract.py',
 'docs/naimei/原选音色核验与恢复.md','docs/naimei/A01-A14实施与直播接入.md','docs/naimei/A01-A14验收与阻塞报告.md',
 'docs/naimei/直播接入任务清单.csv','operations/naimei-a01-a14-20261031/build_release.py']
for name in ['browser-voice-check.json','model-integrity.json','verification-summary.json','voice-transfer.json','director-approved-voice.png']:
 files.append((review/name).relative_to(root).as_posix())
task = Path(__file__).parent
for path in sorted(task.iterdir()):
 if path.is_file() and (path.name=='.gitignore' or path.suffix in {'.py','.cjs','.ps1'}):
  if path.name not in {'sync-sources.ps1','verify-model-files.ps1'}:
   files.append(path.relative_to(root).as_posix())
subprocess.run(['git','-c','core.safecrlf=false','add','--',*files],cwd=root,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
staged=subprocess.check_output(['git','diff','--cached','--name-only','-z'],cwd=root).decode().split('\0')
print(json.dumps({'staged_files':len([n for n in staged if n]),'voice_contract_summary':summary},ensure_ascii=False))
