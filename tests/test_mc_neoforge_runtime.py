"""Preparation boundaries against explicit tiny files, never game/model execution."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import subprocess
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import mc_deployment as deployment
import mc_neoforge as neo
from mc_neoforge_runtime_fixture import install, write_json


class NeoForgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'installation'
        self.root.mkdir()
        self.source = install(self.root)
        self.work = self.root / neo.HOME / 'work'

    def inventory(self):
        return neo.runtime_files(self.root)

    def edit_json(self, path, change):
        value = neo.read(path)
        change(value)
        write_json(path, value)

    def rewrite_jar(self, change):
        path = self.root / neo.CONTROLLER_JAR
        with zipfile.ZipFile(path) as archive:
            entries = {name:archive.read(name) for name in archive.namelist()}
        change(entries)
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        # Even an internally consistent outer receipt cannot replace the checks
        # on embedded resources/schema/dependencies.
        self.edit_json(self.root / neo.BUILD_RECEIPT,
                       lambda value:value.update(sha256=neo.sha(path), bytes=path.stat().st_size))

    def test_inventory_is_read_only_and_binds_both_installed_and_supplied_files(self):
        before = {str(p):neo.sha(p) for p in self.root.parent.rglob('*') if p.is_file()}
        files = self.inventory()
        self.assertIn(neo.CONTROLLER_JAR, files)
        self.assertIn(str(self.source / '.minecraft/versions/MC-Friends-S1-r001/runtime/java21/lib/modules'), files)
        self.assertIn(neo.HOME + '/work/mods/fixture-318.jar', files)
        self.assertEqual(before, {str(p):neo.sha(p) for p in self.root.parent.rglob('*') if p.is_file()})

    def test_offline_identity_and_non_authorizing_receipt_are_required(self):
        path = self.root / neo.RECEIPT
        original = path.read_bytes()
        for change in [{'username':'naimei'}, {'offline_uuid':'0'*36},
                       {'automatic_input_authorized':True}, {'full_application_prepared':True}]:
            with self.subTest(change=change):
                path.write_bytes(original)
                self.edit_json(path, lambda value:value.update(change))
                with self.assertRaisesRegex(ValueError, 'RUNTIME_BINDING'):
                    self.inventory()

    def test_copied_game_receipt_cannot_authorize_another_installation(self):
        self.edit_json(self.root / neo.RECEIPT, lambda value:value.update(installation_root=str(self.root.parent)))
        with self.assertRaisesRegex(ValueError, 'RUNTIME_BINDING'):
            self.inventory()

    def test_missing_lock_hash_is_not_a_request_to_skip_validation(self):
        self.edit_json(self.root / neo.RECEIPT, lambda value:value.pop('lock_sha256'))
        with self.assertRaisesRegex(ValueError, 'RUNTIME_LOCK_HASH'):
            self.inventory()

    def test_supplied_mod_change_is_rejected(self):
        (self.source / '.minecraft/versions/MC-Friends-S1-r001/mods/fixture-0.jar').write_bytes(b'X')
        with self.assertRaisesRegex(ValueError, 'SUPPLIED_FILE_CHANGED'):
            self.inventory()

    def test_same_size_installed_mod_change_is_rejected(self):
        (self.work / 'mods/fixture-0.jar').write_bytes(b'X')
        with self.assertRaisesRegex(ValueError, 'RUNTIME_HASH'):
            self.inventory()

    def test_extra_control_mod_or_directory_is_rejected(self):
        path = self.work / 'mods/second-input-writer.jar'
        path.write_bytes(b'EXTRA CONTROLLER')
        with self.assertRaisesRegex(ValueError, 'TARGET_MOD_SET_CHANGED'):
            self.inventory()
        path.unlink()
        path.mkdir()
        with self.assertRaisesRegex(ValueError, 'TARGET_MOD_SET_CHANGED'):
            self.inventory()

    def test_modified_copied_native_is_rejected(self):
        (self.root / neo.HOME / 'natives/test.dll').write_bytes(b'REPLACED DLL')
        with self.assertRaisesRegex(ValueError, 'RUNTIME_FILE_MISSING_OR_SIZE'):
            self.inventory()

    def test_missing_copied_native_is_rejected(self):
        (self.root / neo.HOME / 'natives/test.dll').unlink()
        with self.assertRaisesRegex(ValueError, 'RUNTIME_NATIVE_SET'):
            self.inventory()

    def test_jre_modules_participate_even_when_executable_is_unchanged(self):
        before = self.inventory()
        exe = self.source / '.minecraft/versions/MC-Friends-S1-r001/runtime/java21/bin/java.exe'
        original = neo.sha(exe)
        module = exe.parents[1] / 'lib/modules'
        module.write_bytes(b'CHANGED JRE MODULES')
        after = self.inventory()
        self.assertEqual(neo.sha(exe), original)
        self.assertNotEqual(before, after)
        self.assertNotEqual(before[str(module)], after[str(module)])

    def asset_path(self):
        index = neo.read(self.source / '.minecraft/assets/indexes/17.json')
        digest = next(iter(index['objects'].values()))['hash']
        return self.source / ('.minecraft/assets/objects/' + digest[:2] + '/' + digest)

    def test_missing_asset_is_rejected_without_downloading(self):
        self.asset_path().unlink()
        with self.assertRaisesRegex(ValueError, 'RUNTIME_ASSET_MISSING_OR_SIZE'):
            self.inventory()

    def test_same_size_changed_asset_is_rejected(self):
        path = self.asset_path()
        path.write_bytes(b'X' * path.stat().st_size)
        with self.assertRaisesRegex(ValueError, 'RUNTIME_ASSET_HASH'):
            self.inventory()

    def test_new_unbuilt_java_source_invalidates_the_exact_build_source_set(self):
        path = self.root / 'game-adapters/minecraft/neoforge/src/main/java/NewInputOwner.java'
        path.write_bytes(b'// newly added source that the old jar does not contain')
        with self.assertRaisesRegex(ValueError, 'BUILD_SOURCE_SET_OR_HASH'):
            self.inventory()

    def test_missing_or_changed_build_digest_is_rejected(self):
        self.edit_json(self.root / neo.BUILD_RECEIPT, lambda value:value.pop('sha256'))
        with self.assertRaisesRegex(ValueError, 'BUILD_BINDING'):
            self.inventory()

    def test_build_cannot_omit_dependency_accounting(self):
        self.edit_json(self.root / neo.BUILD_RECEIPT, lambda value:value.update(dependencies={}))
        with self.assertRaisesRegex(ValueError, 'BUILD_DEPENDENCY_SET'):
            self.inventory()

    def test_outer_jar_digest_does_not_replace_required_control_classes(self):
        self.rewrite_jar(lambda entries:entries.pop('dev/aitalkstreamer/mc/core/BridgeCore.class'))
        with self.assertRaisesRegex(ValueError, 'JAR_CLASSES'):
            self.inventory()

    def test_outer_jar_digest_does_not_replace_resource_comparison(self):
        self.rewrite_jar(lambda entries:entries.update({'META-INF/neoforge.mods.toml':b'wrong client identity'}))
        with self.assertRaisesRegex(ValueError, 'JAR_RESOURCE'):
            self.inventory()

    def test_outer_jar_digest_does_not_replace_contract_schema_comparison(self):
        self.rewrite_jar(lambda entries:entries.update({'mc-contracts/game.schema.json':b'{}'}))
        with self.assertRaisesRegex(ValueError, 'JAR_SCHEMA'):
            self.inventory()

    def test_outer_jar_digest_does_not_replace_embedded_dependency_hash(self):
        entry = neo.read(self.root / neo.BRIDGE_LOCK)['dependencies'][0]
        self.rewrite_jar(lambda entries:entries.update({'META-INF/jarjar/' + entry['file']:b'unreviewed replacement'}))
        with self.assertRaisesRegex(ValueError, 'JAR_DEPENDENCY'):
            self.inventory()

    def test_embedded_dependency_metadata_must_match_both_exact_versions(self):
        self.rewrite_jar(lambda entries:entries.update({'META-INF/jarjar/metadata.json':b'{"jars":[]}'}))
        with self.assertRaisesRegex(ValueError, 'JAR_DEPENDENCY_METADATA'):
            self.inventory()

    def test_mutable_saves_logs_and_options_do_not_invalidate_immutable_inventory(self):
        before = self.inventory()
        for name in ['saves/owned/level.dat','logs/latest.log','options.txt','config/generated.json']:
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'LEGITIMATE LIVE PLAYER DATA')
        self.assertEqual(self.inventory(), before)

    def test_accounts_and_credentials_are_not_imported_or_inventoried(self):
        path = self.source / '.minecraft/versions/MC-Friends-S1-r001/PCL/accounts.json'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'PRIVATE FIXTURE, NEVER IMPORT')
        files = self.inventory()
        self.assertNotIn(str(path), files)
        self.assertFalse((self.work / 'PCL').exists())

    def test_engineering_endpoint_cannot_receive_application_preparation(self):
        config = self.work / 'config/ai-talk-streamer-bridge.json'
        self.edit_json(config, lambda value:value.update(endpoint='ws://127.0.0.1:18974/api/dsh/game/bridge'))
        self.assertTrue(self.inventory())
        with self.assertRaisesRegex(deployment.PreparationError, 'GAME_BRIDGE_BINDING'):
            deployment.client_runtime_files(self.root)

    def test_status_is_explicitly_not_application_or_game_acceptance(self):
        status = neo.runtime_status(self.root)
        self.assertTrue(status['ok'])
        for name in ['automatic_input_authorized','full_application_prepared','services_started','models_loaded','game_started']:
            self.assertIs(status[name], False)
        self.assertEqual(status['real_acceptance_passed'], 0)
        (self.root / neo.RECEIPT).unlink()
        failed = neo.runtime_status(self.root)
        self.assertFalse(failed['ok'])
        self.assertNotIn(str(self.root), json.dumps(failed))
        self.assertNotIn(str(self.source), json.dumps(failed))

    def test_public_cli_reports_current_neoforge_inventory_as_read_only(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'scripts/mc_runtime.py'),
                                 'neoforge-status', '--root', str(self.root)], capture_output=True,
                                text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertTrue(status['ok'])
        self.assertIs(status['game_started'], False)
        self.assertIs(status['full_application_prepared'], False)


if __name__ == '__main__':
    unittest.main()
