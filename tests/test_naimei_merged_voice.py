"""Reject old voices/caches and preserve the exact user-approved merged prompt."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest
from integration.naimei_voice_contract import (load_profile,route_for,cache_matches,worker_matches,
    voice_for_engine,MERGED_PROFILE,MERGED_FREEZE_ID,MERGED_REFERENCE_SHA256)

ROOT=Path(__file__).resolve().parents[1]
TEMP=ROOT/'state/test-tmp'
TEMP.mkdir(parents=True,exist_ok=True)

class MergedVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        shutil.copytree(ROOT/'assets/naimei/voice-final-v1',self.root/'assets/naimei/voice-final-v1')
        (self.root/'configs/naimei').mkdir(parents=True)
        for name in ('voice-models.json','live-runtime.json'):
            shutil.copyfile(ROOT/'configs/naimei'/name,self.root/'configs/naimei'/name)
        self.profile=load_profile(self.root,require_private=False)
        self.voice=self.profile['voices'][0]

    def record(self):
        return {'ready':True,'voice_id':'NCM01','engine':'OmniVoice','reference_sha256':MERGED_REFERENCE_SHA256,
            'spoken_text':'大家好，我是奶妹。','steps':32,'seed':2026102807,'precision':'torch.float16',
            'model':'models/tts-benchmark/omnivoice','reference_preprocess_prompt':False,'voice_freeze_id':MERGED_FREEZE_ID}

    def test_both_sources_form_one_frozen_voice(self):
        self.assertEqual([v['id'] for v in self.profile['voices']],['NCM01'])
        p=json.loads((self.root/'assets/naimei/voice-final-v1/provenance.json').read_text('utf-8'))
        self.assertEqual(p['source_ids'],['SRC01','SRC02'])
        self.assertGreater(p['encoded_reference_seconds'],p['source_segments'][1]['combined_start_seconds'])
        self.assertFalse(self.voice['preprocess_prompt'])

    def test_only_merged_omnivoice_is_routable(self):
        self.assertEqual([(url,v['id']) for url,v in route_for(self.profile,'NCM01')],[('tts_primary_url','NCM01')])
        for ident in ('O07','F07','NC01','NC02','NMV01'):
            with self.assertRaisesRegex(ValueError,'UNAPPROVED'):
                route_for(self.profile,ident)
        with self.assertRaisesRegex(ValueError,'NO_APPROVED_VOICE'):
            voice_for_engine(self.profile,'F5-TTS-v1')

    def test_reference_corruption_fails_before_loading_any_model(self):
        reference=self.root/self.voice['reference']
        reference.parent.mkdir(parents=True,exist_ok=True)
        reference.write_bytes(b'wrong voice')
        with self.assertRaisesRegex(ValueError,'REFERENCE_MISMATCH'):
            load_profile(self.root,require_private=False)

    def test_approved_audition_is_immutable(self):
        (self.root/self.voice['audition']).write_bytes(b'replacement audition')
        with self.assertRaisesRegex(ValueError,'FREEZE_FILE_MISMATCH'):
            load_profile(self.root)

    def test_old_worker_and_preprocessing_cannot_be_reused(self):
        record=self.record()
        self.assertTrue(worker_matches(self.profile,record,'NCM01'))
        for key,value in [('voice_id','O07'),('reference_sha256','310c5d326dfabf0701eb255ca28e9e08f5626795d8b81d4e3b641bbac6b573a8'),('reference_preprocess_prompt',True),('voice_freeze_id','old')]:
            self.assertFalse(worker_matches(self.profile,{**record,key:value},'NCM01'))
        self.assertFalse(worker_matches(self.profile,record,'F07'))

    def test_old_or_different_parameter_caches_are_rejected(self):
        record=self.record();text=record['spoken_text']
        self.assertTrue(cache_matches(record,self.voice,text))
        for key,value in [('voice_id','O07'),('reference_sha256','old'),('reference_preprocess_prompt',True),('voice_freeze_id','old'),('steps',16),('precision','torch.float32'),('seed',1)]:
            self.assertFalse(cache_matches({**record,key:value},self.voice,text))
        self.assertFalse(cache_matches(record,self.voice,'另一句。'))

    def test_profile_cannot_redirect_back_to_legacy_voice(self):
        path=self.root/'configs/naimei/live-runtime.json'
        data=json.loads(path.read_text('utf-8'));data['voice_profile']='assets/naimei/live-v1/voice/profile.json'
        path.write_text(json.dumps(data),'utf-8')
        with self.assertRaisesRegex(ValueError,'PROFILE_POINTER_MISMATCH'):
            load_profile(self.root)

    def test_changing_transcript_or_model_requires_new_approval(self):
        path=self.root/MERGED_PROFILE
        data=json.loads(path.read_text('utf-8'));data['reference_text']='大家好，我是奶妹。'
        path.write_text(json.dumps(data),'utf-8')
        with self.assertRaisesRegex(ValueError,'CONTRACT_MISMATCH'):
            load_profile(self.root)

    def test_public_repository_validates_without_private_reference(self):
        private=self.root/'assets/naimei/voice-final-v1/private'
        if private.exists():
            shutil.rmtree(private)
        with self.assertRaisesRegex(ValueError,'PRIVATE_REFERENCE_MISSING'):
            load_profile(self.root)
        public=load_profile(self.root,require_private=False)
        self.assertFalse(public['private_reference_available'])
        self.assertNotIn('reference_text',public)

    def test_private_reference_transcript_cannot_change(self):
        transcript=self.root/self.profile['reference_text_file']
        transcript.parent.mkdir(parents=True,exist_ok=True)
        transcript.write_text('another transcript','utf-8')
        with self.assertRaisesRegex(ValueError,'PRIVATE_REFERENCE_MISMATCH'):
            load_profile(self.root,require_private=False)

if __name__=='__main__':
    unittest.main()
