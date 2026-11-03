"""A closing native DSH owner must not be replaced or confused with another app."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import importlib.util
import unittest
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('dsh_control_test', ROOT/'scripts/dsh_control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class DshControlTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name, value in [('ROOT', self.root), ('RECORD', self.root / '.setup/dsh-process.json')]:
            change = patch.object(control, name, value)
            change.start(); self.addCleanup(change.stop)

    def test_exact_server_and_project_root_are_both_required(self):
        server = str(self.root/'backend/dsh-bridge/server.mjs')
        own = SimpleNamespace(info={'cmdline':['node.exe', server, str(self.root)]})
        other = SimpleNamespace(info={'cmdline':['node.exe', server, str(self.root.parent/'other')]})
        unrelated = SimpleNamespace(info={'cmdline':['node.exe', 'other/server.mjs', str(self.root)]})
        with patch('psutil.process_iter', return_value=[own, other, unrelated]):
            self.assertEqual(control.owned_processes(), [own])

    def test_closed_http_port_does_not_allow_a_second_owner(self):
        with patch.object(control, 'status', return_value={'process_alive':False}), \
             patch.object(control, 'owned_processes', return_value=[Mock()]), \
             patch.object(control.subprocess, 'Popen') as spawn, \
             patch('sys.argv', ['dsh_control.py', 'start']):
            with self.assertRaises(RuntimeError):control.main()
            spawn.assert_not_called()

    def test_stop_finishes_only_the_known_closing_owner(self):
        owner = Mock()
        with patch.object(control, 'status', return_value={'process_alive':False}), \
             patch.object(control, 'owned_processes', return_value=[owner]), \
             patch('psutil.wait_procs', side_effect=[([], [owner]), ([owner], [])]), \
             patch.object(control.urllib.request, 'Request') as request, \
             patch('sys.argv', ['dsh_control.py', 'stop']):
            control.main()
            request.assert_not_called()
            owner.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
