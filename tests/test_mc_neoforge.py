"""Offline identity, immutable supplied pack and isolated native launch-plan checks.

Files below are explicit tiny fixtures, not Minecraft, NeoForge or a live server.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import mc_neoforge as mc


class NativePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name); self.root = self.folder / 'project'; self.root.mkdir()
        self.source = self.folder / 'supplied'; self.instance = self.source / '.minecraft/versions/MC-Friends-S1-r001'
        self.instance.mkdir(parents=True); (self.root / 'configs').mkdir()
        self.files = []
        def put(relative, data):
            path = self.source / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            self.files.append({'path': relative, 'bytes': len(data), 'sha256': mc.sha(path)})
            return path
        self.put = put
        for i in range(319):
            put(f'.minecraft/versions/MC-Friends-S1-r001/mods/fixture-{i}.jar', str(i).encode())
        base = {'libraries': [], 'assetIndex': {'id': '17'}, 'arguments': {'jvm': ['-cp', '${classpath}'],
            'game': ['--username', '${auth_player_name}', '--uuid', '${auth_uuid}', '--accessToken', '${auth_access_token}',
                     '--gameDir', '${game_directory}', '--userType', '${user_type}']}}
        neo = {'libraries': [], 'mainClass': 'cpw.mods.bootstraplauncher.BootstrapLauncher',
               'arguments': {'jvm': [], 'game': ['--fml.neoForgeVersion', '21.1.248']}}
        put('.minecraft/versions/1.21.1/1.21.1.json', json.dumps(base).encode())
        put('.minecraft/versions/MC-Friends-S1-r001/MC-Friends-S1-r001.json', json.dumps(neo).encode())
        put('.minecraft/versions/MC-Friends-S1-r001/MC-Friends-S1-r001.jar', b'fixture-not-a-game')
        put('.minecraft/versions/MC-Friends-S1-r001/MC-Friends-S1-r001-natives/test.dll', b'fixture')
        for name in ['command_history.txt', 'servers.dat', 'options.txt', 'PCL/accounts.json', 'saves/old-world/level.dat']:
            path = self.instance / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('DO_NOT_IMPORT', encoding='utf-8')
        self.lock = {'schema_version': 1, 'username': 'NAIMEI', 'authentication': 'offline', 'minecraft': '1.21.1',
            'neoforge': '21.1.248', 'mod_count': 319, 'version_id': 'MC-Friends-S1-r001', 'files': self.files}
        self.write_lock()

    def write_lock(self):
        (self.root / mc.LOCK).write_text(json.dumps(self.lock), encoding='utf-8')

    def prepared(self):
        record = mc.prepare(self.root, self.source); work = Path(record['work'])
        jar = work / 'mods/ai-talk-streamer-native-neoforge-0.1.0.jar'; jar.write_bytes(b'explicit-argument-fixture')
        receipt = self.root / '.setup/mc-neoforge-probe-build.json'
        receipt.write_text(json.dumps({'jar': jar.relative_to(self.root).as_posix(), 'sha256': mc.sha(jar), 'sources': {}}), encoding='utf-8')
        return work

    def test_prepare_never_imports_launcher_accounts_history_saves_or_old_servers(self):
        before = {p: mc.sha(p) for p in self.source.rglob('*') if p.is_file()}
        record = mc.prepare(self.root, self.source); work = Path(record['work'])
        for name in ['command_history.txt', 'servers.dat', 'PCL/accounts.json', 'saves']:
            self.assertFalse((work / name).exists())
        self.assertNotIn('DO_NOT_IMPORT', (work / 'options.txt').read_text())
        self.assertEqual(before, {p: mc.sha(p) for p in self.source.rglob('*') if p.is_file()})
        self.assertEqual(record['mod_count'], 319)
        self.assertFalse(record['automatic_input_authorized']); self.assertFalse(record['full_application_prepared'])
        self.assertEqual(mc.read(work/'config/ai-talk-streamer-bridge.json'),
                         {'enabled':True,'endpoint':'ws://127.0.0.1:3092/api/dsh/game/bridge'})

    def test_source_mod_tampering_prevents_any_installation(self):
        (self.instance / 'mods/fixture-0.jar').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'SUPPLIED_FILE_CHANGED'):
            mc.prepare(self.root, self.source)
        self.assertFalse((self.root / mc.HOME).exists())

    def test_partial_modern_defaults_get_data_version_before_becoming_complete_options(self):
        defaults = self.instance / 'configureddefaults/options.txt'; defaults.parent.mkdir()
        original = 'autoJump:false\nkey_key.inventoryessentials.sort_inventory:key.keyboard.unknown\n'
        defaults.write_text(original, encoding='utf-8')
        record = mc.prepare(self.root, self.source); work = Path(record['work'])
        for target in [work / 'options.txt', work / 'configureddefaults/options.txt']:
            values = dict(line.split(':', 1) for line in target.read_text(encoding='utf-8').splitlines())
            self.assertEqual(values['version'], '3955')
            self.assertEqual(values['onboardAccessibility'], 'false')
            self.assertEqual(values['rawMouseInput'], 'false')
            self.assertEqual(values['key_key.inventoryessentials.sort_inventory'], 'key.keyboard.unknown')
        self.assertEqual(defaults.read_text(encoding='utf-8'), original)

    def test_extra_original_mod_is_not_silently_accepted(self):
        (self.instance / 'mods/unpinned.jar').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'MOD_SET_CHANGED'):
            mc.prepare(self.root, self.source)

    def test_module_named_mods_directory_is_not_counted_as_a_game_mod(self):
        self.put('.minecraft/libraries/cpw/mods/bootstraplauncher/2.0.2/bootstraplauncher-2.0.2.jar', b'fixture')
        self.write_lock(); self.assertEqual(mc.package(self.root, self.source)[0]['mod_count'], 319)

    def test_pin_cannot_escape_the_supplied_directory(self):
        self.files.insert(0, {'path': '../outside', 'bytes': 1, 'sha256': '0' * 64}); self.write_lock()
        with self.assertRaisesRegex(ValueError, 'PIN_PATH'):
            mc.prepare(self.root, self.source)

    def test_offline_name_change_is_rejected_instead_of_using_another_account(self):
        self.lock['username'] = 'wikig'; self.write_lock()
        with self.assertRaisesRegex(ValueError, 'NEOFORGE_LOCK'):
            mc.prepare(self.root, self.source)

    def test_repeat_prepare_preserves_owned_saves_and_settings(self):
        work = self.prepared(); save = work / 'saves/own/level.dat'; save.parent.mkdir(parents=True)
        save.write_bytes(b'own-save'); (work / 'options.txt').write_text('own-settings', encoding='utf-8')
        bridge = work/'config/ai-talk-streamer-bridge.json'
        bridge.write_text(json.dumps({'enabled':False}), encoding='utf-8')
        mc.prepare(self.root, self.source)
        self.assertEqual(save.read_bytes(), b'own-save'); self.assertEqual((work / 'options.txt').read_text(), 'own-settings')
        self.assertEqual(mc.read(bridge), {'enabled':False})

    def test_launch_uses_exact_case_offline_uuid_and_isolated_game_directory(self):
        work = self.prepared(); java, args, actual = mc.launch_plan(self.root, self.source, '127.0.0.1:25565')
        self.assertEqual(actual, work)
        self.assertEqual(args[args.index('--username') + 1], 'NAIMEI')
        self.assertEqual(args[args.index('--uuid') + 1], 'a77465cf2de03278bf48d13b367e09ce')
        self.assertEqual(args[args.index('--accessToken') + 1], '0')
        self.assertEqual(args[args.index('--gameDir') + 1], str(work))
        self.assertEqual(args[args.index('--quickPlayMultiplayer') + 1], '127.0.0.1:25565')
        self.assertFalse(any('DO_NOT_IMPORT' in a for a in args))

    def test_singleplayer_title_launch_has_no_multiplayer_target_or_fallback(self):
        self.prepared()
        _, args, _ = mc.launch_plan(self.root, self.source, None, mode='singleplayer')
        self.assertFalse(any(a in args for a in ('--quickPlayMultiplayer','--quickPlayRealms','--server','--port','--quickPlaySingleplayer')))
        self.assertEqual(args[args.index('--username') + 1], 'NAIMEI')

    def test_singleplayer_launch_targets_only_an_existing_owned_world(self):
        work = self.prepared(); world = work/'saves/mc-live-offline-083/level.dat'
        world.parent.mkdir(parents=True); world.write_bytes(b'EXPLICIT_WORLD_FILE_FIXTURE_NOT_REAL_SAVE')
        _, args, _ = mc.launch_plan(self.root, self.source, None, mode='singleplayer', world='mc-live-offline-083')
        self.assertEqual(args[args.index('--quickPlaySingleplayer') + 1], 'mc-live-offline-083')
        self.assertNotIn('--quickPlayMultiplayer', args)
        with self.assertRaisesRegex(ValueError, 'LOCAL_WORLD_MISSING'):
            mc.launch_plan(self.root, self.source, None, mode='singleplayer', world='missing-world')

    def test_singleplayer_launch_keeps_the_actual_spaced_folder_as_one_argument(self):
        work = self.prepared(); name = 'MC Live Offline 083'
        world = work / 'saves' / name / 'level.dat'
        world.parent.mkdir(parents=True); world.write_bytes(b'EXPLICIT_NAMED_WORLD_FIXTURE_NOT_REAL_SAVE')
        _, args, actual = mc.launch_plan(self.root, self.source, None, mode='singleplayer', world=name)
        self.assertEqual(actual, work)
        self.assertEqual(args[args.index('--quickPlaySingleplayer') + 1], name)
        self.assertEqual(args.count(name), 1)
        self.assertNotIn('--quickPlayMultiplayer', args)
        self.assertEqual(world.read_bytes(), b'EXPLICIT_NAMED_WORLD_FIXTURE_NOT_REAL_SAVE')
        self.assertFalse((work / 'saves/mc-live-offline-083').exists())

    def test_singleplayer_preserves_distinct_internal_spaces_and_rejects_missing_spaced_world(self):
        work = self.prepared()
        for name in ['MC Live Offline 083', 'MC  Live Offline 083']:
            path = work / 'saves' / name / 'level.dat'
            path.parent.mkdir(parents=True); path.write_bytes(name.encode('ascii'))
        before = {p: p.read_bytes() for p in (work / 'saves').glob('*/level.dat')}
        for name in ['MC Live Offline 083', 'MC  Live Offline 083']:
            _, args, _ = mc.launch_plan(self.root, self.source, None, mode='singleplayer', world=name)
            self.assertEqual(args[args.index('--quickPlaySingleplayer') + 1], name)
        self.assertEqual(before, {p: p.read_bytes() for p in (work / 'saves').glob('*/level.dat')})
        with self.assertRaisesRegex(ValueError, 'LOCAL_WORLD_MISSING'):
            mc.launch_plan(self.root, self.source, None, mode='singleplayer', world='Missing Local World')

    def test_singleplayer_preserves_neoforge_jvm_module_path_without_treating_it_as_a_game_port(self):
        path = self.instance/'MC-Friends-S1-r001.json'; value = mc.read(path)
        value['arguments']['jvm'] += ['-p', '${library_directory}/modules']
        path.write_text(json.dumps(value), encoding='utf8')
        next(pin for pin in self.files if pin['path'].endswith('/MC-Friends-S1-r001.json')).update(
            bytes=path.stat().st_size, sha256=mc.sha(path))
        self.write_lock(); self.prepared()
        _, args, _ = mc.launch_plan(self.root, self.source, None, mode='singleplayer')
        main = args.index('cpw.mods.bootstraplauncher.BootstrapLauncher')
        self.assertLess(args.index('-p'), main)
        self.assertEqual(args[args.index('-p') + 1], str(self.source/'.minecraft/libraries') + '/modules')
        self.assertNotIn('-p', args[main+1:])
        self.assertNotIn('--quickPlayMultiplayer', args)

    def test_singleplayer_still_blocks_short_and_long_network_flags_in_game_arguments(self):
        path = self.source/'.minecraft/versions/1.21.1/1.21.1.json'; original = mc.read(path)
        for flag in ['--server', '--port', '-s', '-p', '--quickPlayMultiplayer', '--quickPlayRealms']:
            with self.subTest(flag=flag):
                value = json.loads(json.dumps(original)); value['arguments']['game'] += [flag, '25565']
                path.write_text(json.dumps(value), encoding='utf8')
                next(pin for pin in self.files if pin['path'].endswith('/1.21.1.json')).update(
                    bytes=path.stat().st_size, sha256=mc.sha(path))
                self.write_lock(); self.prepared()
                with self.assertRaisesRegex(ValueError, 'NETWORK_ARGUMENT'):
                    mc.launch_plan(self.root, self.source, None, mode='singleplayer')

    def test_singleplayer_rejects_addresses_and_unsafe_world_paths_before_source_reads(self):
        bad_names = ['', '../other', 'C:/save', 'a/b', 'a\\b', 'CON', 'nUl', 'lPt9',
                     ' world', 'world ', 'world.', 'a' * 65, 'world\tname', 'world\n--server host',
                     'world\rname', 'world --server host', 'world -p 25565', 'world "quoted"',
                     'world#comment', 'world;command', '@world', 'world:stream']
        for server, world in [('host:25565', None), *((None, name) for name in bad_names)]:
            with self.subTest(server=server,world=world), self.assertRaisesRegex(ValueError, 'LOCAL_WORLD'):
                mc.launch_plan(self.root, self.folder/'missing', server, mode='singleplayer', world=world)

    def test_singleplayer_rejects_inherited_multiplayer_arguments(self):
        path = self.source/'.minecraft/versions/1.21.1/1.21.1.json'; value = mc.read(path)
        value['arguments']['game'] += ['--quickPlayMultiplayer','host:25565']
        path.write_text(json.dumps(value),encoding='utf8')
        next(pin for pin in self.files if pin['path'].endswith('/1.21.1.json')).update(bytes=path.stat().st_size,sha256=mc.sha(path))
        self.write_lock();self.prepared()
        with self.assertRaisesRegex(ValueError, 'NETWORK_ARGUMENT'):
            mc.launch_plan(self.root, self.source, None, mode='singleplayer')

    def test_jna_temp_overrides_supplied_native_directory_without_changing_native_lookup(self):
        path = self.source / '.minecraft/versions/1.21.1/1.21.1.json'
        value = mc.read(path)
        value['arguments']['jvm'] += ['-Djna.tmpdir=${natives_directory}',
                                     '-Djava.library.path=${natives_directory}']
        path.write_text(json.dumps(value), encoding='utf-8')
        next(pin for pin in self.files if pin['path'].endswith('/1.21.1.json')).update(
            bytes=path.stat().st_size, sha256=mc.sha(path))
        self.write_lock()
        work = self.prepared()
        before = {p: mc.sha(p) for p in self.source.rglob('*') if p.is_file()}
        _, args, _ = mc.launch_plan(self.root, self.source, '127.0.0.1:25565')
        self.assertEqual([arg for arg in args if arg.startswith('-Djna.tmpdir=')],
                         ['-Djna.tmpdir=' + str(work.parent / 'tmp')])
        self.assertIn('-Djava.library.path=' + str(work.parent / 'natives'), args)
        self.assertEqual(before, {p: mc.sha(p) for p in self.source.rglob('*') if p.is_file()})

    def test_changed_copied_mod_prevents_launch(self):
        work = self.prepared(); (work / 'mods/fixture-1.jar').write_bytes(b'tamper')
        with self.assertRaisesRegex(ValueError, 'TARGET_MOD_CHANGED'):
            mc.launch_plan(self.root, self.source, '127.0.0.1:25565')

    def test_extra_copied_mod_prevents_launch(self):
        work = self.prepared(); (work / 'mods/second-controller.jar').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'TARGET_MOD_SET_CHANGED'):
            mc.launch_plan(self.root, self.source, '127.0.0.1:25565')

    def test_changed_native_probe_prevents_launch(self):
        work = self.prepared(); (work / 'mods/ai-talk-streamer-native-neoforge-0.1.0.jar').write_bytes(b'tamper')
        with self.assertRaisesRegex(ValueError, 'PROBE_CHANGED'):
            mc.launch_plan(self.root, self.source, '127.0.0.1:25565')

    def test_invalid_endpoint_is_rejected_before_touching_source(self):
        for value in ['host:0', 'host:65536', 'host:25565 --op', 'http://host:25565', 'user@host:25565', None]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'NEOFORGE_SERVER'):
                mc.launch_plan(self.root, self.folder / 'missing', value)

    def fixture_dependencies(self):
        entries = []
        for group, artifact, version in [('dev.harrel', 'json-schema', '1.9.1'), ('org.xerial', 'sqlite-jdbc', '3.53.4.0')]:
            name = artifact + '-' + version + '.jar'
            path = self.root / mc.HOME / 'dependencies' / name
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'EXPLICIT_DEPENDENCY_HASH_FIXTURE')
            entries.append({'group': group, 'artifact': artifact, 'version': version, 'file': name,
                            'bytes': path.stat().st_size, 'sha256': mc.sha(path)})
        lock = {'schema_version': 1, 'shared_core': mc.BRIDGE_CORE, 'schema': mc.BRIDGE_SCHEMA, 'dependencies': entries}
        (self.root / mc.BRIDGE_LOCK).write_text(json.dumps(lock), encoding='utf-8')
        return lock

    def test_unpinned_or_tampered_bridge_dependency_is_rejected(self):
        self.fixture_dependencies(); entries, paths = mc.bridge_dependencies(self.root)
        self.assertEqual(len(entries), 2)
        paths[0].write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'BRIDGE_DEPENDENCY_HASH'):
            mc.bridge_dependencies(self.root)

    def test_dependency_filename_cannot_escape_installation(self):
        lock = self.fixture_dependencies(); lock['dependencies'][0]['file'] = '../json-schema-1.9.1.jar'
        (self.root / mc.BRIDGE_LOCK).write_text(json.dumps(lock), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'BRIDGE_DEPENDENCY_PATH'):
            mc.bridge_dependencies(self.root)

    def test_loader_bridge_cannot_substitute_another_authority_source(self):
        lock = self.fixture_dependencies(); lock['shared_core'] = 'second-controller'
        (self.root / mc.BRIDGE_LOCK).write_text(json.dumps(lock), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'BRIDGE_LOCK'):
            mc.bridge_dependencies(self.root)

    def test_shared_core_change_invalidates_native_build_before_launch(self):
        self.prepared(); source = self.root / mc.BRIDGE_CORE / 'BridgeCore.java'; source.parent.mkdir(parents=True)
        source.write_text('explicit source identity fixture', encoding='utf-8')
        receipt = self.root / '.setup/mc-neoforge-probe-build.json'; data = mc.read(receipt)
        data['sources'] = {source.relative_to(self.root).as_posix(): mc.sha(source)}
        receipt.write_text(json.dumps(data), encoding='utf-8'); source.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'BUILD_STALE'):
            mc.launch_plan(self.root, self.source, '127.0.0.1:25565')

    def test_probe_lifetime_cannot_be_unbounded_or_changed_by_jvm_injection(self):
        for count in [4, 301, '60 -Dsurvival=true', True]:
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'WORLD_SAMPLE_LIMIT'):
                mc.launch_plan(self.root, self.folder / 'missing', '127.0.0.1:25565', count)
        self.prepared(); _, args, _ = mc.launch_plan(self.root, self.source, '127.0.0.1:25565', 60)
        self.assertIn('-Dai.talk.streamer.integrationWorldSamples=60', args)


class IdentityTests(unittest.TestCase):
    def test_game_probe_rejects_editing_host_before_reading_or_launching_anything(self):
        with patch.object(mc.platform, 'node', return_value='EDITING-PC'), \
                patch.object(mc, 'launch_plan', side_effect=AssertionError('Must not inspect or launch on this host')):
            with self.assertRaisesRegex(ValueError, 'REQUIRES_REMOTE_3080_NOT_LOCAL_MACHINE'):
                mc.probe(Path('nonexistent'), Path('nonexistent'), '127.0.0.1:25565')

    def test_offline_uuid_matches_the_confirmed_whitelist_identity(self):
        self.assertEqual(mc.offline_uuid('NAIMEI'), 'a77465cf-2de0-3278-bf48-d13b367e09ce')
        self.assertNotEqual(mc.offline_uuid('NAIMEI'), mc.offline_uuid('naimei'))

    def test_invalid_usernames_are_not_reinterpreted(self):
        for name in ['', 'a b', 'a' * 17, '../NAIMEI', '奈美', None]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'OFFLINE_USERNAME'):
                mc.offline_uuid(name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
