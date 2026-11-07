"""Fresh-install and save-isolation regressions using temporary native directories."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import configure_install as setup
import sync_mod_sources as deploy
import setup_dsh


class SaveSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.project=self.base/'project';self.project.mkdir()
        self.game=self.base/'game';self.game.mkdir();(self.game/'isaac-ng.exe').write_bytes(b'fixture exe')
        self.save=self.base/'save';self.save.mkdir()
        self.patch=patch.object(setup,'ROOT',self.project);self.patch.start()
        self.proc=patch.object(setup.psutil,'process_iter',return_value=[]);self.proc.start()
    def tearDown(self):self.proc.stop();self.patch.stop();self.temp.cleanup()
    def test_snapshot_preserves_slots_one_two_and_all_original_cloud_data(self):
        (self.save/'persistentgamedata1.dat').write_bytes(b'first')
        (self.save/'persistentgamedata2.dat').write_bytes(b'second')
        (self.save/'persistentgamedata3.dat').write_bytes(b'authorized test')
        (self.save/'empty').mkdir()
        cloud=self.base/'cloud';cloud.mkdir();(cloud/'rep_persistentgamedata3.dat').write_bytes(b'original cloud third')
        before=setup.inventory(self.save)
        result=setup.configure(self.game,self.save,[cloud],allow_existing_slot3=True)
        self.assertEqual(before,setup.inventory(self.save));self.assertTrue(result['backup_verified'])
        protection=json.loads((self.project/'save-protection.json').read_text())
        manifest=json.loads(Path(protection['baseline_manifest']).read_text())
        names=[Path(r['source']).name for r in manifest['files']]
        self.assertNotIn('persistentgamedata3.dat',names)
        self.assertIn('rep_persistentgamedata3.dat',names)
        self.assertEqual(manifest['protected_dat_count'],3)
        self.assertFalse(protection['autopilot_allowed'])
        self.assertTrue((Path(result['backup'])/'0/empty').is_dir())
    def test_existing_slot_three_requires_explicit_authorization(self):
        (self.save/'persistentgamedata3.dat').write_bytes(b'existing')
        with self.assertRaises(RuntimeError):setup.configure(self.game,self.save)
        self.assertFalse((self.project/'game-install.json').exists())
    def test_existing_machine_configuration_is_never_overwritten(self):
        path=self.project/'game-install.json';path.write_bytes(b'existing config')
        with self.assertRaises(RuntimeError):setup.configure(self.game,self.save)
        self.assertEqual(path.read_bytes(),b'existing config')
    def test_game_running_cannot_create_an_inconsistent_backup(self):
        class Process: info={'name':'isaac-ng.exe'}
        with patch.object(setup.psutil,'process_iter',return_value=[Process()]):
            with self.assertRaises(RuntimeError):setup.configure(self.game,self.save)
        self.assertFalse((self.project/'backups').exists())
    def test_recursive_backup_destination_and_overlapping_protected_root_rejected(self):
        with self.assertRaises(RuntimeError):setup.configure(self.game,self.save,backup_root=self.save/'backup')
        with self.assertRaises(RuntimeError):setup.configure(self.game,self.save,[self.save])
        self.assertEqual(list(self.save.iterdir()),[])


class FirstDeployTests(unittest.TestCase):
    def test_new_destination_and_backup_of_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game=root/'game';game.mkdir();(game/'isaac-ng.exe').touch()
            source=root/'mods/IsaacJev';source.mkdir(parents=True)
            for name in deploy.FILES:(source/name).write_text('new '+name)
            (root/'game-install.json').write_text(json.dumps({'game_root':str(game),'executable':'isaac-ng.exe'}))
            with patch.object(deploy,'ROOT',root),patch.object(sys,'argv',['sync_mod_sources.py','--version','native130']):
                deploy.main()
                for name in deploy.FILES:self.assertEqual((game/'mods/IsaacJev'/name).read_bytes(),(source/name).read_bytes())
                (game/'mods/IsaacJev/main.lua').write_text('old controller')
                deploy.main()
            report=json.loads((root/'latest-mod-deployment.json').read_text())
            self.assertEqual((Path(report['backup'])/'main.lua').read_text(),'old controller')


class RuntimeDiscoveryTests(unittest.TestCase):
    def test_explicit_native_runtime_does_not_depend_on_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);node=root/'node.exe';npm=root/'npm-cli.js';node.touch();npm.touch()
            with patch.object(setup_dsh.subprocess,'check_output',return_value='v24.22.1'),patch.dict('os.environ',{},clear=True):
                self.assertEqual(setup_dsh.discover(str(node),str(npm)),(node.resolve(),npm.resolve(),'v24.22.1'))
    def test_old_node_is_rejected_before_any_dependency_install(self):
        with tempfile.TemporaryDirectory() as folder:
            node=Path(folder)/'node.exe';node.touch()
            with patch.object(setup_dsh.subprocess,'check_output',return_value='v22.12.0'):
                with self.assertRaises(RuntimeError):setup_dsh.discover(str(node),'npm-cli.js')


if __name__=='__main__':unittest.main()
