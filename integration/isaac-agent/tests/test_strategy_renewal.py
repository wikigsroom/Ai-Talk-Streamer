"""Bounded embedding windows renew unchosen offers without reviving old authority."""
import tempfile
import unittest
from isaac_jev.strategy import StrategyService,StrategyError
from isaac_jev.models import GameState
from strategy_fixtures import scenario


class StrategyRenewalTests(unittest.TestCase):
    def test_opt_in_window_is_bounded_and_expiry_creates_a_new_authority(self):
        with tempfile.TemporaryDirectory() as td:
            now=[1000.0]
            service=StrategyService(td,clock=lambda:now[0],decision_seconds=999,
                                    max_decision_seconds=120,renew_expired_decisions=True)
            try:
                service.configure(enabled=True,live=True);raw=scenario('pickup')
                service.update(raw,GameState.from_message(raw));old=service.decision()
                self.assertEqual(old['remaining_ms'],120000)
                offer=next(o for o in old['offers'] if o['op']!='wait')
                stale={'plan_id':'old-expired','decision_id':old['id'],'context_id':old['context_id'],
                       'offer_id':offer['id'],'reason':'expired caller','budget':offer['cost']}
                now[0]+=121;raw=raw|{'frame':raw['frame']+7260}
                service.update(raw,GameState.from_message(raw));fresh=service.decision()
                self.assertTrue(fresh['pending']);self.assertNotEqual(fresh['id'],old['id'])
                self.assertEqual(fresh['remaining_ms'],120000)
                with self.assertRaises(StrategyError):service.submit(stale)
                self.assertIsNone(service.command)
                self.assertEqual(service.receipts,{})
            finally:service.close()


if __name__=='__main__':unittest.main()
