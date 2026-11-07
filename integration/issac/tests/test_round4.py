"""R3 failure regressions, written before the R4 candidate is frozen."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from integration.issac.common import AdmissionError,file_hash,read_json,write_json
from integration.issac.saves import SaveProtection


class FirstBootSaveTests(unittest.TestCase):
    def fixture(self,temporary):
        root=Path(temporary);game=root/'game';game.mkdir()
        (game/'rep_persistentgamedata1.dat').write_bytes(b'protected existing slot one')
        guard=SaveProtection(root)
        original=deepcopy(guard.prepare([str(game)]))
        added=root/'Documents/My Games/Binding of Isaac Repentance';added.mkdir(parents=True)
        (added/'options.ini').write_bytes(b'EnableDebugConsole=1\n')
        (added/'log.txt').write_bytes(b'normal first menu log')
        return root,game,added,guard,original

    def test_first_menu_configuration_extends_without_rebaselining_protected_saves(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,game,added,guard,original=self.fixture(temporary)
            with patch.object(guard,'game_stopped'):
                result=guard.prepare([str(game),str(added)],first_boot_root=added)
                repeated=guard.prepare([str(added),str(game)],first_boot_root=added)
            self.assertEqual(result['id'],original['id'])
            self.assertEqual(result['files'][:len(original['files'])],original['files'])
            self.assertEqual(result['roots'][:1],original['roots'])
            self.assertEqual(result,repeated)
            extension=result['authorized_root_additions'][0]
            self.assertEqual(read_json(extension['original_manifest_backup']),original)
            self.assertEqual({Path(x['backup']).name for x in extension['first_boot_files']},{'options.ini','log.txt'})
            self.assertEqual((game/'rep_persistentgamedata1.dat').read_bytes(),b'protected existing slot one')
            guard.verify()
            Path(extension['first_boot_files'][0]['backup']).write_bytes(b'corrupted')
            with self.assertRaisesRegex(AdmissionError,'CONFIG_BACKUP_CHANGED'):guard.verify()

    def test_a_new_slot_three_or_unknown_file_is_never_a_first_boot_config(self):
        for filename in ('rep_persistentgamedata3.dat','rep_persistentgamedata2.dat','unexpected.sav','other.ini'):
            with self.subTest(filename=filename),tempfile.TemporaryDirectory() as temporary:
                root,game,added,guard,original=self.fixture(temporary)
                (added/filename).write_bytes(b'not an authorized new baseline')
                with patch.object(guard,'game_stopped'):
                    with self.assertRaisesRegex(AdmissionError,'CONFIG_ONLY_NO_SAVE'):guard.prepare([str(game),str(added)],first_boot_root=added)
                self.assertEqual(read_json(guard.manifest),original)

    def test_running_game_unknown_root_or_missing_original_root_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,game,added,guard,original=self.fixture(temporary)
            with patch.object(guard,'game_stopped',side_effect=AdmissionError('GAME_STILL_RUNNING')):
                with self.assertRaisesRegex(AdmissionError,'GAME_STILL_RUNNING'):guard.prepare([str(game),str(added)],first_boot_root=added)
            with patch.object(guard,'game_stopped'):
                for roots,expected in (([str(added)],added),([str(game),str(added)],root/'other')):
                    with self.assertRaisesRegex(AdmissionError,'SAVE_ROOT_SET_CHANGED'):guard.prepare(roots,first_boot_root=expected)
            self.assertEqual(read_json(guard.manifest),original)

    def test_extension_does_not_hide_an_existing_protected_save_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,game,added,guard,original=self.fixture(temporary)
            (game/'rep_persistentgamedata1.dat').write_bytes(b'changed')
            with patch.object(guard,'game_stopped'):
                with self.assertRaisesRegex(AdmissionError,'PROTECTED_SAVE_CHANGED'):guard.prepare([str(game),str(added)],first_boot_root=added)
            self.assertEqual(read_json(guard.manifest),original)


class OfflineDependencyTests(unittest.TestCase):
    def fixture(self,temporary):
        root=Path(temporary)/'installation';source=Path(temporary)/'existing'
        rows=[]
        for name,content in [('pydub/__init__.py',b'# existing package\n'),('pydub-0.25.1.dist-info/METADATA',b'Name: pydub\nVersion: 0.25.1\n')]:
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            rows.append({'path':name,'bytes':len(content),'sha256':file_hash(path)})
        write_json(root/'configs/issac/offline-voice-dependencies.json',{'existing_source':str(source),'files':rows})
        return root,source,rows

    def test_existing_runtime_dependency_and_metadata_are_copied_idempotently(self):
        from integration.issac import offline_dependencies as module
        with tempfile.TemporaryDirectory() as temporary:
            root,source,rows=self.fixture(temporary)
            with patch.object(module,'EXISTING_SHARED_SITE',source):
                first=module.install_voice_dependencies(root);again=module.install_voice_dependencies(root)
            self.assertEqual(first['new_files_copied'],2)
            self.assertEqual(again['new_files_copied'],0)
            self.assertEqual(again['new_download_bytes'],0)
            target=root/'runtime/tts-benchmark/omnivoice/Lib/site-packages'
            for row in rows:self.assertEqual(file_hash(target/row['path']),row['sha256'])

    def test_all_sources_are_admitted_before_any_copy_and_conflicts_survive(self):
        from integration.issac import offline_dependencies as module
        with tempfile.TemporaryDirectory() as temporary:
            root,source,rows=self.fixture(temporary)
            target=root/'runtime/tts-benchmark/omnivoice/Lib/site-packages'
            (source/rows[1]['path']).write_bytes(b'changed metadata')
            with patch.object(module,'EXISTING_SHARED_SITE',source):
                with self.assertRaisesRegex(AdmissionError,'DEPENDENCY_CHANGED'):module.install_voice_dependencies(root)
            self.assertFalse(target.exists())
        with tempfile.TemporaryDirectory() as temporary:
            root,source,rows=self.fixture(temporary)
            conflict=root/'runtime/tts-benchmark/omnivoice/Lib/site-packages/pydub/__init__.py'
            conflict.parent.mkdir(parents=True);conflict.write_bytes(b'pre-existing different package')
            with patch.object(module,'EXISTING_SHARED_SITE',source):
                with self.assertRaisesRegex(AdmissionError,'CONFLICT_PRESERVED'):module.install_voice_dependencies(root)
            self.assertEqual(conflict.read_bytes(),b'pre-existing different package')


class IsolatedWindowsProfileTests(unittest.TestCase):
    def test_real_windows_layout_is_created_without_changing_parent_environment(self):
        from integration.issac.local_model import LocalModel
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);model=LocalModel.__new__(LocalModel)
            model.root=root;model.profile=root/'state/isolated-profile';model.home=root/'tools/lmstudio/home'
            before=dict(os.environ)
            env=model.environment()
            self.assertEqual(dict(os.environ),before)
            self.assertEqual(Path(env['APPDATA']),model.profile/'AppData/Roaming')
            self.assertEqual(Path(env['LOCALAPPDATA']),model.profile/'AppData/Local')
            self.assertEqual(Path(env['TEMP']),model.profile/'AppData/Local/Temp')
            for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):self.assertTrue(Path(env[key]).is_dir())
            self.assertEqual(Path((model.profile/'.lmstudio-home-pointer').read_text('utf8')),model.home)


class AcceptanceObserverTests(unittest.TestCase):
    def test_slow_hashing_does_not_starve_the_media_event_loop(self):
        from integration.issac import acceptance
        async def scenario():
            def slow(*args,**kwargs):time.sleep(.08)
            protection=Mock();protection.verify.side_effect=slow
            with patch.object(acceptance,'require_candidate',side_effect=slow):
                task=asyncio.create_task(acceptance.verify_during_media(Path('.'),protection))
                ticks=0
                while not task.done():
                    await asyncio.sleep(.005);ticks+=1
                await task
            self.assertGreater(ticks,8)
            protection.verify.assert_called_once()
        asyncio.run(scenario())

    def test_round_closure_handles_uniform_lists_and_gate_dictionaries(self):
        from integration.issac.acceptance import close_phase
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base=root/'state/issac-acceptance'
            write_json(base/'uniform.json',{'candidate_id':'test','passed':False,'checks':[{'check':'native-game','passed':False},{'check':'static','passed':True}]})
            write_json(base/'gate.json',{'candidate_id':'test','passed':False,'checks':{'mouth':False,'voice':True}})
            write_json(base/'regressions.json',{'candidate_id':'test','passed':False,'results':[{'test':3,'exit_code':1},{'test':0,'exit_code':0}]})
            with patch('integration.issac.acceptance.require_candidate',return_value={'candidate_id':'test'}):result=close_phase(root)
            self.assertEqual(result['recorded_failures'],3)
            self.assertEqual({x for row in result['defects'] for x in row['failed_checks']},{'native-game','mouth','3'})
            self.assertEqual(result['next_action'],'whole_correction_round_then_freeze')


if __name__=='__main__':unittest.main()
