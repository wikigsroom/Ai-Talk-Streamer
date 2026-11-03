"""Native filesystem/source package checks; model/GPU probes remain explicit doubles."""
from pathlib import Path
from unittest.mock import patch
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import unittest
import warnings
import zipfile
import test_mc_deployment as deployment_fixture

ROOT, mc = deployment_fixture.ROOT, deployment_fixture.mc


class McSourcePackageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = deployment_fixture.McDeploymentTests('runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root; self.parent = self.root.parent
        for name in sorted(mc.SOURCE_REQUIRED | {'Start-Avatar.ps1', 'Setup-Streamer.ps1'}):
            if not (self.root / name).exists():
                self.fixture.bytes(name, (ROOT / name).read_bytes())
        # SOURCE_REQUIRED adds real source files to the tiny installation.
        # Rebuild its explicit binary double before testing preparation; a stale
        # receipt must continue to be rejected by production validation.
        from mc_neoforge_runtime_fixture import rebuild_receipt
        rebuild_receipt(self.root)
        self.archive = self.parent / 'project-source.zip'; self.destination = self.parent / 'installed'

    def export(self):
        return mc.export_source(self.root, self.archive)

    def test_public_root_tests_and_fixtures_are_exported_and_bound_to_installation(self):
        fixtures = {'tests/core.test.mjs': b'// public test fixture\n',
                    'tests/support.mjs': b'export const fixture = true;\n',
                    'tests/fixtures/example.txt': b'public fixture bytes\n'}
        for name, data in fixtures.items():
            self.fixture.bytes(name, data)
        self.install()
        source = mc.installed_source_identity(self.destination)
        for name, data in fixtures.items():
            self.assertIn(name, source['files'])
            self.assertEqual((self.destination / name).read_bytes(), data)
        (self.destination / 'tests/core.test.mjs').write_bytes(b'changed installed test')
        with self.assertRaisesRegex(mc.PreparationError, 'SOURCE'):
            mc.installed_source_identity(self.destination)

    def test_force_tracked_private_test_data_cannot_enter_the_source_package(self):
        self.fixture.bytes('tests/audience.private.json', b'fixture private data')
        self.fixture.git('add', '-f', 'tests/audience.private.json')
        with self.assertRaisesRegex(mc.PreparationError, 'SOURCE_PATH_OR_COUNT'):
            self.export()
        self.assertFalse(self.archive.exists())

    def install(self):
        self.export(); return mc.install_source(self.archive, self.destination, mc.sha(self.archive))

    def manifest(self):
        with zipfile.ZipFile(self.archive) as archive:
            return json.loads(archive.read(mc.SOURCE_MANIFEST))

    def rewrite(self, change=None, extra=None, raw_manifest=None):
        with zipfile.ZipFile(self.archive) as archive:
            files = [(i.filename, archive.read(i)) for i in archive.infolist() if i.filename != mc.SOURCE_MANIFEST]
            manifest = json.loads(archive.read(mc.SOURCE_MANIFEST))
        if change: change(manifest, files)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)  # Deliberate duplicate-member fixture only.
            with zipfile.ZipFile(self.archive, 'w') as archive:
                archive.writestr(mc.SOURCE_MANIFEST, raw_manifest or mc.canonical(manifest))
                for name, data in files: archive.writestr(name, data)
                if extra:
                    info, data = extra; archive.writestr(info, data)

    def reject_install(self, code):
        before = {p.name for p in self.parent.iterdir()}
        with self.assertRaisesRegex((RuntimeError, zipfile.BadZipFile), code):
            mc.install_source(self.archive, self.destination, mc.sha(self.archive))
        self.assertFalse(self.destination.exists())
        self.assertEqual({p.name for p in self.parent.iterdir()}, before)

    def populate_runtime(self):
        source_files = self.manifest()['source']['files']
        excluded = {mc.RECEIPT, mc.SOURCE_ORIGIN, mc.PREPARING, '.setup/deployment-origin.json', '.setup/mc-client-installation.json'}
        for directory, dirs, files in os.walk(self.root):
            dirs[:] = [name for name in dirs if name != '.git']
            for filename in files:
                path = Path(directory) / filename; name = path.relative_to(self.root).as_posix()
                if name in source_files or name in excluded: continue
                target = self.destination / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        self.fixture.root = self.destination
        self.fixture.write_client_fixture_receipt()

    def test_source_proof_includes_runtime_schema_launchers_and_license_files(self):
        source = mc.source_identity(self.root)
        self.assertTrue(mc.SOURCE_REQUIRED <= set(source['files']))
        self.assertIn('Start-Avatar.ps1', source['files']); self.assertIn('Setup-Streamer.ps1', source['files'])

    def test_root_launcher_change_invalidates_environment_preparation(self):
        self.fixture.prepare(); self.fixture.bytes('Start-Avatar.ps1', b'changed launch path')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_CHANGED'): self.fixture.validate()

    def test_runtime_schema_change_invalidates_environment_preparation(self):
        self.fixture.prepare(); self.fixture.bytes('docs/technical/mc-live-v1/contracts/game.schema.json', b'{}')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_CHANGED'): self.fixture.validate()

    def test_private_files_models_preparation_and_git_metadata_are_not_exported(self):
        self.export(); value = self.manifest(); names = value['source']['files']
        self.assertNotIn(mc.BINDINGS, names); self.assertNotIn('configs/test-policy.private.json', names)
        self.assertNotIn('models/fixture.bin', names)
        self.assertTrue(all(not n.startswith(('.git/', '.setup/', 'tools/', 'state/')) for n in names))
        self.assertFalse(value['environment_prepared']); self.assertFalse(value['automatic_input_authorized'])
        self.assertEqual(value['real_acceptance_passed'], 0)

    def test_force_tracked_private_configuration_cannot_be_exported(self):
        self.fixture.bytes('configs/forced.private.json', b'fixture private value')
        self.fixture.git('add', '-f', 'configs/forced.private.json')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_PATH_OR_COUNT'): self.export()
        self.assertFalse(self.archive.exists())

    def test_generated_native_game_logs_do_not_change_public_source_or_enter_the_package(self):
        before = mc.source_identity(self.root)
        self.fixture.bytes('game-adapters/minecraft/fabric/logs/latest.log', b'fixture runtime log')
        self.fixture.bytes('game-adapters/minecraft/fabric/crash-reports/crash.txt', b'fixture crash log')
        self.assertEqual(mc.source_identity(self.root), before)
        self.install(); source = mc.source_identity(self.destination)
        for name in ['logs/latest.log', 'crash-reports/crash.txt']:
            path = self.destination / 'game-adapters/minecraft/fabric' / name
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'installed generated log')
        self.assertEqual(mc.source_identity(self.destination), source)

    def test_same_source_produces_the_same_archive_bytes(self):
        first = self.export(); other = self.parent / 'another.zip'
        second = mc.export_source(self.root, other)
        self.assertEqual(first['sha256'], second['sha256']); self.assertEqual(self.archive.read_bytes(), other.read_bytes())

    def test_dirty_source_is_bound_to_bytes_without_claiming_commit_equivalence(self):
        self.fixture.bytes('backend/new-untracked.mjs', b'export default 42;')
        self.install(); source = mc.source_identity(self.destination)
        self.assertIn('backend/new-untracked.mjs', source['files'])
        self.assertFalse(source['commit_alone_describes_workspace'])
        self.assertEqual(source['package_sha256'], mc.sha(self.archive))

    def test_install_writes_separate_source_origin_without_starting_or_preparing(self):
        self.export()
        with patch.object(mc.subprocess, 'check_output', side_effect=AssertionError('no process may run')), \
             patch.object(mc.subprocess, 'Popen', side_effect=AssertionError('no process may run')):
            result = mc.install_source(self.archive, self.destination, mc.sha(self.archive))
            source = mc.source_identity(self.destination)
        self.assertTrue(result['ok']); self.assertFalse(result['environment_prepared'])
        self.assertFalse((self.destination / '.git').exists()); self.assertFalse((self.destination / mc.RECEIPT).exists())
        self.assertFalse((self.destination / '.setup/deployment-origin.json').exists())
        self.assertEqual(source['kind'], 'installed_mc_source_package_with_file_manifest')
        self.assertTrue((self.destination / mc.SOURCE_ORIGIN).is_file())

    def test_installed_cli_reads_the_real_profile_without_git(self):
        self.install()
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(self.destination / 'scripts/mc_runtime.py'),
                                 'describe', '--root', str(self.destination)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['id'], mc.PROFILE_ID)

    def test_installed_source_alone_cannot_start_or_prepare_the_environment(self):
        self.install()
        with self.assertRaises(RuntimeError): mc.base_guard().validate_target(self.destination, check_hardware=False, check_runtime=False)
        self.assertFalse((self.destination / mc.RECEIPT).exists())

    def test_no_git_preparation_and_existing_start_guard_check_full_environment(self):
        self.install(); self.populate_runtime()
        self.fixture.prepare(); value = self.fixture.validate()
        self.assertEqual(value['branch'], 'mc'); self.assertEqual(value['batch_size'], 4)
        self.assertEqual(value['application_profile']['source_kind'], 'installed_mc_source_package_with_file_manifest')
        self.assertFalse((self.destination / '.setup/deployment-origin.json').exists())

    def test_wrong_device_still_fails_for_an_installed_source_package(self):
        self.install(); self.populate_runtime(); self.fixture.prepare()
        self.fixture.gpu = 'NVIDIA GeForce RTX 4090, 49140\n'
        with self.assertRaisesRegex(RuntimeError, 'Inference GPU'): self.fixture.validate()

    def test_foreign_legacy_origin_cannot_override_valid_package_preparation(self):
        self.install(); self.populate_runtime(); self.fixture.prepare()
        self.fixture.write('.setup/deployment-origin.json', {'target':'rtx4090','branch':'deploy/rtx4090','source_commit':'b'*40})
        with self.assertRaisesRegex(RuntimeError, 'another deployment target'): self.fixture.validate()

    def test_same_device_legacy_origin_is_preserved_as_a_separate_historical_record(self):
        self.install(); self.populate_runtime()
        self.fixture.write('.setup/deployment-origin.json', {'target':'rtx3080','branch':'deploy/rtx3080','source_commit':'b'*40})
        before = (self.destination / '.setup/deployment-origin.json').read_bytes()
        self.fixture.prepare(); self.fixture.validate()
        self.assertEqual((self.destination / '.setup/deployment-origin.json').read_bytes(), before)

    def test_editing_installed_source_is_rejected(self):
        self.install(); (self.destination / 'backend/fixture.mjs').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'FILES_CHANGED'): mc.source_identity(self.destination)

    def test_adding_unlisted_installed_source_is_rejected(self):
        self.install(); (self.destination / 'backend/late.mjs').write_bytes(b'new source')
        with self.assertRaisesRegex(RuntimeError, 'FILES_CHANGED'): mc.source_identity(self.destination)

    def test_removing_installed_source_is_rejected(self):
        self.install(); (self.destination / 'backend/fixture.mjs').unlink()
        with self.assertRaisesRegex(RuntimeError, 'FILES_CHANGED'): mc.source_identity(self.destination)

    def test_private_runtime_bindings_do_not_become_public_source(self):
        self.install(); before = mc.source_identity(self.destination)
        (self.destination / 'configs/mc-runtime.private.json').write_bytes(b'fixture private config')
        self.assertEqual(mc.source_identity(self.destination), before)

    def test_copied_source_origin_cannot_authorize_a_different_installation(self):
        self.install(); other = self.parent / 'copied'; shutil.copytree(self.destination, other)
        with self.assertRaisesRegex(RuntimeError, 'ORIGIN_BINDING'): mc.source_identity(other)

    def test_wrong_archive_digest_leaves_destination_absent(self):
        self.export()
        with self.assertRaisesRegex(RuntimeError, 'ARCHIVE_HASH'): mc.install_source(self.archive, self.destination, '0'*64)
        self.assertFalse(self.destination.exists())

    def test_untrusted_manifest_paths_and_windows_names_are_rejected(self):
        self.export(); original = self.archive.read_bytes()
        for name in ['../escape.py', 'C:/escape.py', 'backend\\escape.py', 'backend/CON.txt', 'backend/x.']:
            with self.subTest(name=name):
                self.archive.write_bytes(original)
                def change(value, files):
                    value['source']['files'][name] = mc.digest('fixture'); value['file_sizes'][name] = 0
                    value['source']['snapshot_sha256'] = mc.digest(value['source']['files']); files.append((name, b''))
                self.rewrite(change); self.reject_install('MANIFEST_FILES')

    def test_case_aliases_cannot_collide_on_windows(self):
        self.export()
        def change(value, files):
            name = 'backend/FIXTURE.mjs'; data = b'alias'
            value['source']['files'][name] = mc.hashlib.sha256(data).hexdigest(); value['file_sizes'][name] = len(data)
            value['source']['snapshot_sha256'] = mc.digest(value['source']['files']); files.append((name, data))
        self.rewrite(change); self.reject_install('WINDOWS_ALIAS')

    def test_symlink_zip_member_is_rejected_before_extracting(self):
        self.export(); info = zipfile.ZipInfo('backend/link.mjs'); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.rewrite(extra=(info, b'../../outside')); self.reject_install('MEMBER_TYPE_OR_SIZE')

    def test_duplicate_zip_members_are_rejected(self):
        self.export(); self.rewrite(extra=('backend/fixture.mjs', b'duplicate'))
        self.reject_install('ARCHIVE_MEMBERS')

    def test_duplicate_json_keys_are_rejected(self):
        self.export(); raw = mc.canonical(self.manifest()); raw = b'{"schema_version":1,' + raw[1:]
        self.rewrite(raw_manifest=raw); self.reject_install('DUPLICATE_JSON_KEY')

    def test_central_directory_limit_is_checked_before_zip_index_allocation(self):
        self.export(); data = bytearray(self.archive.read_bytes())
        struct.pack_into('<HH', data, len(data)-22+8, mc.SOURCE_MAX_FILES+2, mc.SOURCE_MAX_FILES+2)
        self.archive.write_bytes(data)
        with patch.object(mc.zipfile, 'ZipFile', side_effect=AssertionError('must not allocate ZIP index')):
            self.reject_install('ARCHIVE_INDEX')

    def test_partial_extraction_hash_failure_cleans_only_its_own_stage(self):
        self.export(); sentinel = self.parent / 'keep.bin'; sentinel.write_bytes(b'untouched')
        def change(value, files):
            value['source']['files']['scripts/mc_runtime.py'] = '0'*64
            value['source']['snapshot_sha256'] = mc.digest(value['source']['files'])
        self.rewrite(change); self.reject_install('ARCHIVE_FILE_HASH')
        self.assertEqual(sentinel.read_bytes(), b'untouched')

    def test_crc_failure_after_partial_extraction_cleans_its_stage(self):
        self.export()
        with zipfile.ZipFile(self.archive) as archive:
            info = archive.getinfo('scripts/mc_runtime.py')
            offset = info.header_offset + 30 + len(info.filename.encode('utf-8')) + len(info.extra)
        data = bytearray(self.archive.read_bytes()); data[offset] ^= 1; self.archive.write_bytes(data)
        self.reject_install('CRC')

    def test_existing_installation_is_never_overwritten(self):
        self.export(); self.destination.mkdir(); sentinel = self.destination / 'keep.bin'; sentinel.write_bytes(b'old installation')
        with self.assertRaisesRegex(RuntimeError, 'DESTINATION_EXISTS'):
            mc.install_source(self.archive, self.destination, mc.sha(self.archive))
        self.assertEqual(sentinel.read_bytes(), b'old installation')

    def test_destination_created_at_commit_is_preserved(self):
        self.export(); original = Path.rename
        def concurrent(path, target):
            if path.name.startswith('.mc-source-install-'):
                self.destination.mkdir(); (self.destination / 'keep.bin').write_bytes(b'concurrent installation')
                raise FileExistsError('fixture race')
            return original(path, target)
        with patch.object(Path, 'rename', concurrent):
            with self.assertRaises(FileExistsError): mc.install_source(self.archive, self.destination, mc.sha(self.archive))
        self.assertEqual((self.destination / 'keep.bin').read_bytes(), b'concurrent installation')
        self.assertFalse(list(self.parent.glob('.mc-source-install-*')))

    def test_source_change_during_export_does_not_publish_an_old_archive(self):
        original = mc.source_identity; calls = 0
        def changing(root):
            nonlocal calls
            calls += 1
            if calls == 2: self.fixture.bytes('backend/fixture.mjs', b'changed during export')
            return original(root)
        with patch.object(mc, 'source_identity', changing):
            with self.assertRaisesRegex(RuntimeError, 'CHANGED_DURING_EXPORT'): self.export()
        self.assertFalse(self.archive.exists()); self.assertFalse(list(self.parent.glob('.mc-source-export-*')))

    def test_an_installed_package_cannot_claim_to_be_a_new_git_export(self):
        self.install()
        with self.assertRaisesRegex(RuntimeError, 'EXPORT_REQUIRES_GIT'):
            mc.export_source(self.destination, self.parent / 'forged-export.zip')

    def test_cli_sanitizes_invalid_archive_errors_without_a_traceback(self):
        self.archive.write_bytes(b'invalid ZIP fixture')
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'scripts/mc_runtime.py'),
            'install-source', '--archive', str(self.archive), '--sha256', mc.sha(self.archive), '--root', str(self.destination)],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 1); value = json.loads(result.stdout)
        self.assertFalse(value['ok']); self.assertFalse(value['services_started']); self.assertFalse(value['models_loaded'])
        self.assertNotIn('Traceback', result.stderr); self.assertNotIn(str(self.parent), result.stdout)
        self.assertFalse(self.destination.exists())

    def test_cli_requires_a_digest_before_attempting_installation(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'scripts/mc_runtime.py'),
            'install-source', '--archive', str(self.archive), '--root', str(self.destination)],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2); self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
