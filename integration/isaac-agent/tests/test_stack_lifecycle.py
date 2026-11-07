"""A failed partial arm rolls back through the normal game-pause procedure."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stack_control

class LifecycleTests(unittest.TestCase):
    def test_dsh_failure_after_local_enable_restores_normal_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/'save-protection.json').write_text('{}',encoding='utf8')
            process=Mock(pid=123);process.create_time.return_value=1
            with patch.object(stack_control,'ROOT',path),patch.object(stack_control,'game_identity',return_value=(process,99)),\
                 patch.object(stack_control,'request',return_value={'slot':3,'readonly':False}),\
                 patch.object(stack_control,'native_state',return_value={'hp':6,'dead':False,'paused':True}),\
                 patch('subprocess.run'),patch.object(stack_control,'api',side_effect=[{},OSError('host offline')]),\
                 patch.object(stack_control,'pause',return_value={'normal_game_pause_acknowledged':True}) as pause:
                with self.assertRaises(OSError):stack_control.arm()
                pause.assert_called_once()
                self.assertEqual(json.loads((path/'save-protection.json').read_text(encoding='utf8'))['allowed_slot'],3)

    def test_local_only_arm_never_enables_model_strategy(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/'save-protection.json').write_text('{}',encoding='utf8')
            process=Mock(pid=123);process.create_time.return_value=1
            from io import BytesIO
            with patch.object(stack_control,'ROOT',path),patch.object(stack_control,'game_identity',return_value=(process,99)),patch.object(stack_control,'request',return_value={'slot':3,'readonly':False}),patch.object(stack_control,'native_state',return_value={'hp':6,'dead':False,'paused':False}),patch('subprocess.run'),patch.object(stack_control,'api',return_value={}) as api,patch.object(stack_control.urllib.request,'urlopen',return_value=BytesIO(b'{"autopilot_enabled":true}')):
                result=stack_control.arm(local_only=True)
            self.assertEqual(result['mode'],'local_only')
            self.assertEqual(api.call_args_list[0].args,(9532,'/control',{'enabled':False,'live':False}))
            self.assertEqual(api.call_args_list[1].args,(9533,'/control',{'automatic':False}))

if __name__=='__main__':unittest.main()
