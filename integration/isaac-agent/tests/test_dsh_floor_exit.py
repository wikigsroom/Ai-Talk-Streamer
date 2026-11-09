"""Observed floor exits stay the strategic actor's choice, with live safety vetoes."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from isaac_jev.models import GameState
from isaac_jev.strategy import StrategyService
from strategy_fixtures import scenario


class DshFloorExit(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=StrategyService(self.tmp.name)
        self.s.configure(enabled=True,live=True)

    def tearDown(self):self.s.close();self.tmp.cleanup()

    def raw(self):
        raw=scenario('pickup')
        raw.update(boss_exit_available=True,boss_exit_grid_index=98,
                   boss_exit_position={'x':360,'y':280},planned_goal='return to observed health pickup')
        raw['layout'].update(room_type='boss',is_boss=True)
        raw['strategy']['room_type']='boss'
        return raw

    def update(self,raw):
        state=GameState.from_message(raw);self.s.update(raw,state);return state

    def exit_offer(self):
        return next(o for o in self.s.decision()['offers'] if (o.get('action_id')or'').startswith('enter_boss_exit_'))

    def test_rewards_and_old_health_preference_do_not_hide_exit_from_dsh(self):
        state=self.update(self.raw());offer=self.exit_offer()
        self.assertTrue(any(o.get('target_id') for o in self.s.decision()['offers']))
        self.assertFalse(any(offer['cost'].values()))
        self.assertIsNone(self.s.command)
        decision=self.s.decision()
        self.s.submit({'plan_id':'leave','decision_id':decision['id'],'context_id':decision['context_id'],
                       'offer_id':offer['id'],'budget':offer['cost'],'reason':'leave the remaining reward'})
        action=self.s._resolve_action(offer,state)
        self.assertEqual(action.mode,'boss_exit');self.assertEqual(action.source,'dsh')

    def test_disappeared_exit_cannot_execute_an_earlier_offer(self):
        raw=self.raw();self.update(raw);offer=self.exit_offer()
        raw['boss_exit_available']=False;state=self.update(raw)
        self.assertIsNone(self.s._resolve_action(offer,state))

    def test_moving_spike_obstruction_blocks_alternative_and_execution(self):
        raw=self.raw();self.update(raw);offer=self.exit_offer()
        raw['danger_effects']=[{'id':88,'kind':'moving_spike','pos':raw['boss_exit_position'],'radius':24}]
        state=self.update(raw)
        self.assertFalse(any((o.get('action_id')or'').startswith('enter_boss_exit_') for o in self.s._offers(state)))
        self.assertIsNone(self.s._resolve_action(offer,state))

    def test_blocked_path_or_active_combat_does_not_offer_an_exit(self):
        for kind in ('blocked','combat','no_exit'):
            with self.subTest(kind=kind):
                raw=self.raw()
                if kind=='blocked':raw['layout']['blocked']=list(range(13*13))
                elif kind=='combat':raw['room_clear']=False
                else:raw['boss_exit_available']=False
                state=self.update(raw)
                self.assertFalse(any((o.get('action_id')or'').startswith('enter_boss_exit_') for o in self.s._offers(state)))


if __name__=='__main__':unittest.main()
