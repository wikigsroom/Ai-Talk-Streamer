"""Explicit offline/online selection; no game, model or network connection."""
from pathlib import Path
import json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from mc_game_service import configuration,CONFIG

class PlayerConfigurationTests(unittest.TestCase):
    def read(self,value):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/CONFIG;path.parent.mkdir(parents=True)
            path.write_text(json.dumps(value),encoding='utf8')
            return configuration(root)

    def test_singleplayer_has_no_server_fallback(self):
        result=self.read({'schema_version':2,'mode':'singleplayer','world':None})
        self.assertIsNone(result['server']);self.assertEqual(result['mode'],'singleplayer')

    def test_named_world_keeps_exact_folder_and_legacy_address_is_only_explicit_multiplayer(self):
        for world in ['mc-live-offline-083','MC Live Offline 083','MC  Live Offline 083']:
            result=self.read({'schema_version':2,'mode':'singleplayer','world':world})
            self.assertEqual(result['world'],world)
        result=self.read({'schema_version':1,'server':'localhost:25565'})
        self.assertEqual(result['mode'],'multiplayer');self.assertIsNone(result['world'])

    def test_mixed_modes_or_missing_explicit_mode_are_rejected(self):
        for value in [{'schema_version':2,'server':'localhost:25565'},
                      {'schema_version':2,'mode':'singleplayer','world':None,'server':'localhost:25565'},
                      {'schema_version':2,'mode':'multiplayer','server':'localhost:25565','world':'other'},
                      {'schema_version':2,'mode':'singleplayer','world':12}]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'GAME_SERVICE_CONFIG'):self.read(value)

if __name__=='__main__':unittest.main()
