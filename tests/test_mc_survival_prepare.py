"""Archive and build-integrity failure checks; fixtures never launch Minecraft."""
from pathlib import Path
import importlib.util
import io
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mc_survival_prepare', ROOT / 'scripts/mc_prepare_survival.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SurvivalPreparationTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'outputs/mc-validation/round-009/prepare-fixtures'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name).resolve()
        assert self.root.is_relative_to(base.resolve())
        self.cache = self.root / '.setup/mc-survival'
        self.cache.mkdir(parents=True)
        self.patches = self.root / 'game-adapters/minecraft/survival/controlled-patches.json'
        self.patches.parent.mkdir(parents=True)
        self.patches.write_text('[]', encoding='utf-8')
        self.source = self.cache / 'source.zip'
        self.archive([('root/src/main/java/Test.java', b'class Test {}'), ('root/LICENSE', b'fixture license')])
        self.artifact = self.cache / 'artifact.jar'
        with zipfile.ZipFile(self.artifact, 'w'):
            pass
        self.lock = {'source_commit': 'fixture', 'source': self.input_spec(self.source), 'compile_artifact': self.input_spec(self.artifact), 'nested': []}
        (self.root / 'configs').mkdir()
        self.save_lock()
        self.audit = self.root / 'configs/mc-executor-source-audit.json'
        self.audit.write_text(json.dumps({'commit': 'fixture', 'reviewed_source_files': []}), encoding='utf-8')
        self.mocks = [patch.object(module, 'ROOT', self.root), patch.object(module, 'CACHE', self.cache),
                      patch.object(module, 'PATCHES', self.patches), patch.object(module, 'require_branch')]
        for item in self.mocks:
            item.start()

    def tearDown(self):
        for item in reversed(self.mocks):
            item.stop()
        self.temp.cleanup()

    def input_spec(self, path):
        return {'file': path.name, 'sha256': module.digest(path.read_bytes()), 'max_bytes': 2 * 1024 * 1024}

    def save_lock(self):
        (self.root / 'configs/mc-survival-build.lock.json').write_text(json.dumps(self.lock), encoding='utf-8')

    def archive(self, entries):
        with zipfile.ZipFile(self.source, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)

    def test_offline_prepare_then_verify_and_reprepare_has_exact_tree(self):
        first = module.prepare(True)
        self.assertEqual(first, module.verify())
        self.assertEqual(first, module.prepare(True))
        self.assertFalse(first['automatic_input_authorized'])

    def test_corrupt_cached_input_is_refused_without_download(self):
        self.source.write_bytes(b'corrupted fixture')
        with self.assertRaisesRegex(ValueError, 'HASH_OR_SIZE'):
            module.prepare(True)

    def test_missing_cached_input_in_offline_mode_is_refused(self):
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, 'INPUT_MISSING'):
            module.prepare(True)

    def test_archive_parent_traversal_and_windows_paths_are_refused(self):
        for name in ['root/../escape', '/absolute/escape', 'root/src/main/C:evil', 'root/src/main/back\\slash']:
            with self.subTest(name=name):
                self.archive([(name.replace(chr(92), '/'), b'bad')])
                if chr(92) in name:
                    normalized = name.replace(chr(92), '/').encode()
                    self.source.write_bytes(self.source.read_bytes().replace(normalized, name.encode()))
                with self.assertRaisesRegex(ValueError, 'ARCHIVE_PATH'):
                    module.extract_sources(self.source, self.root / 'extract')

    def test_archive_case_aliases_are_refused_on_windows(self):
        self.archive([('root/src/main/Test.java', b'a'), ('root/src/main/test.java', b'b')])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_OR_LINK'):
            module.extract_sources(self.source, self.root / 'extract')

    def test_archive_links_are_refused_without_creating_a_symlink(self):
        entry = zipfile.ZipInfo('root/src/main/link')
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        self.archive([(entry, b'../../escape')])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_OR_LINK'):
            module.extract_sources(self.source, self.root / 'extract')

    def test_archive_entry_limit(self):
        self.archive([(f'root/ignored-{i}', b'') for i in range(1001)])
        with self.assertRaisesRegex(ValueError, 'ARCHIVE_LIMIT'):
            module.extract_sources(self.source, self.root / 'extract')

    def test_changed_or_extra_generated_source_prevents_build_verification(self):
        receipt = module.prepare(True)
        directory = self.cache / receipt['generated_directory']
        target = directory / 'src/main/java/Test.java'
        target.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'GENERATED_CHANGED'):
            module.verify()
        module.prepare(True)
        (directory / 'Extra.java').write_text('unexpected', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'GENERATED_CHANGED'):
            module.verify()
        with self.assertRaisesRegex(ValueError, 'GENERATED_EXTRA_FILES'):
            module.prepare(True)

    def test_patch_drift_stops_build_instead_of_compiling_old_output(self):
        module.prepare(True)
        self.patches.write_text('[{"id":"wrong","path":"src/main/java/Test.java","before":"missing","after":"new"}]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'PREPARATION_STALE'):
            module.verify()
        with self.assertRaisesRegex(ValueError, 'PATCH_CONTEXT'):
            module.prepare(True)

    def test_patch_context_is_exact_and_paths_stay_inside_source(self):
        self.patches.write_text('[{"id":"escape","path":"../elsewhere","before":"a","after":"b"}]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'PATCH_PATH'):
            module.prepare(True)

    def test_prior_source_audit_hash_is_mandatory(self):
        self.audit.write_text(json.dumps({'commit': 'fixture', 'reviewed_source_files': [{'path': 'src/main/java/Test.java', 'sha256': '0' * 64}]}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'SOURCE_AUDIT'):
            module.prepare(True)

    def test_embedded_dependencies_are_recursively_hashed(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, 'w') as archive:
            archive.writestr('native.dll', b'fixture, not a DLL')
        with zipfile.ZipFile(self.artifact, 'w') as archive:
            archive.writestr('META-INF/jars/child.jar', inner.getvalue())
        self.lock['compile_artifact'] = self.input_spec(self.artifact)
        self.save_lock()
        receipt = module.prepare(True)
        self.assertEqual(receipt['embedded_artifacts'][0]['sha256'], module.digest(inner.getvalue()))
        self.assertEqual(receipt, module.verify())

    def test_cached_input_destination_cannot_escape(self):
        self.lock['source']['file'] = '../outside.zip'
        self.save_lock()
        with self.assertRaisesRegex(ValueError, 'INPUT_PATH'):
            module.prepare(True)

    def test_modified_local_module_metadata_is_refused_before_build(self):
        child = io.BytesIO()
        with zipfile.ZipFile(child, 'w') as archive:
            archive.writestr('fabric.mod.json', '{"id":"baritone","version":"fixture"}')
        with zipfile.ZipFile(self.artifact, 'w') as archive:
            archive.writestr('META-INF/jars/baritone.jar', child.getvalue())
        self.lock['compile_artifact'] = self.input_spec(self.artifact)
        self.lock['nested'] = [{'entry': 'META-INF/jars/baritone.jar', 'file': 'baritone.jar',
                                'sha256': module.digest(child.getvalue()), 'max_bytes': 1024 * 1024}]
        self.save_lock()
        receipt = module.prepare(True)
        pom = next(name for name in receipt['local_module_hashes'] if name.endswith('.pom'))
        (self.cache / pom).write_text('modified fixture metadata', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'LOCAL_MODULE_CHANGED'):
            module.verify()


if __name__ == '__main__':
    unittest.main()
