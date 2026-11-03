"""Native client download and installation evidence; no game, model or real download."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import mc_client as client
from native_operation import OperationError


class NativeClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.data = b'checked native client fixture'
        self.pin = {'url': 'https://libraries.minecraft.net/fixture.jar', 'bytes': len(self.data),
                    'sha1': hashlib.sha1(self.data).hexdigest(), 'sha256': hashlib.sha256(self.data).hexdigest()}
        self.target = self.root/'libraries/fixture.jar'
        self.lock = json.loads((ROOT/client.LOCK).read_bytes())
        self.write(client.LOCK, self.lock)
    def write(self, name, value):
        path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    @contextmanager
    def response(self, data=None, status=200):
        stream = io.BytesIO(self.data if data is None else data); stream.status = status
        with patch.object(client.urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value = stream
            yield factory.return_value.open
    def install_record(self):
        home = self.lock['home']
        names = [home+'/jvm/bin/java.exe', home+'/libraries/game.jar', self.lock['work']+'/mods/fabric-api-'+self.lock['fabric_api']+'.jar']
        rows = []
        for name in names:
            path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(self.data)
            rows.append({'path': name, **client.hashes(path)})
        record = {'schema_version': 1, 'installation_root': str(self.root), 'home': home,
                  'lock_sha256': client.deployment.sha(self.root/client.LOCK), 'files': rows,
                  'java_version': '21.0.7', 'java': names[0], 'classpath': [names[1]], 'native_libraries': [],
                  'main_class': 'net.fabricmc.loader.impl.launch.knot.KnotClient'}
        self.write(client.RECEIPT, record); return record
    def test_streamed_content_is_hash_checked_before_publish(self):
        with self.response(): result = client.fetch(self.root, self.target, self.pin)
        self.assertTrue(result['downloaded']); self.assertEqual(self.target.read_bytes(), self.data)
        self.assertEqual(list(self.target.parent.glob('*.part')), [])
    def test_verified_cache_performs_no_network_request(self):
        self.target.parent.mkdir(); self.target.write_bytes(self.data)
        with patch.object(client.urllib.request, 'build_opener') as network:
            self.assertFalse(client.fetch(self.root, self.target, self.pin)['downloaded'])
        network.assert_not_called()
    def test_download_window_returns_each_file_once_and_limits_active_requests(self):
        mutex = threading.Lock(); active = 0; maximum = 0; started = []
        def download(home, path, pin):
            nonlocal active, maximum
            with mutex:
                active += 1; maximum = max(maximum, active); started.append(path)
            try:
                return {'bytes': pin['bytes'], 'downloaded': True}
            finally:
                with mutex: active -= 1
        requests = [(SimpleNamespace(dst=self.root/str(n)), self.pin) for n in range(37)]
        with patch.object(client, 'fetch', download):
            completed = list(client.download_window(self.root, requests, 100))
        self.assertEqual(len(completed), 37); self.assertEqual(len(set(started)), 37)
        self.assertLessEqual(maximum, 8); self.assertEqual(active, 0)
    def test_download_failure_does_not_submit_the_rest_of_the_installation(self):
        barrier = threading.Barrier(8); released = threading.Event(); started = []
        def download(home, path, pin):
            started.append(path); barrier.wait(timeout=5)
            if path.name == '0':
                released.set(); raise client.ClientError('MC_CLIENT_DOWNLOAD_UNAVAILABLE')
            self.assertTrue(released.wait(5)); return {'bytes': 1}
        requests = [(SimpleNamespace(dst=self.root/str(n)), self.pin) for n in range(4000)]
        with patch.object(client, 'fetch', download):
            with self.assertRaisesRegex(client.ClientError, 'DOWNLOAD_UNAVAILABLE'):
                list(client.download_window(self.root, requests, 8))
        self.assertEqual(len(started), 8)
    def test_closing_download_window_does_not_start_queued_files(self):
        started = []
        def download(home, path, pin):
            started.append(path); return {'bytes': 1}
        requests = [(SimpleNamespace(dst=self.root/str(n)), self.pin) for n in range(4000)]
        with patch.object(client, 'fetch', download):
            window = client.download_window(self.root, requests, 1)
            next(window); window.close()
        self.assertEqual(len(started), 1)
    def test_same_size_corrupt_cache_is_replaced(self):
        self.target.parent.mkdir(); self.target.write_bytes(b'x'*len(self.data))
        with self.response() as opened: self.assertTrue(client.fetch(self.root, self.target, self.pin)['downloaded'])
        opened.assert_called_once(); self.assertEqual(self.target.read_bytes(), self.data)
    def test_failed_hash_preserves_existing_destination(self):
        self.target.parent.mkdir(); self.target.write_bytes(b'previous verified file')
        with self.response(b'x'*len(self.data)):
            with self.assertRaisesRegex(client.ClientError, 'HASH_MISMATCH'): client.fetch(self.root, self.target, self.pin)
        self.assertEqual(self.target.read_bytes(), b'previous verified file'); self.assertFalse(list(self.target.parent.glob('*.part')))
    def test_oversized_body_is_rejected_and_temporary_removed(self):
        with self.response(self.data+b'x'):
            with self.assertRaisesRegex(client.ClientError, 'DOWNLOAD_SIZE'): client.fetch(self.root, self.target, self.pin)
        self.assertFalse(self.target.exists()); self.assertFalse(list(self.target.parent.glob('*.part')))
    def test_truncated_body_is_rejected(self):
        with self.response(self.data[:-1]):
            with self.assertRaisesRegex(client.ClientError, 'HASH_MISMATCH'): client.fetch(self.root, self.target, self.pin)
        self.assertFalse(self.target.exists())
    def test_failed_status_is_rejected_without_publication(self):
        with self.response(status=206):
            with self.assertRaisesRegex(client.ClientError, 'DOWNLOAD_STATUS'): client.fetch(self.root, self.target, self.pin)
        self.assertFalse(self.target.exists())
    def test_network_failure_removes_partial_file_without_replacing_original(self):
        self.target.parent.mkdir(); self.target.write_bytes(b'original')
        with patch.object(client.urllib.request, 'build_opener') as factory:
            factory.return_value.open.side_effect = client.urllib.error.URLError('fixture disconnected')
            with self.assertRaisesRegex(client.ClientError, 'DOWNLOAD_UNAVAILABLE'):
                client.fetch(self.root, self.target, self.pin)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertFalse(list(self.target.parent.glob('*.part')))
    def test_untrusted_origins_cannot_fetch_or_reuse_cached_files(self):
        for url in ['http://libraries.minecraft.net/x', 'https://example.com/x', 'https://u:p@libraries.minecraft.net/x',
                    'https://libraries.minecraft.net:444/x', 'https://libraries.minecraft.net/x?a=b', 'https://libraries.minecraft.net/x#f']:
            with self.subTest(url=url), patch.object(client.urllib.request, 'build_opener') as network:
                with self.assertRaisesRegex(client.ClientError, 'DOWNLOAD_ORIGIN'): client.fetch(self.root, self.target, {**self.pin, 'url': url})
                network.assert_not_called()
    def test_redirect_is_refused(self):
        with self.assertRaisesRegex(client.ClientError, 'DOWNLOAD_REDIRECT'):
            client.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com/x')
    def test_invalid_size_and_missing_hash_are_rejected(self):
        for pin in [{**self.pin,'bytes': True}, {**self.pin,'bytes': 0}, {**self.pin,'bytes': client.LIMIT+1},
                    {'url': self.pin['url'], 'bytes': len(self.data)}, {**self.pin,'sha1':'../escape'}]:
            with self.subTest(pin=pin), patch.object(client.urllib.request, 'build_opener') as network:
                with self.assertRaises(client.ClientError): client.fetch(self.root, self.target, pin)
                network.assert_not_called()
    def test_destination_outside_installation_is_rejected(self):
        with patch.object(client.urllib.request, 'build_opener') as network:
            with self.assertRaises(OperationError):
                client.fetch(self.root, self.root.parent/'escape.jar', self.pin)
            network.assert_not_called()
    def test_version_and_home_changes_are_rejected(self):
        for key, value in [('minecraft','1.21.2'), ('fabric_loader','latest'), ('home','../game'), ('platform','linux')]:
            changed = copy.deepcopy(self.lock); changed[key] = value; self.write(client.LOCK, changed)
            with self.subTest(key=key), self.assertRaisesRegex(client.ClientError, 'MC_CLIENT_LOCK'): client.load_lock(self.root)
        self.write(client.LOCK, self.lock)
    def test_status_with_no_receipt_is_read_only_and_not_ready(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        result = client.status(self.root)
        self.assertFalse(result['ok']); self.assertEqual(result['code'], 'MC_CLIENT_NOT_INSTALLED')
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))
    def test_valid_fixture_receipt_proves_only_dependencies(self):
        self.install_record(); result = client.status(self.root)
        self.assertTrue(result['ok']); self.assertFalse(result['game_started'])
        self.assertFalse(result['models_loaded']); self.assertFalse(result['full_application_prepared'])
        self.assertFalse(result['automatic_input_authorized']); self.assertFalse(result['bridge_and_executor_installed'])
        self.assertFalse((self.root/'.setup/mc-native-preparation.json').exists())
    def test_status_rejects_modified_file_and_same_length_corruption(self):
        record = self.install_record(); (self.root/record['java']).write_bytes(b'x'*len(self.data))
        with self.assertRaisesRegex(client.ClientError, 'INSTALLED_FILE_CHANGED'): client.status(self.root)
    def test_status_rejects_truncated_file_inventory(self):
        record = self.install_record(); record['files'] = record['files'][:1]; self.write(client.RECEIPT, record)
        with self.assertRaisesRegex(client.ClientError, 'REQUIRED_FILE_UNVERIFIED'): client.status(self.root)
    def test_status_rejects_cross_installation_receipt(self):
        record = self.install_record(); record['installation_root'] = str(self.root.parent); self.write(client.RECEIPT, record)
        with self.assertRaisesRegex(client.ClientError, 'INSTALLATION_BINDING'): client.status(self.root)
    def test_status_rejects_lock_change(self):
        self.install_record(); changed = copy.deepcopy(self.lock); changed['java']['version'] = '21.0.8'; self.write(client.LOCK, changed)
        with self.assertRaisesRegex(client.ClientError, 'INSTALLATION_BINDING'): client.status(self.root)
    def test_status_rejects_duplicate_windows_path(self):
        record = self.install_record(); record['files'].append({**record['files'][0], 'path': record['files'][0]['path'].upper()}); self.write(client.RECEIPT, record)
        with self.assertRaisesRegex(client.ClientError, 'INSTALLATION_FILES'): client.status(self.root)
    def test_status_rejects_other_project_files(self):
        record = self.install_record(); record['files'].append({'path':'configs/unrelated.json','bytes':1,'sha256':'0'*64}); self.write(client.RECEIPT, record)
        with self.assertRaisesRegex(client.ClientError, 'INSTALLATION_PATH'): client.status(self.root)
    def test_public_cli_missing_installation_does_not_start_services(self):
        completed = subprocess.run([sys.executable,'-X','utf8','-B',str(ROOT/'scripts/mc_runtime.py'),
                                   'client-status','--root',str(self.root)],capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        result = json.loads(completed.stdout); self.assertEqual(result['code'], 'MC_CLIENT_NOT_INSTALLED')
        self.assertFalse(result['game_started']); self.assertFalse(result['models_loaded'])


if __name__ == '__main__': unittest.main()
