from pathlib import Path
import unittest
from integration.issac.core_model import core_model,current_core_channel_matches,model_identity_matches

ROOT=Path(__file__).resolve().parents[3]


class CoreModelTests(unittest.TestCase):
    def test_startup_and_controller_admit_only_the_same_official_model_and_capacity(self):
        model=core_model(ROOT)
        value={'model':model['model'],'protocol':model['protocol'],'channel_source':model['channel_source'],
               'context_window_tokens':model['context_window_tokens']}
        self.assertTrue(model_identity_matches(ROOT,value))
        self.assertTrue(current_core_channel_matches(ROOT,value))
        for key,wrong in [('model','gpt-6.1-sol'),('protocol','chat_completions'),
                          ('channel_source','issac_original_saved_api_channel'),('context_window_tokens',32768)]:
            with self.subTest(key=key):
                self.assertFalse(current_core_channel_matches(ROOT,{**value,key:wrong}))


if __name__=='__main__':unittest.main()
