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

    def test_closed_super_secret_and_unusable_challenge_do_not_lure_remote_routes(self):
        branch=room(153,[(166,'super_secret',False),(112,'challenge',False),(152,'default',False)],
                    visited=(152,153))
        branch['layout']['doors'][0]['door_open']=False
        self.update(branch)
        self.update(room(152,[(153,'default',False)],2,visited=(152,153)))
        destinations={r['room'] for r in self.service.routes.routes()}
        self.assertNotIn(166,destinations)
        self.assertNotIn(112,destinations)
        self.assertFalse(self.service.decision()['pending'])

    def test_every_special_door_obeys_edge_cap_even_without_a_route_annotation(self):
        raw=room(153,[(140,'shop',False)],visited=(140,153))
        state=self.update(raw)
        self.assertTrue(any(o.get('action_id')=='enter_door_0' for o in self.service._offers(state)))
        self.service.routes.data['edges']['153>140']=2
        self.assertFalse(any(o.get('action_id')=='enter_door_0' for o in self.service._offers(state)))
        self.assertEqual(self.service.routes.data['edges']['153>140'],2)

    @staticmethod
    def boss(index=154, visit=1, exit_available=True):
        raw=room(index,[(153,'default',False)],visit,visited=(153,index))
        raw.update(boss_exit_available=exit_available,boss_exit_grid_index=52,
                   boss_exit_position={'x':320,'y':240})
        raw['layout'].update(room_type='boss',is_boss=True)
        raw['strategy']['room_type']='boss'
        return raw

    def test_observed_cleared_boss_exit_is_a_remote_goal_with_no_resource_spend(self):
        self.update(self.boss())
        self.update(room(153,[(154,'boss',False)],2,visited=(153,154)))
        offer=self.choose(lambda o:o.get('route',{}).get('kind')=='observed_floor_exit','return-exit')
        self.assertEqual(offer['route']['path'],[153,154])
        self.assertFalse(any(offer['cost'].values()))
        self.assertEqual(self.service.routes.data['goal']['room'],154)

    def test_old_cleared_boss_observation_is_surveyed_once_without_inventing_an_exit(self):
        self.update(self.boss(exit_available=False))
        del self.service.routes.data['rooms']['154']['exit_known']
        self.update(room(153,[(154,'boss',False)],2,visited=(153,154)))
        offer=next(o for o in self.service.decision()['offers'] if o.get('route'))
        self.assertEqual(offer['route']['kind'],'survey_cleared_boss_exit')
        self.update(self.boss(visit=3,exit_available=False))
        self.update(room(153,[(154,'boss',False)],4,visited=(153,154)))
        self.assertFalse(any(r['room']==154 for r in self.service.routes.routes()))

    def test_unavailable_stale_hidden_goal_is_removed_before_fresh_choice(self):
        raw=room(153,[(166,'super_secret',False),(154,'boss',False)],visited=(153,154))
        raw['layout']['doors'][0]['door_open']=False
        self.update(raw)
        self.service.routes.data['goal']={'room':166,'kind':'unvisited_super_secret',
                                          'path':[153,166],'terminal_key_cost':0}
        self.service._offers(GameState.from_message(raw))
        self.assertIsNone(self.service.routes.data['goal'])
        self.assertTrue(any(r['room']==154 for r in self.service.routes.routes()))

    def test_floor_exit_is_retained_as_observed_objective_and_real_stage_change_succeeds(self):
        raw=self.boss();state=self.update(raw)
        self.assertTrue(self.service.routes.data['rooms']['154']['objectives'])
        self.choose(lambda o:(o.get('action_id')or'').startswith('enter_boss_exit_'),'descend')
        response=self.service.decorate_response({'enabled':True,'mode':'navigate'},state)
        self.assertEqual(response['mode'],'boss_exit')
        self.assertTrue(self.service.command['issued'])
        next_floor=room(84,[(85,'default',False)],2,visited=(84,))
        next_floor['stage']=raw['stage']+1
        self.update(next_floor)
        receipt=self.service.receipts['descend']
        self.assertEqual(receipt['status'],'succeeded')
        self.assertEqual(receipt['effect'],'native_floor_transition_observed')

    def test_exit_command_does_not_claim_an_unrelated_same_floor_room_change(self):
        raw=self.boss();state=self.update(raw)
        self.choose(lambda o:(o.get('action_id')or'').startswith('enter_boss_exit_'),'wrong-room')
        self.service.decorate_response({'enabled':True,'mode':'navigate'},state)
        self.update(room(153,[(154,'boss',False)],2,visited=(153,154)))
        self.assertEqual(self.service.receipts['wrong-room']['status'],'indeterminate')

    def test_transition_new_stage_old_map_does_not_pollute_the_next_floor(self):
        raw=room(84,[(85,'default',False)],visited=(71,84))
        self.update(raw);self.choose(lambda o:bool(o.get('route')),'continue-goal')
        original=deepcopy(self.service.routes.data)
        held=deepcopy(raw);held['stage']+=1;held['strategy']['paused']=True
        held['input_lease']['controls_enabled']=False
        observation=deepcopy(self.service.snapshot)
        observation['identity']['stage']=held['stage'];observation['room']['paused']=True
        self.service.routes.observe(observation,held,GameState.from_message(held))
        self.assertEqual(self.service.routes.data,original)
        self.assertTrue(self.service.routes.describe()['observation_suspended'])
        self.assertFalse(self.service.routes.annotate([],GameState.from_message(held)))
        self.assertEqual(self.service.routes.data['goal'],original['goal'])
        stable=room(97,[(98,'default',False)],2,visited=(97,));stable['stage']=held['stage']
        self.update(stable)
        self.assertEqual(self.service.routes.data['native_visited'],[97])
        self.assertEqual(set(self.service.routes.data['rooms']),{'97'})
        self.assertIsNone(self.service.routes.data['goal'])

    def test_controls_disabled_without_pause_also_preserves_graph(self):
        raw=room(84,[(85,'default',False)],visited=(84,))
        self.update(raw);old=deepcopy(self.service.routes.data)
        raw['room_index']=85;raw['input_lease']['controls_enabled']=False
        self.update(raw)
        self.assertEqual(self.service.routes.data,old)
        self.assertEqual(self.service.routes.routes(),[])

    def test_unreachable_room_exit_cannot_lure_a_remote_frontier(self):
        # Observed room 83 is split by a solid wall. From its right entrance
        # the left door exists, but the existing local executor cannot reach it.
        raw=room(83,[(82,'default',False),(84,'default',False)],visited=(83,84))
        raw['player_grid_index']=70;raw['player']['pos']={'x':440,'y':280}
        for d,grid,x in zip(raw['layout']['doors'],(60,74),(40,600)):
            d.update(grid_index=grid,pos={'x':x,'y':280})
        raw['layout']['blocked']=list(range(7,135,15))
        self.update(raw)
        self.assertFalse(self.service.routes.data['rooms']['83']['doors'][0]['locally_reachable'])
        self.assertFalse(any(o.get('route',{}).get('room')==82 for o in self.service._offers(GameState.from_message(raw))))
        self.update(room(84,[(83,'default',False),(85,'default',False)],2,visited=(83,84)))
        self.assertNotIn(82,{r['room'] for r in self.service.routes.routes()})
        self.assertIn(85,{r['room'] for r in self.service.routes.routes()})
        # Real geometry improvement, not selecting the same target again,
        # restores the branch while every existing execution guard remains.
        raw['layout']['blocked']=[];raw['room_visit_sequence']=3;self.update(raw)
        self.assertTrue(self.service.routes.data['rooms']['83']['doors'][0]['locally_reachable'])
        self.assertIn(82,{r['room'] for r in self.service.routes.routes()})

    def test_animation_and_reallocated_hazard_ids_do_not_reset_edge_budget(self):
        raw=room(84,[(85,'default',False)],visited=(84,85))
        raw['hazards']=[{'id':100,'kind':'fire','grid_index':33,'pos':{'x':120,'y':160}}]
        self.update(raw);progress=self.service.routes.data['progress']
        self.service.routes.data['edges']['84>85']=2
        raw['hazards'][0]['id']=200
        raw['layout']['doors'][0].update(target_clear=True,door_open=False,door_open_known=False)
        raw['layout']['blocked']=[7]
        self.update(raw)
        self.assertEqual(self.service.routes.data['progress'],progress)
        self.assertEqual(self.service.routes.data['edges']['84>85'],2)
        raw['layout']['doors'][0].update(door_open=True,door_open_known=True)
        self.update(raw)
        self.assertEqual(self.service.routes.data['edges']['84>85'],2)
        self.assertFalse(self.service.routes.routes())

    def test_schema_one_mixed_floor_cache_is_not_inherited(self):
        self.update(room(84,[(85,'default',False)],visited=(84,)))
        path=self.service.routes.path;old=deepcopy(self.service.routes.data)
        old['schema']=1;old['native_visited']=[1,2,3,84]
        path.write_text(json.dumps(old),'utf8')
        fresh=RouteMemory(path,lambda *a,**k:None)
        self.assertIsNone(fresh.data['floor'])
        self.assertFalse(fresh.data['native_visited'])


if __name__=='__main__':unittest.main()
