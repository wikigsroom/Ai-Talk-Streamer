"""Observed source-CWD and native official-output encoding regressions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from integration.issac.common import AdmissionError
from integration.issac.flashhead import prepare_source


class RetainedSourceCwdTests(unittest.TestCase):
    def test_real_relative_config_read_works_from_an_unrelated_unicode_working_directory(self):
        previous=Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as temporary,patch('sys.path',list(sys.path)):
                root=Path(temporary)/'奶妹独立安装';source=root/'src/flashhead'
                config=source/'flash_head/configs/infer_params.yaml';config.parent.mkdir(parents=True)
                config.write_text('width: 512\nheight: 512\ntgt_fps: 25\n','utf8')
                upstream=source/'flash_head/inference_fixture.py'
                upstream.write_text('with open("flash_head/configs/infer_params.yaml",encoding="utf8") as f:\n content=f.read()\n','utf8')
                elsewhere=Path(temporary)/'其他工作目录';elsewhere.mkdir();os.chdir(elsewhere)
                selected=prepare_source(root)
                spec=importlib.util.spec_from_file_location('round10_retained_relative_open',upstream)
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                self.assertIn('tgt_fps: 25',module.content);self.assertEqual(Path.cwd(),selected)
                self.assertIn(str(root),sys.path);self.assertEqual(selected,source)
                os.chdir(previous)
        finally:os.chdir(previous)

    def test_missing_retained_config_never_changes_working_directory_or_creates_files(self):
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'unprepared'
            with self.assertRaisesRegex(AdmissionError,'INFERENCE_CONFIG_REQUIRED'):prepare_source(root)
            self.assertEqual(Path.cwd(),previous);self.assertFalse(root.exists())


class OfficialUtf8ProtocolTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Native Windows PowerShell 5.1 required')
    def test_actual_script_prefix_outputs_non_ascii_json_as_utf8_without_opening_ui(self):
        root=Path(__file__).resolve().parents[3]
        source=(root/'scripts/issac_livehime_ui.ps1').read_text('utf-8-sig')
        prefix=source.split('Add-Type -AssemblyName UIAutomationClient',1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            script=Path(temporary)/'native-protocol.ps1'
            script.write_text(prefix+"@{label='奶妹 · 开始录制'}|ConvertTo-Json -Compress\n",'utf-8-sig')
            result=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
                '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-ProcessId','1','-WindowHandle','1'],
                capture_output=True,timeout=20,creationflags=0x08000000)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf8',errors='replace'))
            self.assertEqual(json.loads(result.stdout.decode('utf-8-sig')),{'label':'奶妹 · 开始录制'})


if __name__=='__main__':unittest.main()
