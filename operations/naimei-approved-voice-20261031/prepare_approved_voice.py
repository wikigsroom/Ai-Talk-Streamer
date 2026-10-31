"""Preserve the superseded draft and copy the byte-identical approved reference."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

root = Path(__file__).resolve().parents[2]
if subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip() != 'naimei':
    raise RuntimeError('NAIMEI_BRANCH_REQUIRED')
pack = root / 'assets/naimei/live-v1/voice'
history = root / 'output/review/naimei-approved-voice-20261031/superseded-NMV'
assert pack.resolve().is_relative_to(root) and history.resolve().is_relative_to(root)
source = json.loads((root / 'configs/voices/female-a-o07-f07.json').read_text('utf-8'))
models = json.loads((root / 'configs/resident-tts.example.json').read_text('utf-8'))
reference = root / source['reference_audio']
expected = '310c5d326dfabf0701eb255ca28e9e08f5626795d8b81d4e3b641bbac6b573a8'
assert hashlib.sha256(reference.read_bytes()).hexdigest() == source['reference_sha256'] == expected
if not history.exists():
    shutil.copytree(pack, history)
target = pack / 'selected-reference.wav'
shutil.copyfile(reference, target)
voices = []
for selected in source['voices']:
    vid = selected['id']
    spec = models['voices'][vid]
    voices.append({'id':vid,'label':selected['label'] + (' · 主用' if vid == 'O07' else ' · 备用'),
        'engine':spec['engine'],'role':selected['role'],'steps':spec['steps'],'precision':spec['precision'],
        'reference':target.relative_to(root).as_posix(),'reference_text':source['reference_text'],'sha256':expected,
        'audition':'assets/naimei/live-v1/voice/'+vid+'-audition.wav'})
profile = {'schema_version':2,'character_id':'naimei','default_voice_id':'O07','fallback_voice_id':'F07',
    'label':'原选音色 · 夏栀 · 温柔清甜','engine':'OmniVoice','fallback_engine':'F5-TTS-v1',
    'fallback_requires_stopped_primary_request':True,'reference_text':source['reference_text'],
    'reference_sha256':expected,'approved_source':'configs/voices/female-a-o07-f07.json',
    'model_configuration':'configs/resident-tts.example.json','voice_origin':'Reuse the user-selected O07/F07 reference byte-for-byte; no new voice design',
    'voices':voices,'sample_rate':24000,'steps':32,'speed':1.0,'seed':models['seed'],
    'user_audition_confirmed':True,'naimei_audition_confirmed':False,'new_model_weight_bytes':0,'cloud_inference_allowed':False}
(pack/'profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n','utf-8')
for name in ['NMV01-reference.wav','NMV02-reference.wav','NMV03-reference.wav','fallback/NMV01-f5-check.wav','fallback/NMV01-f5-check.json']:
    path=pack/name
    if path.exists():
        saved=history/name
        if not path.resolve().is_relative_to(pack.resolve()) or not saved.is_file() or saved.read_bytes()!=path.read_bytes():
            raise RuntimeError('SUPERSEDED_ASSET_NOT_PRESERVED')
        path.unlink()
print(json.dumps({'default_voice':'O07','fallback_voice':'F07','reference_sha256':expected,'superseded_draft_preserved':True}))
