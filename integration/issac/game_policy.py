"""Fair observed information and run-scoped strategic execution boundaries."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from .common import AdmissionError, digest


DOMAINS = ('active', 'active_special', 'pickup', 'pill', 'card', 'route', 'deal',
           'bomb_entry', 'planetarium', 'dice', 'sacrifice', 'terrain')


@dataclass(frozen=True)
class RunGoal:
    name: str = 'normal_progress'
    evidence: dict | None = None

    def validate(self, identity):
        if self.name == 'normal_progress':
            return {'id': self.name, 'description': '沿本局已观察且实际开放的合法出口推进',
                    'unlocks': 'unknown', 'fixed_for_run': True}
        if self.name not in {'mom', 'heart', 'satan', 'isaac', 'blue_baby', 'lamb',
                             'hush', 'delirium', 'mother', 'beast'}:
            raise AdmissionError('UNKNOWN_RUN_GOAL')
        e = self.evidence or {}
        if (e.get('source') != 'verified_native_observation' or e.get('goal') != self.name
                or e.get('available') is not True or e.get('run_identity') != identity):
            raise AdmissionError('RUN_GOAL_HAS_NO_CURRENT_LEGAL_EVIDENCE')
        return {'id': self.name, 'evidence': deepcopy(e), 'fixed_for_run': True}


class FairPolicy:
    def __init__(self, goal=None):
        self.goal = goal or RunGoal()
        self.run = None
        self.goal_view = None

    def filter(self, message):
        raw = deepcopy(message)
        strategy = raw.setdefault('strategy', {})
        identity = {k: raw.get(k) for k in ('start_seed', 'restart_count')}
        identity['bridge'] = strategy.get('bridge_generation')
        if identity != self.run:
            self.goal_view = self.goal.validate(identity)
            self.run = identity
        raw['run_goal'] = deepcopy(self.goal_view)
        raw['progression_target'] = '' if self.goal.name == 'normal_progress' else self.goal.name
        # No reviewed visible-wall inference rule currently exists. Remove all
        # engine-derived hidden adjacency before both the local and model paths.
        raw.setdefault('layout', {})['bomb_walls'] = []
        strategy['map'] = [x for x in strategy.get('map', [])
                           if isinstance(x, dict) and (int(x.get('display_flags') or 0) > 0
                                                      or int(x.get('visited') or 0) > 0)]
        for pocket in strategy.get('pockets', []):
            if pocket.get('kind') == 'pill' and pocket.get('identified') is not True:
                pocket.pop('effect', None)
                pocket.pop('effect_name', None)
                pocket['effect_supported'] = False
        raw['information_boundary'] = {
            'mode': 'structured_observed_game_state_not_screen_only',
            'hidden_room_adjacency': False, 'unknown_unlocks': 'unknown',
            'unknown_pills': 'unknown', 'health_input_units': 'half_hearts',
        }
        return raw


def decision_fence(raw):
    """Exclude moving coordinates while binding every spend/effect prerequisite."""
    s = raw.get('strategy') or {}
    return digest({
        'inventory': s.get('inventory_revision'), 'health': s.get('health'),
        'resources': {k: raw.get(k) for k in ('coins','keys','bombs')},
        'actives': s.get('actives'), 'pockets': s.get('pockets'),
        'trinkets': raw.get('held_trinkets'), 'clear': raw.get('room_clear'),
        'dice': s.get('dice'), 'sacrifice': s.get('sacrifice'),
        'pickups': [{k: p.get(k) for k in ('id','spawn_seed','type','variant','subtype','price','shop_item_id')}
                    for p in s.get('pickups', raw.get('pickups', []))],
        'doors': [{k: p.get(k) for k in ('slot','target_room_index','open','locked','room_type','state')}
                  for p in raw.get('layout',{}).get('doors',[])],
    })


def health_for_wiki(health):
    """Keep individual types and convert only the documented half-heart fields."""
    result = {'native_units': 'half_hearts', 'wiki_units': 'whole_hearts',
              'exact': health.get('exact') is True, 'character_type': health.get('character_type')}
    for name in ('red_hearts', 'max_hearts', 'soul_hearts'):
        value = health.get(name)
        result[name] = value / 2 if type(value) is int and value >= 0 else None
    # Bone/eternal/broken hearts and the black-heart bitmask have distinct native
    # meanings; do not divide every field by two or double-count black hearts.
    for name in ('bone_hearts', 'eternal_hearts', 'rotten_hearts', 'broken_hearts',
                 'golden_hearts', 'black_hearts_bitmask'):
        result[name] = health.get(name)
    result['black_hearts_are_included_in_soul_hearts'] = True
    return result


def attach_upstream(root):
    """Resolve only the copied pinned source; never a global package installation."""
    import sys
    from pathlib import Path
    source = Path(root).resolve() / 'integration/isaac-agent'
    sys.path.insert(0, str(source/'src'))
    sys.path.insert(0, str(source))
    return source


def strategy_class(root):
    attach_upstream(root)
    from isaac_jev.strategy import StrategyService, StrategyError, digest as upstream_digest

    class StreamStrategy(StrategyService):
        def __init__(self, log_dir, **kwargs):
            super().__init__(log_dir, **kwargs)
            self._live_run_goal = None
            self.core_actor_required = False
            self.floor_rewards = {}
            self.reward_floor = None
            self.wiki_verifier = None

        def update(self, raw, state=None):
            with self.lock:
                if self.snapshot:
                    if decision_fence(self.raw) != decision_fence(raw):
                        # Effects are observed before cancelling an in-flight command;
                        # only a pending model decision is invalidated by a new build.
                        if self.pending:
                            self.emit('decision_cancelled', decision_id=self.pending['id'],
                                      reason='decision_prerequisite_changed')
                            self.pending = None
                self._live_run_goal = deepcopy(raw.get('run_goal'))
                result = super().update(raw, state)
                self._remember_rewards()
                if self.pending:
                    self.pending['inventory_revision'] = self.snapshot.get('inventory_revision')
                return result

        def emit(self, kind, **data):
            if getattr(self, 'snapshot', None):
                data.setdefault('identity', deepcopy(self.snapshot.get('identity')))
                data.setdefault('frame', self.snapshot.get('frame'))
            return super().emit(kind, **data)

        def _remember_rewards(self):
            if not self.snapshot or self.snapshot['room'].get('paused'):return
            identity=self.snapshot['identity']
            floor=tuple(identity.get(k) for k in ('controller','seed','restart','bridge','stage','stage_type','dimension'))
            if floor!=self.reward_floor:self.floor_rewards={};self.reward_floor=floor
            # A new observation of a room replaces its old entity list. Other
            # rooms are explicitly labelled last-seen, never asserted current.
            room=identity['room']
            pickups=deepcopy(self.snapshot['pickups'])
            self.floor_rewards[room]={'room':room,'room_type':self.snapshot['room']['type'],
                'observed_frame':self.snapshot['frame'],'pickups':pickups}

        def _is_local_supply(self, offer):
            target=next((p for p in self.snapshot['pickups'] if p['target_id']==offer.get('target_id')),None)
            return bool(target and target.get('variant') in {10,20,30,40,50,51,52,53,54,55,56,57,58,60,69,70,90,300,350,360,390})

        def _offers(self, state):
            offers=super()._offers(state)
            if self.core_actor_required and state is not None:
                # A preferred collectible must not hide the ordinary supplies.
                supplies=replace(state,pickups=tuple(p for p in state.pickups if p.variant!=100))
                offers+= [o for o in super()._offers(supplies) if self._is_local_supply(o)]
            return list({o['id']:o for o in offers
                if not str(o.get('action_id','')).startswith(('bomb_secret_','bomb_super_secret_'))
                and not(self.core_actor_required and str(o.get('action_id','')).startswith('keep_trinket_'))}.values())

        def _local_offer(self, state, offers):
            if not self.core_actor_required:return None
            reserve_key=any(d.get('target_room_type')=='treasure' and d.get('door_locked') for d in self.snapshot['doors'])
            candidates=[o for o in offers if self._is_local_supply(o) and not o['cost'].get('health_half_hearts')
                and not(reserve_key and self.snapshot['resources']['keys']<=1 and o['cost'].get('keys'))]
            # Prioritize health and keys before money; preserve established
            # pocket/trinket preference, capacity, risk and path checks.
            def rank(o):
                p=next(p for p in self.snapshot['pickups'] if p['target_id']==o['target_id'])
                return ({10:0,30:1,20:2,40:3,90:4}.get(p.get('variant'),5),o['action_id'])
            return min(candidates,key=rank) if candidates else None

        def _accept_local_offer(self, offer):
            pending=self.pending
            body={'plan_id':'local-'+upstream_digest([pending['id'],offer['id']]),
                'decision_id':pending['id'],'context_id':upstream_digest(pending['identity']),
                'offer_id':offer['id'],'budget':deepcopy(offer['cost']),
                'reason':'local supply policy: capacity, risk, path and identity checked'}
            result=super().submit(body)
            self.receipts[result['plan_id']].update(actor_id='local_controller',authorization_source='local_supply_policy')
            self.emit('local_supply_accepted',receipt=deepcopy(self.receipts[result['plan_id']]),offer=deepcopy(offer))

        def reward_review(self):
            if not self.snapshot:return []
            current=self.snapshot['identity']['room'];result=[]
            for room,observed in self.floor_rewards.items():
                for pickup in observed['pickups']:
                    if pickup.get('variant')==100 and pickup.get('subtype',0)<=0:continue
                    result.append({**deepcopy(pickup),'room':room,'room_type':observed['room_type'],
                        'observed_frame':observed['observed_frame'],
                        'observation':'current_room' if room==current else 'last_seen_requires_revisit',
                        'owner':'naimei_core_dsh' if pickup.get('variant')==100 else 'local_controller'})
            return result

        def decision(self):
            with self.lock:return self._decision_locked()

        def _decision_locked(self):
            value = super().decision()
            if value.get('pending'):
                value['run_goal'] = deepcopy(self._live_run_goal)
                value['context']['wiki_health'] = health_for_wiki(value['context']['health'])
                value['context']['floor_reward_review']=self.reward_review()
                local=[o['id'] for o in value['offers'] if self._is_local_supply(o)] if self.core_actor_required else []
                value['offers']=[o for o in value['offers'] if o['id'] not in local]
                value['context']['required_assessment']={
                    'free_supplies':'local_controller collects safe reachable free supplies first',
                    'growth':'evaluate visible active/passive items against current build; do not skip without benefit/risk reasoning',
                    'key_recovery':{'keys':self.snapshot['resources']['keys'],
                        'known_keys':[x for x in self.reward_review() if x.get('variant')==30],
                        'locked_reward_doors':[x for x in self.snapshot['doors'] if x.get('door_locked') and x.get('target_room_type')=='treasure']}}
                value['information_boundary'] = self.raw.get('information_boundary', {})
            return value

        def wiki_context(self):
            with self.lock:
                if not self.fresh() or self.snapshot['room'].get('dead'):return None
                if self.pending and self.clock()<self.pending['deadline']:
                    return {'decision_id':self.pending['id'],'context_id':upstream_digest(self.pending['identity']),
                        'inventory_revision':self.snapshot.get('inventory_revision')}
                return {'decision_id':'observation-'+self.snapshot['revision'],
                    'context_id':upstream_digest(self.snapshot['identity']),
                    'inventory_revision':self.snapshot.get('inventory_revision')}

        def submit(self, body):
            with self.lock:
                if self.core_actor_required and (not isinstance(body,dict) or body.get('actor_id')!='naimei'
                        or not isinstance(body.get('core_session_id'),str)
                        or not body['core_session_id'].startswith(('naimei-game-','naimei-fact-','studio-'))):
                    raise StrategyError('Naimei core actor and actual DSH session are required')
                known=isinstance(body,dict) and body.get('plan_id') in self.receipts
                if self.pending and self.pending['identity'] != self.snapshot.get('identity'):
                    raise StrategyError('Current room/run/bridge differs from the offered context')
                if self.pending:
                    p = self.pending
                    if p.get('inventory_revision') is not None and p['inventory_revision'] != self.snapshot.get('inventory_revision'):
                        raise StrategyError('Inventory changed since the offer')
                if self.core_actor_required and self.pending:
                    offer=next((o for o in self.pending['offers'] if o['id']==body.get('offer_id')),None)
                    if offer and self._is_local_supply(offer):raise StrategyError('ordinary supply belongs to local controller')
                    if self.wiki_verifier is None:raise StrategyError('wiki evidence verifier required')
                    wiki_context=self.wiki_context()
                    target=next((p for p in self.snapshot['pickups'] if offer and p['target_id']==offer.get('target_id') and p.get('variant')==100),None)
                    if target and not self.wiki_verifier(body.get('wiki_receipts'),wiki_context,target.get('subtype')):
                        raise StrategyError('chosen item requires current verified wiki evidence')
                    assessment=body.get('assessment')
                    if not isinstance(assessment,dict) or any(not isinstance(assessment.get(k),str) or not 1<=len(assessment[k])<=160 for k in ('growth','key_recovery')):
                        raise StrategyError('growth and key recovery assessment required')
                    if offer and str(offer.get('action_id','')).startswith('enter_boss_exit_'):
                        reviews=body.get('reward_review',[])
                        if not isinstance(reviews,list):raise StrategyError('floor reward review required')
                        for p in self.reward_review():
                            if p.get('variant')==100 and not self.wiki_verifier(body.get('wiki_receipts'),wiki_context,p.get('subtype'),known_required=False):
                                raise StrategyError('remaining collectible requires wiki lookup before floor exit')
                            review=next((r for r in reviews if r.get('target_id')==p['target_id']),None)
                            if not review or review.get('disposition')!='skip' or not isinstance(review.get('reason'),str) or not 2<=len(review['reason'])<=160:
                                raise StrategyError('every remaining floor reward needs an explicit skip reason')
                result=super().submit(body)
                if body.get('actor_id')=='naimei':
                    receipt=self.receipts[result['plan_id']]
                    receipt.update(actor_id='naimei',core_session_id=body['core_session_id'],assessment=deepcopy(body.get('assessment')),reward_review=deepcopy(body.get('reward_review',[])),wiki_receipts=deepcopy(body.get('wiki_receipts',[])))
                    result=deepcopy(receipt)
                    if not known:self.emit('naimei_core_plan_accepted',plan_id=result['plan_id'],actor_id='naimei',core_session_id=body['core_session_id'])
                return result

    return StreamStrategy
