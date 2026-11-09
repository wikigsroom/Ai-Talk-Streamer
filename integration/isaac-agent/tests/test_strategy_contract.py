"""Safety and execution outcomes across the asynchronous strategy boundary."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from copy import deepcopy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from isaac_jev.strategy import StrategyService, StrategyError, DOMAINS
from isaac_jev.models import GameState
from isaac_jev.runtime import Controller
from strategy_fixtures import scenario


class StrategyContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.now=1000.0
        self.service=StrategyService(self.temp.name,clock=lambda:self.now,decision_seconds=20)
        self.service.configure(enabled=True,live=True)
    def tearDown(self): self.service.close();self.temp.cleanup()
    def update(self,raw): self.service.update(raw,GameState.from_message(raw))
    def plan(self,domain='pickup',key='one'):
        raw=scenario(domain);self.update(raw);d=self.service.decision()
        offer=next(o for o in d['offers'] if o['domain']==domain and o['op']!='wait')
        body={'plan_id':key,'decision_id':d['id'],'identity':d['identity'],'offer_id':offer['id'],'reason':'contract test','budget':offer['cost']}
        return raw,body,offer

    def test_all_twelve_domains_have_real_locally_constructed_offers(self):
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                self.service.pending=None;self.service.resolved.clear()
                self.update(scenario(domain))
                d=self.service.decision()
                self.assertIn(domain,{o['domain'] for o in d['offers']},d['offers'])

    def test_configured_decision_window_is_not_silently_truncated_to_thirty_seconds(self):
        for requested, expected in ((45,45),(60,60),(90,60)):
            with self.subTest(requested=requested):
                service=StrategyService(self.temp.name,clock=lambda:self.now,decision_seconds=requested)
                try:
                    service.configure(enabled=True)
                    raw=scenario('pickup');service.update(raw,GameState.from_message(raw))
                    self.assertEqual(service.decision()['remaining_ms'],expected*1000)
                finally:service.close()

    def test_query_is_detached_and_freshness_is_explicit(self):
        self.update(scenario());q=self.service.query();q['data']['health']['red_hearts']=0
        self.assertEqual(self.service.query('health')['data']['red_hearts'],8)
        self.now+=2;self.assertFalse(self.service.query()['connected'])

    def test_loading_wait_does_not_make_stale_state_or_authorization_fresh(self):
        raw=scenario('pickup');raw['strategy']['paused']=True;self.update(raw)
        self.now+=6
        self.assertTrue(self.service.native_engine_hold_grace())
        self.assertFalse(self.service.query()['connected'])
        response=self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        self.assertFalse(response['strategy']['owned'])
        self.assertIsNone(response['strategy']['command'])
        self.now+=4
        self.assertFalse(self.service.native_engine_hold_grace())

    def test_held_heartbeats_cannot_roll_the_loading_deadline_forward(self):
        raw=scenario();raw['strategy']['paused']=True;self.update(raw)
        self.now+=8;self.update(raw);self.assertTrue(self.service.native_engine_hold_grace())
        self.now+=2;self.update(raw);self.assertFalse(self.service.native_engine_hold_grace())

    def test_live_controls_explicit_pause_death_and_manual_override_have_no_loading_grace(self):
        for changes in ({}, {'strategy':{'paused':True,'pause_ack':{'ordinary_pause_input_issued':True}}},
                        {'strategy':{'paused':True,'manual_override':True}},
                        {'strategy':{'paused':True},'player_dead':True}):
            raw=scenario();raw.update(changes);self.update(raw);self.now+=2
            self.assertFalse(self.service.native_engine_hold_grace(),changes)

    def test_observed_disabled_controls_grace_clears_when_play_resumes_or_authority_is_withdrawn(self):
        raw=scenario();raw['input_lease']={'controls_enabled':False};self.update(raw)
        self.now+=6;self.assertTrue(self.service.native_engine_hold_grace())
        self.service.configure(enabled=False);self.assertFalse(self.service.native_engine_hold_grace())
        self.service.configure(enabled=True,live=True);raw['input_lease']['controls_enabled']=True;self.update(raw)
        self.now+=2;self.assertFalse(self.service.native_engine_hold_grace())

    def test_waiting_for_agent_is_not_failed_pickup_movement(self):
        controller=Controller(log_dir=self.temp.name,autopilot_enabled=True)
        controller.strategy_service=self.service
        raw=scenario('pickup')
        try:
            for frame in range(100,1300,6):
                raw.update(frame=frame,last_action_id='strategy_safe_hold',last_action_mode='strategy_hold',
                           movement_blocked=True,movement_progress=0)
                response=controller.receive_state(raw)
                self.assertEqual(response['mode'],'strategy_hold')
                self.assertEqual(controller._effective_action.mode,'strategy_hold')
            self.assertNotIn(7,controller._ignored_pickup_ids)
            self.assertEqual(controller._movement_stall_count,0)
            decision=self.service.decision()
            offer=next(o for o in decision['offers'] if o.get('target_id'))
            self.service.submit({'plan_id':'after-hold','decision_id':decision['id'],'identity':decision['identity'],
                                 'offer_id':offer['id'],'budget':offer['cost']})
            raw['frame']+=6
            response=controller.receive_state(raw)
            self.assertEqual(response['source'],'dsh')
            self.assertNotIn(7,response['ignored_pickup_ids'])
            self.assertEqual(controller._effective_action.action_id,response['id'])
            seq=response['action_sequence']
            raw['frame']+=6
            self.assertEqual(controller.receive_state(raw)['action_sequence'],seq)
        finally:controller.shutdown()

    def test_identity_is_not_frame_number_and_black_hearts_is_bitmask(self):
        raw,body,_=self.plan();raw['frame']+=6;self.update(raw)
        self.assertEqual(self.service.submit(body)['status'],'accepted')
        self.assertEqual(self.service.query('health')['data']['black_hearts_bitmask'],4)

    def test_plan_id_is_idempotent_even_after_decision_consumed(self):
        raw,body,_=self.plan();first=self.service.submit(body)
        self.assertEqual(first,self.service.submit(body));self.assertIsNotNone(self.service.command)

    def test_reused_entity_index_with_new_spawn_seed_is_rejected(self):
        raw,body,_=self.plan();raw['strategy']['pickups'][0]['spawn_seed']+=1;self.update(raw)
        with self.assertRaises(StrategyError):self.service.submit(body)

    def test_price_and_resources_rechecked_while_model_thinks(self):
        raw,body,_=self.plan();raw['strategy']['pickups'][0]['price']=15;raw['coins']=1;self.update(raw)
        with self.assertRaises(StrategyError):self.service.submit(body)

    def test_old_room_and_late_model_reply_are_rejected(self):
        raw,body,_=self.plan();raw['room_index']+=1;self.update(raw)
        with self.assertRaises(StrategyError):self.service.submit(body)
        self.service.pending=None;self.service.resolved.clear()
        raw,body,_=self.plan(key='two');self.now+=21
        with self.assertRaises(StrategyError):self.service.submit(body)

    def test_unknown_pill_is_observable_but_not_executable(self):
        raw=scenario('pill');raw['strategy']['pockets'][0].update(identified=False,effect=None,effect_supported=False)
        self.update(raw)
        self.assertFalse(any(o['domain']=='pill' for o in self.service.decision()['offers']))
        self.assertIsNone(self.service.query('pockets')['data'][0]['effect'])

    def test_health_trade_cannot_be_submitted_as_free(self):
        raw,body,offer=self.plan('deal');self.assertEqual(offer['cost']['health_half_hearts'],2)
        body['budget']={'coins':0,'keys':0,'bombs':0,'health_half_hearts':0}
        with self.assertRaises(StrategyError):self.service.submit(body)

    def test_locked_chest_requires_explicit_key_budget_and_native_pickup_target(self):
        raw=scenario('pickup')
        p=raw['strategy']['pickups'][0]
        p.update(variant=60,subtype=0,is_collectible=False,kind='locked_chest',options_index=0)
        raw['pickups']=[deepcopy(p)];self.update(raw)
        d=self.service.decision();offer=next(o for o in d['offers'] if o.get('action_id')=='open_chest_7')
        self.assertEqual(offer['cost']['keys'],1)
        body={'plan_id':'chest','decision_id':d['id'],'context_id':d['context_id'],'offer_id':offer['id'],'budget':offer['cost']}
        self.service.submit(body)
        response=self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        self.assertEqual(response['strategy']['command']['target']['id'],7)
        raw['keys']=0;self.update(raw)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        self.assertEqual(self.service.receipts['chest']['status'],'indeterminate')

    def test_room_only_damage_active_cannot_be_wasted_after_room_clears(self):
        raw,body,_=self.plan('active');raw['room_clear']=True;raw['enemies']=[];self.update(raw)
        with self.assertRaises(StrategyError):self.service.submit(body)

    def test_combat_card_is_only_offered_during_combat_and_is_rechecked_after_delay(self):
        raw=scenario('card');raw['strategy']['pockets'][0]['id']=4
        self.update(raw)
        self.assertFalse(any(o['domain']=='card' for o in self.service.decision()['offers']))
        raw['room_clear']=False;raw['enemies']=[{'id':8,'type':12,'pos':{'x':500,'y':280},'hp':10}]
        self.service.pending=None;self.service.resolved.clear();self.update(raw)
        d=self.service.decision();offer=next(o for o in d['offers'] if o['domain']=='card')
        body={'plan_id':'combat-card','decision_id':d['id'],'context_id':d['context_id'],'offer_id':offer['id'],'budget':offer['cost']}
        raw['room_clear']=True;raw['enemies']=[];self.update(raw)
        with self.assertRaises(StrategyError):self.service.submit(body)

    def test_unknown_sacrifice_count_and_special_health_reject_payment(self):
        raw=scenario('sacrifice');raw['strategy']['sacrifice']['known']=False;self.update(raw)
        self.assertFalse(any(o['domain']=='sacrifice' for o in self.service.decision()['offers']))
        raw=scenario('deal');raw['strategy']['health']['bone_hearts']=1
        self.service.pending=None;self.service.resolved.clear();self.update(raw)
        self.assertFalse(any(o.get('guard',{}).get('price',0)<0 for o in self.service.decision()['offers']))

    def test_bible_against_satan_is_not_offered(self):
        raw=scenario('active');raw['strategy']['actives'][0]['id']=33
        raw['enemies']=[{'id':8,'type':84,'pos':{'x':300,'y':200},'hp':100,'is_boss':True}];raw['room_clear']=False
        self.update(raw);self.assertFalse(self.service.decision().get('pending'))

    def test_emergency_combat_preempts_pickup_and_never_holds_firing(self):
        raw,body,_=self.plan();self.service.submit(body)
        raw['enemies']=[{'id':8,'type':10,'pos':{'x':300,'y':200},'hp':100}];raw['room_clear']=False;self.update(raw)
        response={'type':'action','enabled':True,'id':'shoot','mode':'combat','move':{'x':1,'y':0},'shoot':{'x':0,'y':1}}
        result=self.service.decorate_response(response,GameState.from_message(raw))
        self.assertEqual(result['id'],'shoot');self.assertFalse(result['strategy']['hold'])
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'cancelled')

    def test_utility_issued_once_and_requires_observed_consumption(self):
        raw,body,_=self.plan('active');self.service.submit(body)
        response={'enabled':True,'id':'local'}
        result=self.service.decorate_response(response,GameState.from_message(raw))
        self.assertIsNotNone(result['strategy']['command'])
        result=self.service.decorate_response(response,GameState.from_message(raw))
        self.assertIsNone(result['strategy']['command'])
        raw['strategy']['actives'][0].update(charge=0,ready=False);self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'succeeded')

    def test_uncertain_consumable_effect_is_not_retried(self):
        raw,body,_=self.plan('card');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw));self.now+=13;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'indeterminate')
        self.assertEqual(self.service.submit(body)['status'],'indeterminate')

    def test_bomb_consumption_waits_for_observed_opening_and_never_places_twice(self):
        raw,body,_=self.plan('bomb_entry');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['bombs']-=1;raw['bomb_active']=True;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'issued')
        self.assertEqual(self.service.receipts[body['plan_id']]['stage'],'bomb_spent_waiting_for_target_effect')
        response=self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        self.assertTrue(response['strategy']['hold']);self.assertIsNone(response['strategy']['command'])
        raw['bomb_active']=False;raw['layout']['doors'].append(dict(slot=0,target_room_index=42,target_room_type='secret',
            door_open=True,door_open_known=True,pos={'x':80,'y':280}))
        self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['effect'],'native_bomb_opening_observed')
        self.assertEqual(self.service.submit(body)['status'],'succeeded')

    def test_spent_bomb_without_observed_opening_times_out_as_uncertain(self):
        raw,body,_=self.plan('bomb_entry');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['bombs']-=1;self.update(raw);self.now+=13;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'indeterminate')
        self.assertIsNone(self.service.command)

    def test_manual_stop_and_controller_restart_reject_old_plan(self):
        raw,body,_=self.plan();self.service.configure(enabled=False)
        with self.assertRaises(StrategyError): self.service.submit(body)
        other=StrategyService(self.temp.name,clock=lambda:self.now)
        try:
            other.configure(enabled=True,live=True);other.update(raw,GameState.from_message(raw))
            with self.assertRaises(StrategyError): other.submit(body)
        finally: other.close()

    def test_route_survives_local_preference_change_but_not_a_lock_change(self):
        raw,body,offer=self.plan('route')
        self.assertEqual(offer['op'],'select_action')
        raw['layout']['doors'].append(dict(raw['layout']['doors'][0],slot=2,target_room_index=98,pos={'x':520,'y':280},grid_index=103))
        raw.update(planned_door_slot=2,planned_goal='committed navigation choice')
        self.update(raw);self.service.submit(body)
        response=self.service.decorate_response({'enabled':True,'door_slot':2},GameState.from_message(raw))
        self.assertEqual(response['id'],offer['action_id'])
        self.assertEqual(response['door_slot'],1)
        self.assertEqual(response['target_room_index'],84)
        self.assertEqual(response['source'],'dsh')
        raw['layout']['doors'][0]['door_open']=False;self.update(raw)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'indeterminate')

    def test_restart_or_bridge_reload_is_not_a_successful_door_transition(self):
        for field in ['start_seed','restart_count','bridge_generation']:
            with self.subTest(field=field):
                self.service.pending=None;self.service.command=None;self.service.resolved.clear()
                raw,body,_=self.plan('route',key=field);self.service.submit(body)
                self.service.decorate_response({'enabled':True},GameState.from_message(raw))
                if field=='bridge_generation':raw['strategy'][field]='replacement'
                else:raw[field]=raw.get(field,0)+1
                raw['room_index']=84;self.update(raw)
                self.assertEqual(self.service.receipts[field]['status'],'indeterminate')

    def test_actual_selected_door_transition_is_success(self):
        raw,body,_=self.plan('route');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['room_index']=84;raw['room_visit_sequence']+=1;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'succeeded')

    def test_short_engine_pause_before_the_selected_room_transition_preserves_the_actual_effect(self):
        raw,body,_=self.plan('route');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['strategy']['paused']=True;raw['frame']+=1;self.update(raw)
        result=self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        self.assertTrue(result['strategy']['hold']);self.assertIsNone(result['strategy']['command'])
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'issued')
        self.now+=.1;raw['room_index']=84;raw['room_visit_sequence']+=1;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'succeeded')

    def test_stable_or_explicit_pause_does_not_keep_an_old_route_authorized(self):
        for explicit in [False,True]:
            with self.subTest(explicit=explicit):
                self.service.pending=None;self.service.command=None;self.service.resolved.clear()
                raw,body,_=self.plan('route',key=str(explicit));self.service.submit(body)
                self.service.decorate_response({'enabled':True},GameState.from_message(raw))
                raw['strategy']['paused']=True
                if explicit:raw['strategy']['pause_ack']={'paused':True,'frame':raw['frame'],'id':'operator'}
                self.update(raw)
                if not explicit:self.now+=.8;self.update(raw)
                self.assertEqual(self.service.receipts[body['plan_id']]['status'],'cancelled')
                self.assertIsNone(self.service.command)

    def test_quick_same_room_pause_resume_cannot_replay_an_issued_route(self):
        raw,body,_=self.plan('route');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['strategy']['paused']=True;self.update(raw);self.now+=.1
        raw['strategy']['paused']=False;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'cancelled')

    def test_room_transition_after_pause_grace_is_not_claimed_as_success(self):
        raw,body,_=self.plan('route');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['strategy']['paused']=True;self.update(raw);self.now+=.8
        raw['room_index']=84;raw['room_visit_sequence']+=1;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'indeterminate')

    def test_pending_or_unissued_choices_are_cancelled_immediately_on_pause(self):
        raw,body,_=self.plan();raw['strategy']['paused']=True;self.update(raw)
        with self.assertRaises(StrategyError):self.service.submit(body)
        raw['strategy']['paused']=False;self.service.resolved.clear();self.update(raw)
        d=self.service.decision();o=next(o for o in d['offers'] if o['op']!='wait')
        self.service.submit({'plan_id':'not-issued','decision_id':d['id'],'identity':d['identity'],'offer_id':o['id'],'budget':o['cost']})
        raw['strategy']['paused']=True;self.update(raw)
        self.assertEqual(self.service.receipts['not-issued']['status'],'cancelled')

    def test_consumed_collectible_waits_for_its_delayed_inventory_delta_without_reissue(self):
        raw,body,_=self.plan('pickup');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['strategy']['pickups']=[];raw['pickups']=[];self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'issued')
        result=self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        self.assertTrue(result['strategy']['hold']);self.assertIsNone(result['strategy']['command'])
        self.now+=.3;raw['strategy']['inventory'][0]['count']=2;raw['strategy']['inventory_revision']='1x2';self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'succeeded')

    def test_unrelated_resource_delta_cannot_prove_a_missing_collectible_was_acquired(self):
        raw,body,_=self.plan('pickup');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['strategy']['pickups']=[];raw['pickups']=[];raw['bombs']+=1;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'issued')
        self.now+=1.1;self.update(raw)
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'indeterminate')

    def test_combat_preempts_the_missing_pickup_observation_hold(self):
        raw,body,_=self.plan('pickup');self.service.submit(body)
        self.service.decorate_response({'enabled':True},GameState.from_message(raw))
        raw['strategy']['pickups']=[];raw['pickups']=[];self.update(raw)
        raw['room_clear']=False;raw['enemies']=[{'id':8,'type':10,'pos':{'x':300,'y':200},'hp':100}];self.update(raw)
        result=self.service.decorate_response({'enabled':True,'id':'shoot','shoot':{'x':1,'y':0}},GameState.from_message(raw))
        self.assertEqual(result['id'],'shoot');self.assertFalse(result['strategy']['hold'])
        self.assertEqual(self.service.receipts[body['plan_id']]['status'],'cancelled')

    def test_empty_room_without_candidates_does_not_spend_a_model_turn_on_wait(self):
        raw=scenario();raw['layout']['doors']=[];self.update(raw)
        self.assertFalse(self.service.decision().get('pending'))

    def test_wait_cannot_fall_back_to_the_declined_pickup_or_a_paid_door(self):
        raw=scenario('pickup');self.update(raw);d=self.service.decision()
        wait=next(o for o in d['offers'] if o['op']=='wait')
        self.service.submit({'plan_id':'defer','decision_id':d['id'],'identity':d['identity'],'offer_id':wait['id'],'budget':wait['cost']})
        self.update(raw)
        self.assertFalse(any(o.get('target_id') for o in self.service.decision()['offers']))
        self.service.pending=None
        for response in [dict(enabled=True,id='take_item_7',mode='item'),dict(enabled=True,id='bomb_wall_0',mode='bomb_wall')]:
            result=self.service.decorate_response(response,GameState.from_message(raw))
            self.assertEqual(result['id'],'enter_door_1')
            self.assertEqual(result['source'],'local-strategy-fallback')
        response=dict(enabled=True,id='enter_door_1',mode='navigate')
        self.assertFalse(self.service.decorate_response(response,GameState.from_message(raw))['strategy']['hold'])
        raw['layout']['doors'][0]['door_locked']=True
        self.assertTrue(self.service.decorate_response(response,GameState.from_message(raw))['strategy']['hold'])

    def test_model_timeout_can_leave_a_declined_pickup_by_free_route_without_consuming_it(self):
        raw=scenario('pickup');self.update(raw);self.now+=21;self.update(raw)
        self.assertFalse(self.service.decision()['pending'])
        response=self.service.decorate_response(dict(enabled=True,id='take_item_7',mode='item'),GameState.from_message(raw))
        self.assertEqual(response['id'],'enter_door_1')
        self.assertIsNone(response['strategy']['command'])
        self.assertFalse(response['strategy']['hold'])
        raw['layout']['doors'][0]['target_room_type']='angel'
        self.assertTrue(self.service.decorate_response(dict(enabled=True,id='take_item_7',mode='item'),GameState.from_message(raw))['strategy']['hold'])


if __name__=='__main__':unittest.main()
