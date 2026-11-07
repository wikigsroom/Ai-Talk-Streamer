"""Monitoring must not serialize the dashboard's large decision history."""
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState
from isaac_jev.runtime import Controller
from isaac_jev.web_dashboard import LocalDashboard


class CompactStatusTests(unittest.TestCase):
    def test_observation_and_toggle_skip_diagnostic_history(self):
        with tempfile.TemporaryDirectory() as folder:
            controller=Controller(log_dir=folder)
            controller._latest_state=GameState.from_message({'frame':12,'player':{'hp':4}})
            controller._debug_history.append({'irrelevant':'x'*1000000})
            server=LocalDashboard(controller,port=0)
            server.start()
            try:
                with patch('isaac_jev.runtime.decision_rules',side_effect=AssertionError('diagnostics built')):
                    with urllib.request.urlopen(server.url+'api/status?compact=1') as reply:
                        payload=reply.read()
                    status=json.loads(payload)
                    self.assertLess(len(payload),8192)
                    self.assertEqual(status['latest_frame'],12)
                    self.assertEqual(status['latest_state']['player_hp'],4)
                    self.assertNotIn('debug_logs',status)
                    req=urllib.request.Request(server.url+'api/autopilot?compact=1',
                        data=b'{"enabled":true}',headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(req) as reply:
                        enabled=json.load(reply)
                    self.assertTrue(enabled['autopilot_enabled'])
            finally:
                server.stop()
                controller.shutdown()


if __name__=='__main__': unittest.main()
