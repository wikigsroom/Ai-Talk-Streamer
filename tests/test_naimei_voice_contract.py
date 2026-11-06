"""Preserve the historical O07/F07 release and its cache validation."""
from pathlib import Path
import copy
import json
import shutil
import tempfile
import unittest
from integration.naimei_voice_contract import load_legacy_profile as load_profile, route_for, cache_matches, worker_matches, APPROVED_REFERENCE_SHA256

ROOT = Path(__file__).resolve().parents[1]


class ApprovedVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in ['assets/naimei/live-v1/voice/profile.json','assets/naimei/live-v1/voice/selected-reference.wav',
                     'configs/voices/female-a-o07-f07.json','configs/resident-tts.example.json']:
            target = self.root/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,target)
        self.profile = load_profile(self.root)
        self.voice = self.profile['voices'][0]

    def tearDown(self):
        self.temporary.cleanup()

    def change(self, name, edit):
        path=self.root/name
        value=json.loads(path.read_text('utf-8'))
        edit(value)
        path.write_text(json.dumps(value),'utf-8')

    def test_reference_is_the_original_selected_waveform(self):
        self.assertEqual(self.voice['sha256'],APPROVED_REFERENCE_SHA256)
        self.assertEqual({v['reference'] for v in self.profile['voices']},{'assets/naimei/live-v1/voice/selected-reference.wav'})

    def test_corrupt_reference_cannot_generate_a_replacement_voice(self):
        (self.root/self.voice['reference']).write_bytes(b'new unapproved reference')
        with self.assertRaisesRegex(ValueError,'REFERENCE_MISMATCH'):
            load_profile(self.root)

    def test_missing_reference_fails_closed(self):
        (self.root/self.voice['reference']).unlink()
        with self.assertRaisesRegex(ValueError,'REFERENCE_MISMATCH'):
            load_profile(self.root)

    def test_draft_selection_is_rejected(self):
        for vid in ['NMV01','NMV02','NMV03']:
            with self.assertRaisesRegex(ValueError,'UNAPPROVED'):
                route_for(self.profile,vid)

    def test_primary_failure_routes_to_f07_with_the_same_reference(self):
        routes=route_for(self.profile,'O07')
        self.assertEqual([(url,v['id'],v['engine']) for url,v in routes],
                         [('tts_primary_url','O07','OmniVoice'),('tts_fallback_url','F07','F5-TTS-v1')])
        self.assertEqual(routes[0][1]['sha256'],routes[1][1]['sha256'])

    def test_explicit_f07_never_tries_the_omnivoice_worker(self):
        self.assertEqual([(url,v['id']) for url,v in route_for(self.profile,'F07')],[('tts_fallback_url','F07')])

    def test_cache_requires_the_selected_model_even_with_matching_reference(self):
        record={'voice_id':'O07','engine':'OmniVoice','reference_sha256':APPROVED_REFERENCE_SHA256,'spoken_text':'你好。',
                'steps':32,'seed':2026102807,'precision':'torch.float16','model':'models/tts-benchmark/omnivoice'}
        self.assertTrue(cache_matches(record,self.voice,'你好。'))
        fallback=next(v for v in self.profile['voices'] if v['id']=='F07')
        self.assertFalse(cache_matches(record,fallback,'你好。'))
        self.assertFalse(cache_matches(record,self.voice,'再见。'))
        for key, value in [('model','models/another-model'),('steps',16),('precision','torch.float32'),('seed',1)]:
            self.assertFalse(cache_matches({**record,key:value},self.voice,'你好。'))

    def test_old_nmv_cache_cannot_survive_an_asset_filename_reuse(self):
        record={'voice_id':'NMV01','engine':'OmniVoice','reference_sha256':'7b082199946e4047062fc0698b7b72d4435c1bbbff1f1712d4ccf93560859d9f','spoken_text':'你好。'}
        self.assertFalse(cache_matches(record,self.voice,'你好。'))

    def test_worker_readiness_rejects_another_reference_and_precision(self):
        health={'ready':True,'voice_id':'O07','engine':'OmniVoice','reference_sha256':APPROVED_REFERENCE_SHA256,
                'steps':32,'seed':2026102807,'precision':'torch.float16','model':'models/tts-benchmark/omnivoice'}
        self.assertTrue(worker_matches(self.profile,health,'O07'))
        for key,value in [('reference_sha256','wrong'),('precision','torch.float32'),('voice_id','NMV01'),('engine','F5-TTS-v1'),('model','models/another-model')]:
            wrong={**health,key:value}
            self.assertFalse(worker_matches(self.profile,wrong,'O07'))

    def test_changed_model_parameters_do_not_inherit_selection_approval(self):
        self.change('configs/resident-tts.example.json',lambda p:p['voices']['O07'].__setitem__('model','models/another-model'))
        with self.assertRaisesRegex(ValueError,'CONTRACT_MISMATCH'):
            load_profile(self.root)

    def test_reference_transcript_is_preserved_instead_of_renaming_its_words(self):
        self.change('assets/naimei/live-v1/voice/profile.json',lambda p:p.__setitem__('reference_text','大家好，我是奶妹。'))
        with self.assertRaisesRegex(ValueError,'CONTRACT_MISMATCH'):
            load_profile(self.root)

    def test_model_configuration_cannot_redirect_to_an_unchecked_file(self):
        self.change('assets/naimei/live-v1/voice/profile.json',lambda p:p.__setitem__('model_configuration','configs/another.json'))
        with self.assertRaisesRegex(ValueError,'CONTRACT_MISMATCH'):
            load_profile(self.root)

    def test_installed_model_source_must_match_the_original(self):
        self.change('configs/resident-tts.example.json',lambda p:p['voices']['O07'].__setitem__('source','src/new-fork'))
        with self.assertRaisesRegex(ValueError,'CONTRACT_MISMATCH'):
            load_profile(self.root)


if __name__=='__main__':
    unittest.main()
