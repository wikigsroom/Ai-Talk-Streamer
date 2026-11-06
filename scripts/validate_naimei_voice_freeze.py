"""Validate the selected voice freeze independently of historical visual releases."""
from pathlib import Path
import json
import sys
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integration.naimei_voice_contract import load_profile, route_for

def validate(root=ROOT):
    root=Path(root).resolve()
    profile=load_profile(root,require_private=False)
    pack=root/'assets/naimei/voice-final-v1'
    freeze=json.loads((pack/'manifest.json').read_text('utf-8'))
    provenance=json.loads((pack/'provenance.json').read_text('utf-8'))
    assert provenance['source_ids']==['SRC01','SRC02'] and provenance['one_combined_prompt']
    assert provenance['preprocess_prompt'] is False and provenance['encoded_reference_seconds']==11.92
    assert len(provenance['samples'])==6
    waves=[('approved-audition.wav',31.57)]
    if profile['private_reference_available']:
        waves.append(('private/reference.wav',11.92))
    for name,expected_seconds in waves:
        with wave.open(str(pack/name),'rb') as audio:
            assert (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())==(24000,1,2)
            assert abs(audio.getnframes()/24000-expected_seconds)<1/24000
    assert len(route_for(profile,'NCM01'))==1
    character=root/'configs/characters/naimei.json'
    if character.exists():
        assert json.loads(character.read_text('utf-8'))['voice_profile']=='assets/naimei/voice-final-v1/profile.json'
    return {'ok':True,'freeze_id':freeze['freeze_id'],'voice_id':'NCM01','source_count':2,
        'reference_seconds':11.92,'audition_seconds':31.57,'locked_files':len(freeze['files']),
        'user_approved':True,'automatic_fallback':False,'new_model_weight_bytes':0,
        'repository_contains_reference_audio':False,'private_reference_available':profile['private_reference_available'],
        'mouth_quality_accepted':False,'remote_activation_recorded':False}

if __name__=='__main__':
    print(json.dumps(validate(),ensure_ascii=False))
