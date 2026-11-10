"""Execute the real native UI classifier with observed live and false states."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock
import urllib.error

from integration.issac.common import AdmissionError
from integration.issac.live_supervisor import LiveSupervisor

ROOT=Path(__file__).resolve().parents[3]
FIXTURES=Path(__file__).parent/'fixtures'


@unittest.skipUnless(os.name=='nt','Native PowerShell UI classifier requires Windows')
class ActualOfficialUiState(unittest.TestCase):
    def setUp(self):
        self.buttons=json.loads((FIXTURES/'official-live-ui-20261111.json').read_text('utf8'))['buttons']

    def classify(self,buttons):
        command=[r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe','-NoProfile','-NonInteractive',
            '-ExecutionPolicy','Bypass','-File',str(FIXTURES/'classify-official-live-ui.ps1'),
            '-ModulePath',str(ROOT/'scripts/issac_broadcast_state.psm1')]
        result=subprocess.run(command,input=json.dumps(buttons).encode('ascii'),capture_output=True,timeout=12,
            creationflags=0x08000000)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf8',errors='replace'))
        return json.loads(result.stdout.decode('utf-8-sig'))

    def test_actual_elapsed_button_and_quality_identify_the_running_client(self):
        value=self.classify(self.buttons)
        self.assertTrue(value['already_running']);self.assertEqual(value['running_buttons'],0)
        self.assertEqual(value['running_evidence'],'owned_live_elapsed_and_quality_controls')

    def test_local_recording_clock_does_not_hide_an_available_start_button(self):
        value=self.classify(self.buttons+[{'name':'开始直播','is_button':True,'enabled':True,'offscreen':False}])
        self.assertFalse(value['already_running']);self.assertEqual(value['start_buttons'],1)

    def test_clock_without_live_quality_does_not_admit_streaming(self):
        self.assertFalse(self.classify(self.buttons[:1])['already_running'])

    def test_hidden_disabled_and_text_clocks_cannot_admit_streaming(self):
        for key,value in [('enabled',False),('offscreen',True),('is_button',False)]:
            rows=deepcopy(self.buttons);rows[0][key]=value
            self.assertFalse(self.classify(rows)['already_running'])

    def test_child_text_is_not_a_second_start_button(self):
        rows=[{'name':'开始直播','is_button':True,'enabled':True,'offscreen':False},
              {'name':'开始直播','is_button':False,'enabled':True,'offscreen':False}]
        self.assertEqual(self.classify(rows)['start_buttons'],1)

    def test_existing_named_live_control_remains_read_only_evidence(self):
        rows=[{'name':'关播','is_button':True,'enabled':True,'offscreen':False}]
        self.assertTrue(self.classify(rows)['already_running'])


class LocalApiAdmissionReason(unittest.TestCase):
    def supervisor(self,body):
        owner=object.__new__(LiveSupervisor);owner.token='local-test-token';owner.opener=Mock()
        owner.opener.open.side_effect=urllib.error.HTTPError('http://127.0.0.1:9534/control',409,'Conflict',{},io.BytesIO(body))
        return owner

    def test_local_admission_code_is_preserved_for_recovery_diagnosis(self):
        owner=self.supervisor(b'{"error":"NORMAL_PAUSE_INPUT_ACK_PENDING"}')
        with self.assertRaisesRegex(AdmissionError,'^RECOVERY_API_NORMAL_PAUSE_INPUT_ACK_PENDING$'):
            owner.api(9534,'/control',{'action':'recovery_pause'})

    def test_arbitrary_response_text_is_not_echoed_as_a_failure_code(self):
        for body in (b'{"error":"private text must not be echoed"}',b'not JSON'):
            owner=self.supervisor(body)
            with self.assertRaisesRegex(AdmissionError,'^RECOVERY_API_LOCAL_HTTP_409$'):
                owner.api(9534,'/control',{'action':'recovery_pause'})


if __name__=='__main__':unittest.main()
