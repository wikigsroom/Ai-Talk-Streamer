"""MC preparation uses a real temporary Git checkout and fixed native-probe doubles.

No fake executable is run, no model/service is started and no real device is used.
The fixtures prove file/source/lifecycle enforcement, not production readiness.
"""
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
REAL_OUTPUT = subprocess.check_output
spec = importlib.util.spec_from_file_location('mc_deployment_test', ROOT / 'scripts/mc_deployment.py')
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)
guard = mc.base_guard()


class HashCompatibilityTests(unittest.TestCase):
    def test_python310_file_hashes_without_newer_standard_library_helpers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '原生校验.bin'
            # Exercise an empty file and a binary file larger than the read buffer.
            # Disable the newer helper even when the test host has Python >=3.11.
            with patch.object(mc.hashlib, 'file_digest', None, create=True):
                for data in [b'', bytes(range(256)) * 8193]:
                    with self.subTest(bytes=len(data)):
                        path.write_bytes(data)
                        self.assertEqual(mc.sha(path), hashlib.sha256(data).hexdigest())
                        self.assertEqual(path.read_bytes(), data)


@unittest.skipUnless(sys.platform == 'win32', 'Native Windows junction check')
class PathCompatibilityTests(unittest.TestCase):
    def test_native_junction_is_rejected_even_when_target_stays_in_installation(self):
        import _winapi
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / 'target'; target.mkdir()
            source = target / 'source.json'; source.write_bytes(b'original')
            link = root / 'linked'
            try:
                _winapi.CreateJunction(str(target), str(link))
                self.assertEqual(link.lstat().st_reparse_tag, stat.IO_REPARSE_TAG_MOUNT_POINT)
                with self.assertRaisesRegex(mc.PreparationError, 'MC_PREPARATION_LINK'):
                    mc.inside(root, 'linked/source.json')
            finally:
                if link.exists():
                    self.assertEqual(link.lstat().st_reparse_tag, stat.IO_REPARSE_TAG_MOUNT_POINT)
                    os.rmdir(link)
            self.assertEqual(source.read_bytes(), b'original')


class McDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'installation'
        self.root.mkdir()
        for name in [mc.PROFILE, '.gitignore', 'configs/deployment-targets.json', 'configs/deployment-target.json',
                     'configs/releases/current.json', 'configs/layouts/mc-landscape-v1.json',
                     'configs/mc-neoforge-client.lock.json', 'configs/mc-neoforge-bridge.lock.json',
                     'backend/dsh-bridge/package.json', 'backend/dsh-bridge/package-lock.json',
                     'backend/dsh-bridge/humanity-port.mjs']:
            self.bytes(name, (ROOT / name).read_bytes())
        runtime_lock = self.load_root('configs/releases/rtx3080-k02-runtime-lock.json')
        data = b'fixture model, never loaded'
        self.bytes('models/fixture.bin', data)
        reference = b'fixture reference, never played'
        self.bytes('assets/voices/fixture.wav', reference)
        runtime_lock['model_files'] = [{'path':'models/fixture.bin', 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}]
        runtime_lock['reference_sha256'] = hashlib.sha256(reference).hexdigest()
        self.write('configs/releases/rtx3080-k02-runtime-lock.json', runtime_lock)
        self.write('configs/livetalking.yaml', {'model':'musetalk', 'batch_size':4, 'fps':25})
        self.write('configs/hardware-profile.json', {'preset':'rtx3080-k02-batch4'})
        self.write('configs/resident-tts.json', {'default_voice_id':'O07', 'voices':{
            'O07':{'precision':'FP16'}, 'F07':{'precision':'FP32'}},
            'reference_audio':'assets/voices/fixture.wav', 'reference_sha256':runtime_lock['reference_sha256']})
        self.write('configs/dsh-active-policy.json', {'policy_file':'configs/test-policy.private.json'})
        self.write('configs/test-policy.private.json', {'deployment':{'state_relative_path':'state/female-a-3080-k02',
            'dsh_home_relative_path':'state/female-a-3080-k02/dsh-home', 'bridge_port':3092, 'management_port':3091}})
        self.bytes('.gitignore', (self.root / '.gitignore').read_bytes() + b'\n/configs/test-policy.private.json\n')
        for name in ['readiness', 'asset-check']:
            self.write('.setup/' + name + '.result.json', {'ok':True})
        self.write('.setup/deployment-origin.json', {'target':'rtx3080', 'branch':'deploy/rtx3080', 'source_commit':'a' * 40})
        for name in ['package.json', 'package-lock.json']:
            self.bytes('tools/dsh/' + name, (self.root / 'backend/dsh-bridge' / name).read_bytes())
        for name, version in [('@deepseek-ai/dsh','0.2.0-rc.2'), ('deepseek-harness-humanity','0.1.17')]:
            self.write('tools/dsh/node_modules/' + name + '/package.json', {'version':version})
        prefix = 'tools/dsh/node_modules/deepseek-harness-humanity/lib/'
        self.bytes(prefix + 'stream-connector.mjs', (self.root / 'backend/dsh-bridge/humanity-port.mjs').read_bytes())
        self.bytes(prefix + 'index.mjs', b'fixture patched module')
        self.write('.setup/dsh-humanity-patch.json', {'base_version':'0.1.17', 'connector_version':'stream-humanity-v1',
            'connector_sha256':mc.sha(self.root / (prefix + 'stream-connector.mjs')),
            'files':[{'file':'index.mjs', 'patched_sha256':mc.sha(self.root / (prefix + 'index.mjs'))}]})
        self.write(mc.BINDINGS, {'schema_version':1, 'profile':mc.PROFILE,
            'executables':{name:'tools/native/' + name + '.exe' for name in ['node','python','java']}})
        for name in ['node','python','java']:
            self.bytes('tools/native/' + name + '.exe', ('fixture ' + name).encode())
        self.write_client_fixture_receipt()
        self.bytes('backend/fixture.mjs', b'export const fixture = true;\n')
        self.write('configs/mc-player.private.json', {'schema_version':2,'mode':'singleplayer','world':None})
        self.bytes('integration/dsh_bridge.py', b'# source-owned proxy fixture\n')
        self.bytes('src/LiveTalking/server/dsh_bridge.py', b'# source-owned proxy fixture\n')
        self.git('init', '-b', 'mc')
        self.git('add', '.')
        self.commit('temporary fixture source')
        import mc_runtime_projection as projection
        with projection.applied(self.root,mc.source_identity(self.root),self.root/'.setup/projection-fixture-backup'):
            pass
        self.node_version = '24.22.1'
        self.gpu = 'NVIDIA GeForce RTX 3080, 10240\n'

    def write_client_fixture_receipt(self):
        # Explicit NeoForge file doubles: none of the fixture binaries are run.
        from mc_neoforge_runtime_fixture import install
        install(self.root)

    def load_root(self, name):
        return json.loads((ROOT / name).read_text(encoding='utf-8-sig'))

    def bytes(self, name, data):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)

    def write(self, name, value):
        self.bytes(name, (json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8'))

    def read(self, name):
        return json.loads((self.root / name).read_text(encoding='utf-8-sig'))

    def git(self, *args):
        return REAL_OUTPUT(['git', *args], cwd=self.root, stderr=subprocess.STDOUT)

    def commit(self, text):
        self.git('-c','user.name=MC test','-c','user.email=mc-test@example.invalid',
                 '-c','commit.gpgsign=false','commit','-m',text)

    def probe(self, argv, **kwargs):
        name = Path(argv[0]).name.lower()
        if name == 'nvidia-smi':
            return self.gpu if kwargs.get('text') else self.gpu.encode()
        if name == 'node.exe':
            return json.dumps({'version':self.node_version, 'platform':'win32','arch':'x64','sqlite':True}).encode()
        if name == 'python.exe':
            return b'{"version":"3.10.22","platform":"win32","bits":64}'
        if name == 'java.exe':
            return b'    os.arch = amd64\nopenjdk version "21.0.11" 2026-04-21\n'
        return REAL_OUTPUT(argv, **kwargs)

    def prepare(self, **kwargs):
        with patch.object(mc.subprocess, 'check_output', side_effect=self.probe), patch.object(mc, 'idle'):
            return mc.prepare(self.root, **kwargs)

    def validate(self):
        with patch.object(mc.subprocess, 'check_output', side_effect=self.probe):
            return guard.validate_target(self.root)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix():mc.sha(p) for p in self.root.rglob('*')
                if p.is_file() and '.git' not in p.relative_to(self.root).parts}

    def test_mc_requires_real_preparation_and_preserves_legacy_origin(self):
        origin = (self.root / '.setup/deployment-origin.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Git branch'):
            self.validate()
        result = self.prepare()
        self.assertFalse(result['automatic_input_authorized'])
        self.assertEqual(result['real_acceptance_passed'], 0)
        self.assertEqual(origin, (self.root / '.setup/deployment-origin.json').read_bytes())
        value = self.validate()
        self.assertEqual((value['target'],value['branch'],value['batch_size']), ('rtx3080','mc',4))
        self.assertEqual(value['application_profile']['profile_id'], mc.PROFILE_ID)

    def test_preflight_and_start_guard_are_read_only(self):
        before = self.snapshot()
        with patch.object(mc.subprocess, 'check_output', side_effect=self.probe), patch.object(mc, 'idle'):
            report, _ = mc.preflight(self.root)
        self.assertTrue(report['ok'], report)
        self.assertEqual(self.snapshot(), before)
        self.prepare(); before = self.snapshot(); self.validate()
        self.assertEqual(self.snapshot(), before)

    def test_game_installation_is_reported_when_inference_configuration_is_missing(self):
        (self.root / 'configs/livetalking.yaml').unlink()
        with patch.object(mc.subprocess, 'check_output', side_effect=self.probe), patch.object(mc, 'idle'):
            report, _ = mc.preflight(self.root)
        checks = {row['name']:row for row in report['checks']}
        self.assertTrue(checks['game_files']['ok'])
        self.assertFalse(checks['runtime_files']['ok'])
        self.assertFalse(report['ok'])
        self.assertFalse((self.root / mc.RECEIPT).exists())

    def test_missing_native_client_cannot_receive_application_preparation(self):
        (self.root/'.setup/mc-neoforge-installation.json').unlink()
        with self.assertRaisesRegex(mc.PreparationError, 'PREFLIGHT_FAILED'):
            self.prepare()
        self.assertFalse((self.root/mc.RECEIPT).exists())

    def test_changed_native_client_invalidates_application_preparation(self):
        self.prepare()
        from mc_neoforge import HOME
        self.bytes(HOME + '/work/mods/fixture-0.jar', b'changed client mod')
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_FILE_MISSING_OR_SIZE'):
            self.validate()

    def test_new_untracked_runtime_source_is_part_of_the_proof(self):
        self.bytes('backend/new-untracked.mjs', b'export default 1;')
        self.bytes('scripts/new-runtime-resource.yaml', b'fixture: true\n')
        self.prepare()
        source = self.read(mc.RECEIPT)['source']
        self.assertIn('backend/new-untracked.mjs', source['files'])
        self.assertIn('scripts/new-runtime-resource.yaml', source['files'])
        self.assertFalse(source['commit_alone_describes_workspace'])
        self.assertEqual(source['snapshot_sha256'], mc.digest(source['files']))

    def test_source_edit_invalidates_preparation(self):
        self.prepare(); self.bytes('backend/fixture.mjs', b'changed')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_CHANGED'): self.validate()

    def test_source_addition_invalidates_preparation(self):
        self.prepare(); self.bytes('web/late-new.js', b'new script')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_CHANGED'): self.validate()

    def test_source_removal_invalidates_preparation(self):
        self.prepare(); (self.root / 'backend/fixture.mjs').unlink()
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_MISSING'): self.validate()

    def test_new_commit_invalidates_old_source_identity(self):
        self.prepare(); self.bytes('notes.txt', b'unrelated commit')
        self.git('add','notes.txt'); self.commit('new commit')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_CHANGED'): self.validate()

    def test_other_branch_cannot_prepare(self):
        self.git('switch','-c','other')
        with self.assertRaisesRegex(mc.PreparationError, 'PREFLIGHT_FAILED'): self.prepare()
        self.assertFalse((self.root / mc.RECEIPT).exists())

    def test_detached_source_cannot_prepare(self):
        self.git('checkout','--detach')
        with self.assertRaisesRegex(mc.PreparationError, 'PREFLIGHT_FAILED'): self.prepare()

    def test_copied_preparation_cannot_authorize_a_different_installation(self):
        self.prepare(); other = self.root.parent / 'other-installation'
        shutil.copytree(self.root, other)
        with self.assertRaisesRegex(mc.PreparationError, 'RECORD_BINDING'):
            mc.validate_prepared(other, self.read('configs/deployment-target.json'))

    def test_copied_runtime_cannot_reuse_git_preparation(self):
        self.prepare(); (self.root / '.git').rename(self.root / '.git-saved')
        with self.assertRaisesRegex(RuntimeError, 'REQUIRES_MC_SOURCE_CHECKOUT'): self.validate()

    def test_runtime_config_change_requires_repreparation(self):
        self.prepare(); config = self.read('configs/livetalking.yaml'); config['extra'] = 'new'
        self.write('configs/livetalking.yaml', config)
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_CHANGED'): self.validate()

    def test_model_bytes_are_checked_even_with_the_same_size(self):
        self.prepare(); path = self.root / 'models/fixture.bin'
        self.bytes('models/fixture.bin', b'x' * path.stat().st_size)
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_HASH'): self.validate()

    def test_missing_archive_receipt_does_not_hide_missing_model(self):
        lock = self.read('configs/releases/rtx3080-k02-runtime-lock.json')
        lock['model_files'].append({'path':'models/benchmark-manifest.json', 'bytes':2,
                                   'sha256':hashlib.sha256(b'{}').hexdigest()})
        self.write('configs/releases/rtx3080-k02-runtime-lock.json', lock)
        self.prepare(); self.validate()
        self.assertFalse((self.root/'models/benchmark-manifest.json').exists())
        (self.root/'models/fixture.bin').unlink()
        with self.assertRaisesRegex(RuntimeError, 'MODEL_MISSING_OR_SIZE'): mc.runtime_files(self.root)

    def test_dsh_package_copy_must_match_the_source_lock(self):
        self.prepare(); self.bytes('tools/dsh/package-lock.json', b'{}')
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_HASH'): self.validate()

    def test_local_world_target_change_requires_new_environment_preparation(self):
        self.prepare()
        self.write('configs/mc-player.private.json', {'schema_version':2,'mode':'singleplayer','world':'MC Live Offline 083'})
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_CHANGED'):
            self.validate()

    def test_installed_humanity_patch_is_verified(self):
        self.prepare(); self.bytes('tools/dsh/node_modules/deepseek-harness-humanity/lib/index.mjs', b'changed')
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_HASH'): self.validate()

    def test_rebuilt_game_artifact_invalidates_environment_proof(self):
        self.prepare()
        from mc_neoforge import CONTROLLER_JAR
        name = CONTROLLER_JAR
        with (self.root / name).open('ab') as stream: stream.write(b'new build')
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_FILE_MISSING_OR_SIZE'): self.validate()

    def test_jre_modules_change_invalidates_preparation_with_unchanged_java_executable(self):
        self.prepare()
        receipt = self.read('.setup/mc-neoforge-installation.json')
        path = Path(receipt['source']) / '.minecraft/versions/MC-Friends-S1-r001/runtime/java21/lib/modules'
        path.write_bytes(b'CHANGED JRE MODULES')
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_CHANGED'):
            self.validate()

    def test_engineering_game_endpoint_cannot_receive_application_preparation(self):
        from mc_neoforge import HOME
        self.write(HOME + '/work/config/ai-talk-streamer-bridge.json',
                   {'enabled':True,'endpoint':'ws://127.0.0.1:18974/api/dsh/game/bridge'})
        with self.assertRaisesRegex(mc.PreparationError, 'PREFLIGHT_FAILED'):
            self.prepare()
        self.assertFalse((self.root / mc.RECEIPT).exists())

    def test_changed_executable_is_rejected_before_start(self):
        self.prepare(); self.bytes('tools/native/node.exe', b'other executable')
        with self.assertRaisesRegex(RuntimeError, 'BINARY_CHANGED'): self.validate()

    def test_actual_version_is_rechecked_at_start(self):
        self.prepare(); self.node_version = '24.19.0'
        with self.assertRaisesRegex(RuntimeError, 'NATIVE_NODE'): self.validate()

    def test_wrong_node_version_prevents_receipt_creation(self):
        self.node_version = '24.19.0'
        with self.assertRaisesRegex(mc.PreparationError, 'PREFLIGHT_FAILED'): self.prepare()
        self.assertFalse((self.root / mc.RECEIPT).exists())

    def test_wrong_device_stays_rejected_with_a_valid_mc_proof(self):
        self.prepare(); self.gpu = 'NVIDIA GeForce RTX 4090, 49140\n'
        with self.assertRaisesRegex(RuntimeError, 'Inference GPU'): self.validate()

    def test_wrong_batch_stays_rejected(self):
        self.write('configs/livetalking.yaml', {'model':'musetalk','batch_size':8,'fps':25})
        with self.assertRaisesRegex(mc.PreparationError, 'PREFLIGHT_FAILED'): self.prepare()

    def test_other_device_state_stays_rejected(self):
        policy = self.read('configs/test-policy.private.json')
        policy['deployment']['state_relative_path'] = 'state/female-a-4090'
        self.write('configs/test-policy.private.json', policy)
        with self.assertRaisesRegex(mc.PreparationError, 'PREFLIGHT_FAILED'): self.prepare()

    def test_missing_or_changed_layout_fails_before_native_probes(self):
        self.bytes('configs/layouts/mc-landscape-v1.json', b'{}')
        with patch.object(mc, 'native_binaries') as native:
            report, _ = mc.preflight(self.root)
        self.assertFalse(report['ok']); native.assert_not_called()
        self.assertEqual(report['checks'], [{'name':'profile','ok':False,'code':'MC_PROFILE_LAYOUT'}])

    def test_neoforge_version_drift_is_rejected(self):
        path = 'configs/mc-neoforge-client.lock.json'
        lock = self.read(path); lock['neoforge'] = '21.1.247'; self.write(path, lock)
        with self.assertRaisesRegex(mc.PreparationError, 'NEOFORGE_LOCK'): mc.load_profile(self.root)

    def test_damaged_or_falsely_authoritative_record_is_rejected(self):
        self.prepare(); record = self.read(mc.RECEIPT)
        for value, code in [([], 'RECORD_BINDING'), ({**record,'automatic_input_authorized':True}, 'NOT_EXECUTION_AUTHORITY'),
                            ({**record,'real_acceptance_passed':68}, 'NOT_EXECUTION_AUTHORITY')]:
            with self.subTest(code=code):
                self.write(mc.RECEIPT, value)
                with self.assertRaisesRegex(RuntimeError, code): self.validate()

    def test_preparation_lock_blocks_start_and_is_not_removed_by_another_preparer(self):
        self.prepare(); self.bytes(mc.PREPARING, b'owned by another preparation')
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'IN_PROGRESS'): self.validate()
        with self.assertRaisesRegex(mc.PreparationError, 'ALREADY_RUNNING'): self.prepare(refresh=True)
        self.assert_only_operation_record_changed(before)

    def test_failed_refresh_preserves_prior_receipt_and_origin(self):
        self.prepare(); before = self.snapshot(); self.node_version = '24.19.0'
        with self.assertRaisesRegex(mc.PreparationError, 'PREFLIGHT_FAILED'): self.prepare(refresh=True)
        self.assert_only_operation_record_changed(before)

    def assert_only_operation_record_changed(self, before):
        import native_operation
        after = self.snapshot()
        name = native_operation.LOCK
        self.assertNotEqual(after[name], before[name])
        self.assertEqual({k:v for k,v in after.items() if k != name},
                         {k:v for k,v in before.items() if k != name})
        value = native_operation.status(self.root)
        self.assertEqual(value['phase'], 'ROLLED_BACK')
        self.assertEqual(value['processes'], [])
        self.assertFalse(value['busy'])

    def test_native_operation_gate_rejects_prepare_before_any_preflight(self):
        import native_operation
        import threading
        errors = []
        def contend():
            try:
                mc.prepare(self.root)
            except native_operation.OperationError as error:
                errors.append(str(error))
        with native_operation.operation(self.root, 'studio-starting'), patch.object(mc, 'preflight') as preflight:
            thread = threading.Thread(target=contend)
            thread.start(); thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, ['MC_NATIVE_OPERATION_BUSY'])
            preflight.assert_not_called()
            self.assertFalse((self.root / mc.PREPARING).exists())
            self.assertFalse((self.root / mc.RECEIPT).exists())

    def test_refresh_archives_old_proof_without_rewriting_device_origin(self):
        self.prepare(); old = (self.root / mc.RECEIPT).read_bytes()
        origin = (self.root / '.setup/deployment-origin.json').read_bytes()
        self.bytes('backend/fixture.mjs', b'updated source')
        self.prepare(refresh=True); self.validate()
        history = list((self.root / '.setup/mc-native-history').glob('*.json'))
        self.assertEqual(len(history), 1); self.assertEqual(history[0].read_bytes(), old)
        self.assertEqual((self.root / '.setup/deployment-origin.json').read_bytes(), origin)

    def test_workspace_change_during_prepare_cannot_issue_old_proof(self):
        original = mc.source_identity
        count = 0
        def changing(root):
            nonlocal count
            count += 1
            if count == 2: self.bytes('backend/fixture.mjs', b'concurrent edit')
            return original(root)
        with patch.object(mc, 'source_identity', side_effect=changing):
            with self.assertRaisesRegex(mc.PreparationError, 'CHANGED_DURING_CHECK'): self.prepare()
        self.assertFalse((self.root / mc.RECEIPT).exists())

    def test_busy_port_is_reported_without_touching_processes(self):
        with patch.object(mc.socket, 'socket') as socket, patch('psutil.process_iter') as processes:
            socket.return_value.__enter__.return_value.connect_ex.return_value = 0
            with self.assertRaisesRegex(mc.PreparationError, 'PORT_BUSY'): mc.idle(self.root, [3092])
            processes.assert_not_called()

    def test_closing_project_process_blocks_prepare_but_other_apps_are_left_alone(self):
        own = SimpleNamespace(info={'cmdline':['node.exe',str(self.root / 'backend/dsh-bridge/server.mjs'),str(self.root)]})
        other = SimpleNamespace(info={'cmdline':['node.exe',str(self.root.parent / 'unrelated/backend/dsh-bridge/server.mjs')]})
        with patch.object(mc.socket, 'socket') as socket:
            socket.return_value.__enter__.return_value.connect_ex.return_value = 1
            with patch('psutil.process_iter', return_value=[other]): mc.idle(self.root, [3092])
            with patch('psutil.process_iter', return_value=[other,own]):
                with self.assertRaisesRegex(mc.PreparationError, 'PROJECT_PROCESS_ACTIVE'): mc.idle(self.root, [3092])

    def test_paths_cannot_escape_the_selected_installation(self):
        for name in ['../private.json','/outside.json','C:/outside.json','configs/../outside.json','configs\\outside.json']:
            with self.subTest(name=name):
                with self.assertRaisesRegex(mc.PreparationError, 'PATH'): mc.inside(self.root, name)

    def test_cli_reports_configuration_failure_as_json_without_private_values(self):
        folder = self.root.parent / 'unprepared'; folder.mkdir()
        result = subprocess.run([sys.executable,'-X','utf8',str(ROOT / 'scripts/mc_runtime.py'),
                                 'preflight','--root',str(folder)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,1)
        value = json.loads(result.stdout)
        self.assertFalse(value['ok']); self.assertFalse(value['services_started'])
        self.assertFalse(value['models_loaded']); self.assertEqual(list(folder.iterdir()),[])
        self.assertNotIn(str(folder), result.stdout); self.assertNotIn('Traceback',result.stderr)


if __name__ == '__main__':
    unittest.main()
