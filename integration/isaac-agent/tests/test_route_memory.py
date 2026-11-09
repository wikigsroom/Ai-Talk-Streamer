"""Navigation regression scenarios. Synthetic state, never evidence of gameplay."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src')); sys.path.insert(0, str(ROOT/'tests'))
from isaac_jev.models import GameState
from isaac_jev.route_memory import RouteMemory
from isaac_jev.strategy import StrategyService
from strategy_fixtures import scenario


def room(index, exits, visit=1, visited=(), keys=1):
    raw = scenario('route')
    raw.update(room_index=index, room_visit_sequence=visit, keys=keys, frame=100+visit*6)
    raw['layout']['room_index'] = index
    raw['layout']['doors'] = [dict(slot=i, pos={'x':320,'y':120}, grid_index=7,
        target_room_index=target, target_room_type=kind, target_clear=target in visited,
        target_is_boss=kind=='boss', door_locked=locked, door_lock_known=True,
        door_open=not locked, door_open_known=True) for i,(target,kind,locked) in enumerate(exits)]
    raw['strategy']['map'] = [{'index':n,'visited':1,'type':1} for n in set(visited)|{index}]
    return raw


class RouteMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = StrategyService(self.temp.name)
        self.service.configure(enabled=True, live=True)

    def tearDown(self):
        self.service.close(); self.temp.cleanup()

    def update(self, raw):
        state=GameState.from_message(raw)
        self.service.update(raw,state)
        return state

    def choose(self, predicate, key):
        d = self.service.decision()
        o = next(o for o in d['offers'] if predicate(o))
        self.service.submit({'plan_id':key,'decision_id':d['id'],'context_id':d['context_id'],
                             'offer_id':o['id'],'budget':o['cost'],'reason':'synthetic navigation regression'})
        return o

    def test_55_70_declined_shop_does_not_lure_another_round_trip(self):
        a = room(55,[(70,'default',False),(81,'shop',True)],visited=(55,70))
        self.update(a)
        self.choose(lambda o:o['op']=='wait','keep-last-key')
        b = room(70,[(55,'default',False),(71,'default',False)],2,visited=(55,70))
        self.update(b)
        routes=[o['route']['room'] for o in self.service.decision()['offers'] if o.get('route')]
        self.assertIn(71,routes)
        self.assertNotIn(81,routes)
        self.assertNotIn(55,routes)
        a['room_visit_sequence']=3;self.update(a)
        self.assertFalse(any(o.get('guard',{}).get('door',{}).get('target_room_index')==81
                             for o in self.service._offers(GameState.from_message(a))))

    def test_84_85_failed_optional_target_is_not_reoffered_on_revisit(self):
        raw=scenario('pickup');raw.update(room_index=85)
        self.update(raw)
        o=self.choose(lambda o:bool(o.get('target_id')),'unreachable-pickup')
        self.service._finish('rejected','no_current_safe_path_or_candidate')
        self.update(room(84,[(85,'default',False),(71,'default',False)],2,visited=(84,85)))
        raw['room_visit_sequence']=3;self.update(raw)
        offers=self.service._offers(GameState.from_message(raw))
        self.assertFalse(any(p.get('target_id')==self.service.snapshot['pickups'][0]['target_id'] for p in offers))
        self.assertEqual(len(self.service.routes.data['constraints']),1)

    def test_refusal_survives_restart_and_ordinary_pause_but_fences_do_not(self):
        raw=scenario('pickup');self.update(raw)
        original=self.service.snapshot['pickups'][0]['target_id']
        self.choose(lambda o:o['op']=='wait','decline')
        raw['strategy']['paused']=True;self.update(raw)
        self.service.configure(enabled=False);self.service.configure(enabled=True,live=True)
        raw['strategy']['paused']=False;raw['room_visit_sequence']=2;self.update(raw)
        self.assertNotEqual(original,self.service.snapshot['pickups'][0]['target_id'])
        self.service.close()
        self.service=StrategyService(self.temp.name);self.service.configure(enabled=True,live=True)
        self.update(raw)
        self.assertFalse(any(o.get('target_id') for o in self.service._offers(GameState.from_message(raw))))

    def test_a_new_key_allows_dsh_to_reconsider_a_declined_paid_door(self):
        raw=room(55,[(81,'shop',True)],visited=(55,))
        self.update(raw);self.choose(lambda o:o['op']=='wait','save-key')
        raw['room_visit_sequence']=2;self.update(raw)
        self.assertFalse(self.service.decision()['pending'])
        raw['keys']=2;self.update(raw)
        d=self.service.decision()
        door=next(o for o in d['offers'] if o.get('guard',{}).get('door'))
        self.assertEqual(door['cost']['keys'],1)
        self.assertIsNone(self.service.command)

    def test_new_spawn_seed_does_not_inherit_a_refusal(self):
        raw=scenario('pickup');self.update(raw);self.choose(lambda o:o['op']=='wait','skip')
        raw['strategy']['pickups'][0]['spawn_seed']+=1;raw['pickups']=deepcopy(raw['strategy']['pickups'])
        raw['room_visit_sequence']=2;self.update(raw)
        self.assertTrue(any(o.get('target_id') for o in self.service.decision()['offers']))

    def test_door_wall_cell_uses_walkable_approach_for_route_alternatives(self):
        raw=scenario('pickup')
        raw['layout']['blocked']=[7]
        self.update(raw)
        self.assertTrue(any(o.get('action_id')=='enter_door_1' for o in self.service.decision()['offers']))

    def test_known_native_visit_is_survey_not_unexplored(self):
        self.update(room(70,[(55,'default',False)],visited=(55,70)))
        o=next(o for o in self.service.decision()['offers'] if o.get('route'))
        self.assertEqual(o['route']['kind'],'survey_previously_visited_room')
        self.assertTrue(o['route']['previously_visited'])

    def test_multi_room_goal_survives_valid_backtracking_and_stops_at_paid_step(self):
        # Observe the corridor before choosing a multi-room target.
        self.update(room(84,[(85,'default',False),(71,'default',False)],visited=(84,85,71)))
        self.update(room(85,[(84,'default',False),(87,'treasure',True)],2,visited=(84,85,71)))
        self.update(room(84,[(85,'default',False),(71,'default',False)],3,visited=(84,85,71)))
        chosen=self.choose(lambda o:o.get('route',{}).get('room')==87,'treasure-goal')
        self.assertEqual(chosen['route']['path'],[84,85,87])
        self.assertEqual(chosen['cost']['keys'],0)
        self.assertEqual(chosen['route']['terminal_key_cost'],1)
        self.service.command['issued']=True
        self.update(room(85,[(84,'default',False),(87,'treasure',True)],4,visited=(84,85,71)))
        self.assertEqual(self.service.receipts['treasure-goal']['status'],'succeeded')
        self.assertTrue(self.service.decision()['pending'])
        self.assertIsNone(self.service.command)
        self.assertEqual(self.service.routes.data['goal']['room'],87)

    def test_no_progress_cycle_exhausts_edge_without_inventing_progress(self):
        for n,index in enumerate((84,85,84,85,84,85,84),1):
            self.update(room(index,[(85 if index==84 else 84,'default',False)],n,visited=(84,85)))
        self.assertEqual(self.service.routes.data['progress'],2)
        self.assertFalse(self.service.routes.routes())
        response=self.service.decorate_response({'enabled':True,'id':'enter_door_0','mode':'navigate'},
                                               GameState.from_message(self.service.raw))
        self.assertEqual(response['mode'],'strategy_hold')

    def test_floor_and_dimension_change_reset_memory(self):
        raw=scenario('pickup');self.update(raw);self.choose(lambda o:o['op']=='wait','defer')
        raw['dimension']=1;self.update(raw)
        self.assertFalse(self.service.routes.data['constraints'])
        self.assertTrue(any(o.get('target_id') for o in self.service.decision()['offers']))

    def test_pause_retains_goal_context_but_requires_a_fresh_choice(self):
        raw=room(84,[(85,'default',False)],visited=(84,))
        self.update(raw);self.choose(lambda o:bool(o.get('route')),'go')
        self.service.configure(enabled=False)
        self.assertEqual(self.service.routes.data['goal']['room'],85)
        self.assertTrue(self.service.routes.data['goal']['suspended'])
        self.service.configure(enabled=True,live=True);raw['frame']+=6;self.update(raw)
        self.assertTrue(self.service.decision()['pending'])
        self.assertIsNone(self.service.command)
        self.assertIsNone(self.service.routes.continuation(self.service.decision()['offers']))

    def test_free_fallback_respects_declined_resource_and_never_uses_a_key(self):
        raw=room(55,[(81,'shop',True),(70,'default',False)],visited=(55,))
        state=self.update(raw);self.choose(lambda o:o['op']=='wait','wait')
        response=self.service.decorate_response({'enabled':True,'id':'enter_door_0','mode':'navigate'},state)
        self.assertEqual(response['target_room_index'],70)
        self.assertIsNone(response['strategy']['command'])
        self.assertEqual(raw['keys'],1)


if __name__=='__main__':unittest.main()
