"""User's supply/DSH ownership and reward gates, without changing a real game."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
fixture_path=str(ROOT/'integration/isaac-agent/tests')
sys.path.insert(0,fixture_path)
try:
    from strategy_fixtures import scenario
finally:
    # Do not shadow identically named integration tests during discovery.
    sys.path.remove(fixture_path)
from integration.issac.game_policy import strategy_class
from isaac_jev.models import GameState
from isaac_jev.strategy import StrategyError


class AgencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.service=strategy_class(ROOT)(self.temp.name,clock=lambda:1000)
        self.service.core_actor_required=True
        self.service.configure(enabled=True,live=True)
        self.service.wiki_verifier=lambda receipts,context,item_id,**kw:receipts==['real-current-wiki']

    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def update(self,raw):
        self.service.update(raw,GameState.from_message(raw))

    def plan(self,offer):
        d=self.service.decision()
        return {'plan_id':'one','decision_id':d['id'],'context_id':d['context_id'],
                'offer_id':offer['id'],'budget':offer['cost'],'actor_id':'naimei',
                'core_session_id':'naimei-game-real',
                'assessment':{'growth':'本层可见道具有成长收益','key_recovery':'目前钥匙足够'}}

    def test_key_is_locally_authorized_before_competing_collectible(self):
        raw=scenario('pickup');key=deepcopy(raw['pickups'][0])
        # The native Mod sends `kind`; `pickup_kind` is only the parsed field.
        key.update(id=8,spawn_seed=8008,variant=30,subtype=1,name='Key',kind='key',is_collectible=False,options_index=0)
        raw['pickups'].append(key);raw['strategy']['pickups'].append(deepcopy(key))
        self.update(raw)
        self.assertIsNone(self.service.pending)
        receipt=next(iter(self.service.receipts.values()))
        self.assertEqual(receipt['actor_id'],'local_controller')
        self.assertEqual(self.service.command['offer']['action_id'],'take_pickup_8')
        self.assertEqual(receipt['cost'],dict(coins=0,keys=0,bombs=0,health_half_hearts=0))

    def test_collectible_cannot_be_picked_without_real_current_wiki_receipt(self):
        self.update(scenario('pickup'))
        offer=next(o for o in self.service.decision()['offers'] if o.get('target_id'))
        body=self.plan(offer)
        with self.assertRaisesRegex(StrategyError,'wiki evidence'):self.service.submit(body)
        body['wiki_receipts']=['real-current-wiki']
        result=self.service.submit(body)
        self.assertEqual(result['actor_id'],'naimei')
        self.assertEqual(result['assessment'],body['assessment'])

    def test_growth_and_key_recovery_are_mandatory_even_for_wait(self):
        self.update(scenario('pickup'))
        offer=next(o for o in self.service.decision()['offers'] if o['op']=='wait')
        body=self.plan(offer);del body['assessment']
        with self.assertRaisesRegex(StrategyError,'assessment required'):self.service.submit(body)
        self.assertIsNotNone(self.service.pending)

    def test_boss_observation_wiki_context_exists_without_a_pending_choice(self):
        raw=scenario('active');raw['strategy']['actives']=[]
        raw['strategy']['room_type']='boss';raw['enemies'][0].update(type=20,variant=0,subtype=0,is_boss=True)
        self.update(raw);self.service.pending=None
        context=self.service.wiki_context()
        self.assertTrue(context['decision_id'].startswith('observation-'))
        self.assertEqual(self.service.query('bosses')['data'][0]['type'],20)

    def test_floor_exit_is_not_a_free_fallback(self):
        raw=scenario('route');self.update(raw);self.service.pending=None
        self.service._current_offers=[]
        response=self.service.decorate_response({'enabled':True,'mode':'boss_exit'},GameState.from_message(raw))
        self.assertTrue(response['strategy']['hold'])
        self.assertIsNone(response['strategy']['command'])

    def test_floor_exit_requires_each_remaining_reward_and_its_wiki_lookup(self):
        raw=scenario('pickup')
        raw.update(boss_exit_available=True,boss_exit_grid_index=52,boss_exit_position={'x':320,'y':240})
        raw['strategy']['room_type']='boss';raw['layout']['room_type']='boss'
        self.update(raw)
        offer=next(o for o in self.service.decision()['offers'] if (o.get('action_id')or'').startswith('enter_boss_exit_'))
        body=self.plan(offer);body['wiki_receipts']=['real-current-wiki']
        with self.assertRaisesRegex(StrategyError,'every remaining floor reward'):self.service.submit(body)
        reward=self.service.reward_review()[0]
        body['reward_review']=[{'target_id':reward['target_id'],'disposition':'skip','reason':'当前同类收益不足，保留现有构筑'}]
        self.assertEqual(self.service.submit(body)['status'],'accepted')

    def test_previous_room_rewards_are_last_seen_and_disappear_after_revisit(self):
        raw=scenario('pickup');self.update(raw)
        other=scenario('route');other.update(room_index=84,room_visit_sequence=2);self.update(other)
        self.assertEqual(self.service.reward_review()[0]['observation'],'last_seen_requires_revisit')
        revisit=scenario('route');revisit['room_visit_sequence']=3;self.update(revisit)
        self.assertEqual(self.service.reward_review(),[])

class BossWikiTests(unittest.TestCase):
    def test_native_boss_query_rejects_ambiguous_or_extended_inputs(self):
        from integration.issac.wiki import arguments
        self.assertEqual(arguments({'operation':'boss','type':102,'variant':1,'subtype':0}),['boss','102','1','0'])
        for q in ({'operation':'boss','type':102,'variant':1},
                  {'operation':'boss','type':True,'variant':0,'subtype':0},
                  {'operation':'boss','type':102,'variant':0,'subtype':0,'sql':'select 1'}):
            with self.assertRaises(ValueError):arguments(q)

    @unittest.skipUnless((ROOT/'knowledge/issac-wiki/data/isaac.sqlite3').exists(),'offline pinned Wiki exists on the 4090 installation')
    def test_actual_fixed_wiki_distinguishes_isaac_from_blue_baby_by_variant(self):
        from integration.issac.wiki import WikiService
        service=WikiService(ROOT,sys.executable,lambda:None);service.prepare()
        a=service.boss_result({'type':102,'variant':0,'subtype':0})
        b=service.boss_result({'type':102,'variant':1,'subtype':0})
        self.assertTrue(a['exact_match']);self.assertTrue(b['exact_match'])
        self.assertNotEqual(a['records'][0]['alias'],b['records'][0]['alias'])
        self.assertEqual(a['records'][0]['alias'],'Isaac')
        unknown=service.boss_result({'type':102,'variant':999,'subtype':0})
        self.assertFalse(unknown['exact_match']);self.assertTrue(unknown['unknown'])
