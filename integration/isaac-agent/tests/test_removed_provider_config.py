"""Old experiment configuration must not reintroduce a removed provider."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.providers import parse_provider_config,ProviderConfigError


class RemovedProviderConfigTests(unittest.TestCase):
    def test_legacy_configuration_cannot_restore_removed_provider(self):
        legacy={'selected_provider':'local','shadow_enabled':False,
                'providers':{'laya':{'url':'http://127.0.0.1:9530/v1/systemone','model':'old-experiment'}}}
        config=parse_provider_config(legacy,environ={})
        self.assertEqual(config.selected_provider,'local')
        self.assertNotIn('laya',config.persisted_dict()['providers'])
        for field in ('selected_provider','shadow_provider'):
            with self.subTest(field=field),self.assertRaises(ProviderConfigError):
                parse_provider_config({**legacy,field:'laya'},environ={})


if __name__=='__main__':unittest.main()
