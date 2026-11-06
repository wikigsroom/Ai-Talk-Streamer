"""Seal the user-approved merged-v3 waveform and recipe without regenerating it."""
from pathlib import Path
import hashlib
import json
import shutil
import wave

ROOT=Path(__file__).resolve().parents[1]
PACK=ROOT/'assets/naimei/voice-final-v1'
CLONE=ROOT/'assets/naimei/voice-clone-merged-v3'
OUTPUT=ROOT/'output/audio/naimei-voice-clone-merged-v3-20261106'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))

def main():
    manifest=PACK/'manifest.json'
    if manifest.exists():
        raise RuntimeError('Voice freeze already exists; validate it or create a new version')
    source=json.loads((CLONE/'manifest.json').read_text('utf-8'))
    ref=source['references'][0]
    assert len(source['references'])==1 and ref['source_ids']==['SRC01','SRC02']
    assert ref['sha256']=='73ef5e49c20d2fad0cbf5911d6ff1b351836a0116635a1e6439fae4e195a6908'
    assert source['prompt_audit']['both_sources_retained'] and source['prompt_audit']['encoded_seconds']==11.92
    copies=[(ROOT/ref['asset_path'],'private/reference.wav'),(CLONE/'references/NCM01-reference.txt','private/reference.txt'),
        (ROOT/source['preview']['path'],'approved-audition.wav'),
        (ROOT/source['full_combined_source']['path'],'private/combined-full.wav')]
    copies.extend((OUTPUT/f'NCM01-S0{i}.wav',f'samples/NCM01-S0{i}.wav') for i in range(1,7))
    files=[]
    for origin,name in copies:
        target=PACK/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and sha(target)!=sha(origin):
            raise RuntimeError('Existing freeze input differs: '+name)
        shutil.copyfile(origin,target)
        assert sha(target)==sha(origin)
        if target.suffix=='.wav':
            with wave.open(str(target),'rb') as audio:
                assert (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())==(24000,1,2)
        if not target.is_relative_to(PACK/'private'):
            files.append(target)
    assert sha(PACK/'approved-audition.wav')==source['preview']['sha256']
    profile={'schema_version':3,'character_id':'naimei','freeze_id':'NM-VOICE-FINAL-20261106-v1',
        'default_voice_id':'NCM01','fallback_voice_id':None,'label':'奶妹 · 双录音合并定稿',
        'engine':'OmniVoice','fallback_engine':None,'automatic_fallback':False,
        'reference_text_file':'assets/naimei/voice-final-v1/private/reference.txt',
        'reference_text_sha256':sha(PACK/'private/reference.txt'),'reference_sha256':ref['sha256'],
        'approved_source':'assets/naimei/voice-final-v1/manifest.json',
        'model_configuration':'configs/naimei/voice-models.json',
        'voice_origin':'One combined reference from both user recordings; approved merged-v3 audio is preserved byte-for-byte',
        'voices':[{'id':'NCM01','label':'奶妹 · 双录音合并定稿','engine':'OmniVoice','role':'default',
            'steps':32,'precision':'FP16','reference':'assets/naimei/voice-final-v1/private/reference.wav',
            'reference_text_file':'assets/naimei/voice-final-v1/private/reference.txt',
            'reference_text_sha256':sha(PACK/'private/reference.txt'),'sha256':ref['sha256'],'preprocess_prompt':False,
            'audition':'assets/naimei/voice-final-v1/approved-audition.wav'}],
        'sample_rate':24000,'steps':32,'speed':1.0,'seed':2026102807,
        'reference_preprocess_prompt':False,'speech_asset_root':'assets/naimei/speech-ncm01-v1',
        'voice_frozen':True,'user_audition_confirmed':True,'naimei_audition_confirmed':True,
        'voice_identity_accepted':True,'mouth_quality_accepted':False,
        'new_model_weight_bytes':0,'cloud_inference_allowed':False}
    models={'release':profile['freeze_id'],'default_voice_id':'NCM01','automatic_fallback':False,
        'seed':profile['seed'],'reference_audio':profile['voices'][0]['reference'],
        'reference_text_file':profile['reference_text_file'],'reference_text_sha256':profile['reference_text_sha256'],
        'reference_sha256':ref['sha256'],'reference_preprocess_prompt':False,
        'voices':{'NCM01':{'engine':'OmniVoice','python':'runtime/tts-benchmark/omnivoice/Scripts/python.exe',
            'source':'src/tts-benchmark/omnivoice','model':'models/tts-benchmark/omnivoice',
            'port':9891,'precision':'FP16','steps':32}}}
    save(PACK/'profile.json',profile);save(ROOT/'configs/naimei/voice-models.json',models)
    provenance={'parent_clone_id':source['pack_id'],'reference_sha256':ref['sha256'],
        'reference_seconds':11.92,'source_ids':['SRC01','SRC02'],'source_segments':ref['segments'],
        'full_combined_seconds':source['full_combined_source']['seconds'],
        'full_combined_sha256':source['full_combined_source']['sha256'],
        'one_combined_prompt':True,'preprocess_prompt':False,'encoded_reference_seconds':11.92,
        'reference_audio_token_frames':source['prompt_audit']['reference_audio_token_frames'],
        'audition_sha256':source['preview']['sha256'],'audition_seconds':source['preview']['seconds'],
        'samples':[{'id':x['id'],'text':next(y['text'] for y in source['lines'] if x['id'].endswith(y['id'])),
            'sha256':x['audio_sha256'],'seconds':x['seconds']} for x in source['checks']]}
    # Keep source hashes/timestamps, while removing this machine's private paths.
    for item in provenance['source_segments']:
        item.pop('source_excerpt_file',None)
        item.pop('reference_text',None)
    save(PACK/'provenance.json',provenance)
    files.extend([PACK/'profile.json',ROOT/'configs/naimei/voice-models.json',PACK/'provenance.json'])
    freeze={'schema_version':1,'freeze_id':profile['freeze_id'],'status':'frozen','character_id':'naimei',
        'voice_id':'NCM01','parent_clone_id':source['pack_id'],'approved_reference_sha256':ref['sha256'],
        'approval':{'by':'user','date':'2026-11-06','instruction':'定稿约束，使用该版本的音频，并且同步更新到仓库。',
            'scope':'Merged-v3 reference, voice identity, approved audition and synthesis recipe'},
        'voice_identity_accepted':True,'mouth_quality_accepted':False,'live_performance_accepted':False,
        'remote_activation_recorded':False,'public_broadcast_allowed':False,'repository_contains_reference_audio':False,
        'publication_constraint':'Generated auditions only; exclude original reference audio, transcript and full source recordings',
        'files':[{'path':f.relative_to(ROOT).as_posix(),'bytes':f.stat().st_size,'sha256':sha(f)} for f in files],
        'private_files':[{'path':f.relative_to(ROOT).as_posix(),'bytes':f.stat().st_size,'sha256':sha(f),
            'required_for_runtime':f.name in {'reference.wav','reference.txt'}} for f in sorted((PACK/'private').iterdir()) if f.is_file()]}
    save(manifest,freeze)
    print(json.dumps({'freeze_id':freeze['freeze_id'],'voice_id':'NCM01','files':len(files),
        'reference_sha256':ref['sha256'],'preserved_approved_audio':True},ensure_ascii=False))

if __name__=='__main__':
    main()
