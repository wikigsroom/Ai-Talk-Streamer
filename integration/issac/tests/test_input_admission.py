"""The actual embedded controller waits for DSH without exhausting objectives."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'integration/isaac-agent/tests'))
try:
    from strategy_fixtures import scenario
finally:
    sys.path.remove(str(ROOT/'integration/isaac-agent/tests'))
from integration.issac.game_policy import strategy_class
from integration.issac.strategy_host import controller_class


class EmbeddedInputAdmission(unittest.TestCase):
    def test_waiting_for_persona_probe_does_not_consume_hazard_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            service=strategy_class(ROOT)(td);service.core_actor_required=True
            owner=controller_class(ROOT,service,SimpleNamespace(ingest=lambda *args:None))(
                autopilot_enabled=False,log_dir=td)
            try:
                raw=scenario();raw['input_lease']={'controls_enabled':True}
                raw['hazards']=[{'id':10,'kind':'fire','type':33,'hp':5,'animation':'Flickering',
                                 'pos':{'x':400,'y':280}}]
                for frame in range(100,1000,6):owner.receive_state(raw|{'frame':frame})
                self.assertTrue(owner.require_enabled_action_feedback)
                self.assertEqual(owner._ignored_hazard_ids,set())
                self.assertEqual(owner._unreachable_targets,[])
                service.configure(enabled=True,live=True);owner.set_autopilot(True)
                owner.receive_state(raw|{'frame':1000})
                decision=service.decision()
                self.assertTrue(decision['pending'])
                self.assertIn('clear_hazard_10',[o.get('action_id') for o in decision['offers']])
            finally:
                owner.shutdown();service.close()


if __name__=='__main__':unittest.main()
