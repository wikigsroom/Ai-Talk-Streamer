"""Fair observed information and run-scoped strategic execution boundaries."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
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
                if self.pending:
                    self.pending['inventory_revision'] = self.snapshot.get('inventory_revision')
                return result

        def emit(self, kind, **data):
            if getattr(self, 'snapshot', None):
                data.setdefault('identity', deepcopy(self.snapshot.get('identity')))
                data.setdefault('frame', self.snapshot.get('frame'))
            return super().emit(kind, **data)

        def _offers(self, state):
            return [o for o in super()._offers(state)
                    if not str(o.get('action_id', '')).startswith(('bomb_secret_', 'bomb_super_secret_'))
                    and 'bomb_wall' not in o.get('guard', {})]

        def decision(self):
            value = super().decision()
            if value.get('pending'):
                value['run_goal'] = deepcopy(self._live_run_goal)
                value['context']['wiki_health'] = health_for_wiki(value['context']['health'])
                value['information_boundary'] = self.raw.get('information_boundary', {})
            return value

        def wiki_context(self):
            with self.lock:
                if not self.pending or not self.fresh() or self.clock() >= self.pending['deadline']:
                    return None
                if self.snapshot['room'].get('dead') or self.snapshot['room'].get('paused'):
                    return None
                return {'decision_id': self.pending['id'],
                        'context_id': upstream_digest(self.pending['identity']),
                        'inventory_revision': self.snapshot.get('inventory_revision')}

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
                result=super().submit(body)
                if body.get('actor_id')=='naimei':
                    receipt=self.receipts[result['plan_id']]
                    receipt.update(actor_id='naimei',core_session_id=body['core_session_id'])
                    result=deepcopy(receipt)
                    if not known:self.emit('naimei_core_plan_accepted',plan_id=result['plan_id'],actor_id='naimei',core_session_id=body['core_session_id'])
                return result

    return StreamStrategy
