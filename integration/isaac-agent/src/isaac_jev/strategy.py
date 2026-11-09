"""Bounded strategic decisions. No network inference or native requests on the frame path."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import queue
import threading
import time
import uuid
from typing import Any

from .models import Action, GameState, Vec2
from .decision import build_candidate_set
from .navigation import move_towards, path_distance, door_is_usable, door_path_distance
from .route_memory import RouteMemory

DOMAINS = {
    'active': '主动道具', 'active_special': '一次性/重骰/传送主动',
    'pickup': '道具组合与拾取', 'pill': '药丸', 'card': '塔罗牌与符文',
    'route': '楼层路线', 'deal': '天使/恶魔房', 'bomb_entry': '炸弹开路',
    'planetarium': '星象房与跳过宝箱房', 'dice': '骰子房',
    'sacrifice': '献祭房', 'terrain': '特殊地形路线',
}

# Verified 1.7.9b ids. Unknown consumables/effects are observable but not executable.
# This is a capability registry, not an assertion that all synergies are known.
ACTIVE = {
    45: ('Yum Heart', 'active', 'heals one red heart'),
    33: ('The Bible', 'active', 'flight; kills Mom/Heart; kills player against Satan'),
    34: ('The Book of Belial', 'active', 'damage bonus for current room'),
    35: ('The Necronomicon', 'active', 'room damage'),
    36: ('The Poop', 'active', 'creates a poop obstacle'),
    38: ('Book of Revelations', 'active', 'adds soul heart; affects boss pool'),
    58: ('Book of Shadows', 'active', 'temporary invulnerability'),
    83: ('The Nail', 'active', 'temporary combat boost and heart effect'),
    97: ('The Book of Sin', 'active', 'spawns a random pickup'),
    105: ('The D6', 'active_special', 'rerolls room pedestals; irreversible'),
    133: ('Guppy\'s Paw', 'active_special', 'consumes a red-heart container'),
    145: ('Guppy\'s Head', 'active', 'spawns blue flies'),
    146: ('Prayer Card', 'active', 'adds an eternal heart'),
    160: ('Crack the Sky', 'active', 'room damage'),
    166: ('D20', 'active_special', 'rerolls room pickups'),
    181: ('White Pony', 'active', 'directed dash; local executor unsupported'),
    283: ('D100', 'active_special', 'rerolls build and room contents'),
    288: ('Box of Spiders', 'active', 'spawns blue spiders'),
    295: ('Magic Fingers', 'active', 'consumes one coin for room damage'),
    347: ('Diplopia', 'active_special', 'one use; duplicates room pickups'),
    351: ('Mega Bean', 'active', 'room combat effect'),
    419: ('Teleport 2.0', 'active_special', 'teleports to an unexplored room'),
    439: ('Mom\'s Box', 'active', 'spawns a trinket'),
    477: ('Void', 'active_special', 'absorbs room pedestal items'),
    489: ('D Infinity', 'active_special', 'effect depends on selected die; unsupported'),
    545: ('Book of the Dead', 'active', 'uses room corpses'),
    556: ('Sulfur', 'active', 'temporary Brimstone'),
}
UNSUPPORTED_ACTIVE = {181, 489}
COMBAT_ONLY_ACTIVE = {34, 35, 58, 160, 295, 351, 556}
HARD_ITEMS = {168, 329, 358, 233, 394, 273, 352, 474}
CARD_RULES = {
    1: ('The Fool', 'teleport'), 3: ('The High Priestess', 'combat'),
    4: ('The Empress', 'combat'), 5: ('The Emperor', 'teleport'),
    8: ('The Chariot', 'combat'), 9: ('Justice', 'pickup'),
    10: ('The Hermit', 'teleport'), 11: ('Wheel of Fortune', 'pickup'),
    12: ('Strength', 'combat'), 13: ('The Hanged Man', 'flight'),
    14: ('Death', 'combat'), 15: ('Temperance', 'pickup'),
    16: ('The Devil', 'combat'), 17: ('The Tower', 'dangerous'),
    18: ('The Stars', 'teleport'), 19: ('The Moon', 'teleport'),
    20: ('The Sun', 'heal'), 21: ('Judgement', 'pickup'),
    22: ('The World', 'map'), 23: ('2 of Clubs', 'resource'),
    24: ('2 of Diamonds', 'resource'), 25: ('2 of Spades', 'resource'),
    26: ('2 of Hearts', 'heal'), 31: ('Joker', 'teleport'),
    32: ('Hagalaz', 'terrain'), 33: ('Jera', 'duplicate'),
    34: ('Ehwaz', 'exit'), 35: ('Dagaz', 'heart'), 36: ('Ansuz', 'map'),
    38: ('Berkano', 'combat'), 39: ('Algiz', 'combat'),
}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()[:20]


class StrategyError(ValueError):
    pass


class StrategyService:
    """One authoritative state cache, one pending decision, one bounded command."""

    def __init__(self, log_dir: str | Path, *, clock=time.monotonic, decision_seconds=45.0):
        self.clock = clock
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.incarnation = uuid.uuid4().hex
        self.enabled = False
        self.live = False
        self.reason = 'observation_only'
        self.raw: dict = {}
        self.snapshot: dict = {}
        self.received = 0.0
        self.engine_hold_since = None
        self.counter = 0
        self.events: deque = deque(maxlen=256)
        self.receipts: dict[str, dict] = {}
        self.resolved: set[str] = set()
        self.pending: dict | None = None
        self.command: dict | None = None
        self.decision_seconds = min(60, max(2, decision_seconds))
        self.agent_heartbeat = 0.0
        self.state_latency: deque = deque(maxlen=500)
        self.catalog: dict[int, dict] = {}
        self.history = {'room_observations': [], 'transactions': []}
        self._stop = threading.Event()
        self._writes: queue.Queue = queue.Queue(maxsize=1024)
        self._logger = threading.Thread(target=self._write_loop, daemon=True)
        self._logger.start()
        self.routes = RouteMemory(self.log_dir / 'route-memory.json', self.emit)
        self._current_offers = []

    def _write_loop(self):
        while not self._stop.is_set() or not self._writes.empty():
            try: value = self._writes.get(timeout=.2)
            except queue.Empty: continue
            with (self.log_dir / 'strategy-events.jsonl').open('a', encoding='utf8') as stream:
                stream.write(json.dumps(value, ensure_ascii=False) + '\n')

    def close(self):
        self._stop.set()
        self._logger.join(timeout=2)

    def emit(self, kind, **data):
        self.counter += 1
        event = {'seq': self.counter, 'kind': kind, 'at': time.time(), **data}
        self.events.append(event)
        try: self._writes.put_nowait(event)
        except queue.Full: self.reason = 'audit_queue_full'; self.enabled = False
        return event

    def configure(self, *, enabled: bool, live: bool = False):
        with self.lock:
            if enabled and not self.enabled:
                self.resolved.clear()
            self.enabled, self.live = bool(enabled), bool(live and enabled)
            if not enabled:
                self._cancel('manual_stop')
            self.reason = 'armed' if self.live else 'observation_only'
            self.emit('configuration', enabled=self.enabled, live=self.live)
            return self.status()

    def _cancel(self, reason):
        if reason != 'context_changed':
            self.routes.suspend(reason)
        if self.pending:
            self.emit('decision_cancelled', decision_id=self.pending['id'], reason=reason)
            self.pending = None
        if self.command:
            self._finish('cancelled', reason)

    def _identity(self, raw):
        return {
            'controller': self.incarnation, 'seed': raw.get('start_seed'),
            'restart': raw.get('restart_count', 0), 'stage': raw.get('stage'),
            'stage_type': raw.get('stage_type'), 'dimension': raw.get('dimension', 0),
            'room': raw.get('room_index'), 'visit': raw.get('room_visit_sequence'),
            'bridge': raw.get('strategy', {}).get('bridge_generation'),
        }

    def update(self, raw: dict, state: GameState | None = None):
        start = self.clock()
        # Copy at the boundary. Query callers can never mutate the controller state.
        with self.lock:
            previous = self.snapshot
            self.raw = deepcopy(raw)
            self.received = self.clock()
            extra = self.raw.get('strategy') or {}
            # Loading/extra animations can stop both simulation and Lua render
            # callbacks. This is a bounded wait certificate, never fresh state
            # or an extension of the 1.5 s native authorization lease.
            ack = extra.get('pause_ack') or {}
            engine_held = (extra.get('paused') is True or
                           self.raw.get('input_lease', {}).get('controls_enabled') is False)
            if (engine_held and not ack.get('ordinary_pause_input_issued')
                    and not raw.get('player_dead') and not extra.get('manual_override')):
                if self.engine_hold_since is None:
                    self.engine_hold_since = self.received
            else:
                self.engine_hold_since = None
            for item in extra.get('catalog', []): self.catalog[item['id']] = item
            identity = self._identity(raw)
            if not previous or previous.get('identity') != identity:
                if previous and any(previous['identity'].get(k)!=identity.get(k) for k in ('seed','restart')):
                    self.history = {'room_observations': [], 'transactions': []}
                self.history['room_observations'].append({'identity':deepcopy(identity),'frame':raw.get('frame'),
                    'type':extra.get('room_type', raw.get('layout',{}).get('room_type')),
                    'kind':'attached' if not previous else 'context_changed'})
                self.history['room_observations'] = self.history['room_observations'][-128:]
            player = raw.get('player') or {}
            health = deepcopy(extra.get('health') or {})
            if not health:
                health = {k: player.get(k) for k in ('red_hearts', 'max_hearts', 'soul_hearts', 'bone_hearts', 'eternal_hearts')}
                health.update(black_hearts_bitmask=player.get('black_hearts'), units='half_hearts', exact=False)
            pickups = deepcopy(extra.get('pickups', raw.get('pickups', [])))
            for p in pickups:
                p['target_id'] = digest([identity, p.get('id'), p.get('spawn_seed'), p.get('type'), p.get('variant'), p.get('subtype')])
            self.snapshot = {
                'schema': 'isaac-strategy/1', 'source': extra.get('source', 'native_game'), 'identity': identity, 'frame': raw.get('frame'),
                'health': health, 'player': deepcopy(player),
                'inventory': deepcopy(extra.get('inventory', [])),
                'inventory_known': extra.get('inventory_known', False),
                'inventory_revision': extra.get('inventory_revision'),
                'effects': deepcopy(extra.get('effects', {'known':False})),
                'history': deepcopy(self.history),
                'actives': deepcopy(extra.get('actives', [])),
                'pockets': deepcopy(extra.get('pockets', [])),
                'trinkets': deepcopy(raw.get('held_trinkets', [])),
                'resources': {k: raw.get(k, 0) for k in ('coins', 'keys', 'bombs')},
                'room': {'index': raw.get('room_index'), 'type': extra.get('room_type', raw.get('layout', {}).get('room_type')),
                         'clear': bool(raw.get('room_clear')), 'dead': bool(raw.get('player_dead')),
                         'paused': bool(extra.get('paused')), 'pause_ack': extra.get('pause_ack'),
                         'exit': {'known': 'boss_exit_available' in raw,
                                  'available': bool(raw.get('boss_exit_available')),
                                  'grid_index': raw.get('boss_exit_grid_index', -1)},
                         'sacrifice': deepcopy(extra.get('sacrifice', {'count': None, 'known': False})),
                         'dice': deepcopy(extra.get('dice')), 'terrain': deepcopy(raw.get('layout', {}).get('grid_events', []))},
                'map': deepcopy(extra.get('map', [])),
                'doors': deepcopy(raw.get('layout', {}).get('doors', [])),
                'enemies': deepcopy(raw.get('enemies', [])),
                'bosses': [deepcopy(x) for x in raw.get('enemies', []) if x.get('is_boss')],
                'pickups': pickups, 'projectiles': deepcopy(raw.get('projectiles', [])),
                'danger_effects': deepcopy(raw.get('danger_effects', [])),
                'capabilities': {'active_slots': [0], 'pocket_slots': [0], 'normal_health_spending_characters': [0],
                                 'unknown_effects_executable': False},
            }
            self.snapshot['revision'] = digest({k: self.snapshot[k] for k in
                ('identity', 'health', 'inventory_revision', 'actives', 'pockets', 'resources', 'doors', 'pickups')})
            self.routes.observe(self.snapshot, self.raw, state)
            self.snapshot['route_progress'] = self.routes.describe()
            changed = previous and previous.get('identity') != identity
            if changed:
                # A room transition may be the successful effect of the command.
                if self.command and self.command.get('issued'):
                    command = self.command
                    offer = command['offer']
                    origin = command['identity']
                    same_run = all(origin.get(k) == identity.get(k) for k in ('controller', 'seed', 'restart', 'bridge'))
                    moved = any(origin.get(k) != identity.get(k) for k in ('room', 'stage', 'stage_type', 'dimension'))
                    door = offer.get('guard', {}).get('door')
                    same_floor = all(origin.get(k) == identity.get(k) for k in ('stage', 'stage_type', 'dimension'))
                    expected_door = bool(door and same_floor and door.get('target_room_index') == identity.get('room'))
                    expected_exit = bool((offer.get('action_id') or '').startswith('enter_boss_exit_')
                        and command['before']['room'].get('exit', {}).get('available')
                        and identity.get('stage') == origin.get('stage', -2) + 1
                        and identity.get('dimension') == origin.get('dimension'))
                    pause = command.get('transition_pause')
                    within_pause_grace = not pause or self.clock() <= pause['deadline']
                    if same_run and moved and within_pause_grace and (offer.get('effect') == 'teleport' or expected_door or expected_exit):
                        self._finish('succeeded', 'native_floor_transition_observed' if expected_exit else 'native_room_transition_observed')
                    else:
                        self._finish('indeterminate', 'context_changed_without_expected_effect')
                self._cancel('context_changed')
            elif previous and (raw.get('frame', 0) < previous.get('frame', 0)):
                self._cancel('frame_regression')
            if raw.get('player_dead') or extra.get('manual_override'):
                self._cancel('dead_manual_override_or_paused')
            elif extra.get('paused'):
                # Room transitions briefly report IsPaused before the new room
                # identity arrives. Hold inputs and only retain an already-issued
                # route for 750 ms; this never authorizes a resume or new action.
                if self.pending:
                    self.emit('decision_cancelled', decision_id=self.pending['id'], reason='native_paused')
                    self.pending = None
                if self.command:
                    c = self.command
                    ack = extra.get('pause_ack') or {}
                    explicit_pause = ack.get('paused') and ack.get('frame', -1) >= (c.get('issued_frame') or 0)
                    transition = c.get('issued') and c['offer'].get('effect') in {'room_change', 'teleport'}
                    if transition and not explicit_pause:
                        pause = c.setdefault('transition_pause', {'deadline': self.clock()+.75})
                        if self.clock() > pause['deadline']: self._cancel('native_pause_exceeded_transition_grace')
                    else: self._cancel('native_paused')
            elif self.command and self.command.get('transition_pause'):
                # A quick operator pause/unpause in the same room must not
                # silently replay the old authorization.
                self._cancel('pause_ended_without_expected_room_transition')
            self._observe_command()
            if self.pending and self.clock() > self.pending['deadline']:
                self.resolved.add(self.pending['fingerprint'])
                self.emit('decision_expired', decision_id=self.pending['id'], reason='deadline')
                self.pending = None
            if self.command and self.clock() > self.command['deadline']:
                self._finish('indeterminate' if self.command.get('issued') else 'expired', 'effect_timeout_no_retry')
            if self.enabled and not self.pending and not self.command and not raw.get('player_dead') and not extra.get('manual_override') and not extra.get('paused'):
                offers = self._offers(state)
                self._current_offers = offers
                fingerprint = digest([identity, extra.get('inventory_revision'),
                    [(o['id'], o.get('guard')) for o in offers]])
                continuation = self.routes.continuation(offers)
                optional = any(o['op'] != 'wait' and not o.get('guard', {}).get('door') for o in offers)
                if offers and fingerprint not in self.resolved and not (continuation and not optional):
                    self.pending = {'id': uuid.uuid4().hex, 'fingerprint': fingerprint,
                                    'identity': identity, 'revision': self.snapshot['revision'],
                                    'created': self.clock(), 'deadline': self.clock() + self.decision_seconds,
                                    'offers': offers, 'mode': 'live' if self.live else 'observe'}
                    self.emit('decision_ready', decision_id=self.pending['id'], domains=sorted({o['domain'] for o in offers}))
            self.state_latency.append((self.clock() - start) * 1000)

    def fresh(self):
        return bool(self.snapshot) and self.clock() - self.received < 1.5

    def native_engine_hold_grace(self):
        """Wait at most ten seconds after an observed engine input hold.

        Query freshness, stale speech cancellation and all input/target leases
        remain unchanged. A missing packet in ordinary gameplay has no grace.
        """
        with self.lock:
            return (self.enabled and self.live and self.engine_hold_since is not None
                    and 0 <= self.clock() - self.engine_hold_since < 10)

    def query(self, topic='state'):
        with self.lock:
            result = deepcopy(self.snapshot)
            if topic not in {'state', 'health', 'inventory', 'effects', 'history', 'actives', 'pockets', 'map', 'room', 'enemies', 'bosses', 'pickups', 'resources'}:
                raise StrategyError('unknown query topic')
            envelope = {'connected': self.fresh(), 'age_ms': round((self.clock() - self.received)*1000, 1) if self.received else None,
                        'identity': result.get('identity'), 'revision': result.get('revision'), 'frame': result.get('frame')}
            if topic == 'state': envelope['data'] = result
            else: envelope['data'] = result.get(topic)
            return envelope

    def lookup(self, kind, identity):
        if kind == 'collectible':
            item = deepcopy(self.catalog.get(int(identity), {'id': int(identity), 'known': False}))
            item.update(game_version='Repentance 1.7.9b',sources=['live ItemConfig for names/descriptions/quality', 'native130 capability registry for curated mechanics'])
            if int(identity) in self.catalog: item['known'] = True
            if int(identity) in ACTIVE:
                name, domain, effect = ACTIVE[int(identity)]
                item.update(name=name, domain=domain, mechanics=effect,
                            executable=int(identity) not in UNSUPPORTED_ACTIVE)
            item['hard_rejected'] = int(identity) in HARD_ITEMS
            return item
        if kind == 'card':
            info = CARD_RULES.get(int(identity))
            return {'id': int(identity), 'known': bool(info), 'name': info[0] if info else None,
                    'effect': info[1] if info else None, 'executable': bool(info and info[1] != 'dangerous')}
        if kind == 'domain':
            return {'id': str(identity), 'description': DOMAINS.get(str(identity)), 'rules': DOMAIN_GUIDANCE.get(str(identity))}
        raise StrategyError('lookup kind must be collectible/card/domain')

    def _health_spend(self, price=0, damage=0):
        s = self.snapshot; h = s['health']
        if not h.get('exact') or h.get('character_type') != 0 or h.get('bone_hearts', 0) or h.get('rotten_hearts', 0):
            return False
        red, maximum, soul = int(h.get('red_hearts', 0)), int(h.get('max_hearts', 0)), int(h.get('soul_hearts', 0))
        if price < 0:
            if price not in {-1, -2, -3, -4}: return False
            red_cost, soul_cost = {-1: (2, 0), -2: (4, 0), -3: (0, 6), -4: (2, 4)}[price]
            if maximum < red_cost or soul < soul_cost: return False
            red = min(red, maximum-red_cost); soul -= soul_cost
        return red+soul-damage >= 4

    def _offers(self, state):
        s = self.snapshot
        if not s or not s['inventory_known']: return []
        result = []
        safe = s['room']['clear'] and not s['enemies'] and not s['projectiles'] and not self._threats()

        def add(op, domain, label, guard=None, **data):
            value = {'op': op, 'domain': domain, 'label': label, 'guard': guard or {}, **data}
            price = value['guard'].get('price', 0)
            health_cost = {-1: 2, -2: 4, -3: 6, -4: 6}.get(price, 0) if price < 0 else 0
            value['cost'] = {'coins': max(0, price), 'keys': int(bool(value['guard'].get('door', {}).get('door_locked'))) + value['guard'].get('pickup_keys',0),
                             'bombs': int(domain == 'bomb_entry'), 'health_half_hearts': health_cost}
            if op == 'sacrifice_once': value['cost']['health_half_hearts'] = 2
            if op == 'use_active' and value['guard'].get('id') == 295: value['cost']['coins'] = 1
            if op == 'use_active' and value['guard'].get('id') == 133: value['cost']['health_half_hearts'] = 2
            if any(value['cost'].values()): value['label'] += '；费用 '+json.dumps(value['cost'],ensure_ascii=False,separators=(',',':'))
            value['id'] = digest([s['identity'], op, domain, value.get('target_id'), value['guard'], data.get('action_id')])
            result.append(value)

        for a in s['actives']:
            item = int(a.get('id', 0)); rule = ACTIVE.get(item)
            if not rule or a.get('slot') != 0 or item in UNSUPPORTED_ACTIVE: continue
            if item in COMBAT_ONLY_ACTIVE and (s['room']['clear'] or not s['enemies']): continue
            if item == 45 and s['health'].get('red_hearts',0) >= s['health'].get('max_hearts',0): continue
            if rule[1] == 'active_special' and not safe: continue
            if not a.get('ready') or (item == 295 and s['resources']['coins'] < 1): continue
            if item == 33 and any(x.get('type') == 84 for x in s['enemies']): continue
            if item == 133 and not self._health_spend(price=-1): continue
            # Rerolls/absorptions need a visible target; do not waste them in empty combat.
            if item in {105, 347, 477} and not s['pickups']: continue
            if item == 166 and not s['pickups']: continue
            add('use_active', rule[1], rule[0], {'slot': 0, 'id': item, 'inventory_revision': s['inventory_revision'], 'combat_required': item in COMBAT_ONLY_ACTIVE},
                effect='teleport' if item == 419 else 'utility', safe_only=rule[1] == 'active_special')
        for p in s['pockets']:
            if p.get('slot') != 0: continue
            if p.get('kind') == 'pill':
                if not p.get('identified') or not p.get('effect_supported'): continue
                combat=p.get('effect_name')=='PILLEFFECT_BAD_GAS'
                if combat and (s['room']['clear'] or not s['enemies']) or not combat and not safe:continue
                add('use_pocket', 'pill', p.get('name', p.get('effect_name','identified pill')),
                    {'slot': 0, 'kind': 'pill', 'id': p.get('id'), 'effect': p.get('effect'),'combat_required':combat},
                    effect='utility', safe_only=not combat)
            elif p.get('kind') == 'card' and p.get('id') in CARD_RULES:
                rule = CARD_RULES[p['id']]
                if rule[1] == 'dangerous': continue
                combat=rule[1]=='combat'
                if combat and (s['room']['clear'] or not s['enemies']) or not combat and not safe:continue
                add('use_pocket', 'card', rule[0], {'slot': 0, 'kind': 'card', 'id': p['id'],'combat_required':combat},
                    effect='teleport' if rule[1] == 'teleport' else 'utility', safe_only=not combat)
        if not safe or state is None:
            if result: add('wait', 'route', '保留道具，继续本地战斗', effect='none')
            return result
        candidate_set = build_candidate_set(state)
        for a in candidate_set.admissible_candidates:
            if a.mode in {'combat', 'evade', 'recovery', 'wait'}: continue
            if a.action_id.startswith('wait_'): continue
            domain = 'route'
            if a.mode in {'item', 'shop', 'pickup', 'chest'}: domain = 'pickup'
            if a.mode in {'bomb_wall', 'bomb'}: domain = 'bomb_entry'
            if a.mode in {'hazard', 'button', 'tnt'}: domain = 'terrain'
            if a.mode == 'navigate' and any(g.get('timed') for g in s['room']['terrain']): domain = 'terrain'
            door = next((d for d in s['doors'] if a.action_id == 'enter_door_'+str(d.get('slot'))), None)
            if door and door.get('target_room_type') in {'devil', 'angel'}: domain = 'deal'
            if door and door.get('target_room_type') == 'planetarium': domain = 'planetarium'
            target = next((p for p in s['pickups'] if a.action_id in {f"take_item_{p['id']}", f"take_pickup_{p['id']}", f"open_chest_{p['id']}"}), None)
            pickup_state=next((p for p in state.pickups if target and p.entity_id==target['id']),None)
            if a.mode=='chest' and (not target or not pickup_state or pickup_state.pickup_kind in {'bomb_chest','spiked_chest','mimic_chest'}):continue
            if target and (target.get('subtype') in HARD_ITEMS and target.get('variant') == 100): continue
            if target and target.get('price', 0) < 0 and not self._health_spend(target['price']): continue
            guard=({'target_id':target['target_id'],'price':target.get('price',0),
                    'pickup_keys':int(bool(pickup_state and pickup_state.pickup_kind in {'locked_chest','eternal_chest'}))} if target else
                   {'door':deepcopy(door)} if door else {})
            if domain=='bomb_entry':
                wall=next((w for w in self.raw.get('layout',{}).get('bomb_walls',[])
                    if a.action_id==f"bomb_secret_{w.get('slot')}"),None)
                if wall:guard['bomb_wall']=deepcopy(wall)
                elif a.action_id.startswith('bomb_hazard_'):
                    guard['bomb_hazard_id']=int(a.action_id.removeprefix('bomb_hazard_'))
                else:continue
            add('select_action', domain, a.reason or a.action_id,
                guard, action_id=a.action_id,
                target_id=target['target_id'] if target else None,
                effect='room_change' if a.mode in {'navigate', 'boss_exit'} else 'pickup' if target else 'macro', safe_only=True)
        # Expose safe alternatives suppressed by a preference rule in the local policy.
        existing = {o.get('action_id') for o in result}
        for p in s['pickups']:
            if not p.get('locally_eligible', True): continue
            if p.get('variant') != 100: continue
            if p.get('subtype') in HARD_ITEMS or p.get('subtype') == 316 and not any(x['id']==260 for x in s['inventory']): continue
            price = p.get('price', 0)
            if price > s['resources']['coins'] or price < 0 and not self._health_spend(price): continue
            aid = f"take_item_{p['id']}"
            if aid in existing: continue
            pos = Vec2.from_value(p.get('pos', {}))
            if not math.isfinite(path_distance(state, pos, p.get('grid_index', -1))): continue
            add('select_pickup', 'deal' if price < 0 else 'pickup', p.get('name', aid),
                {'target_id': p['target_id'], 'price': price}, action_id=aid, target_id=p['target_id'], effect='pickup', safe_only=True)
        # Route alternatives are local-path-checked; locked doors consume one key.
        for d in state.layout.doors:
            aid = f'enter_door_{d.slot}'
            usable = door_is_usable(d, state) or (d.target_room_type == 'planetarium' and d.lock_known and d.locked and state.keys > 0)
            if aid in existing or not usable: continue
            if d.slot in state.unreachable_door_slots or not math.isfinite(door_path_distance(state, d)): continue
            raw_d = next((x for x in s['doors'] if x.get('slot') == d.slot), {})
            if d.target_room_type in {'curse', 'sacrifice'}: continue  # separate explicit health macro required
            add('select_route', 'deal' if d.target_room_type in {'angel', 'devil'} else 'planetarium' if d.target_room_type=='planetarium' else 'route',
                f'进入 {d.target_room_type} / {d.target_room_index}', {'door': raw_d}, action_id=aid, effect='room_change', safe_only=True)
        sac = s['room']['sacrifice']
        if s['room']['type'] == 'sacrifice' and sac.get('known') and self._health_spend(damage=2) and sac.get('spike_index') is not None:
            add('sacrifice_once', 'sacrifice', '仅支付一次献祭；完成后重新判断',
                {'count': sac['count'], 'health': deepcopy(s['health'])}, grid_index=sac['spike_index'], effect='sacrifice', safe_only=True)
        dice = s['room']['dice']
        if dice and dice.get('face') in range(1, 7) and dice.get('grid_index') is not None:
            add('trigger_dice', 'dice', f"触发 {dice['face']} 点骰子；不可撤销",
                {'dice': dice, 'inventory_revision': s['inventory_revision']}, grid_index=dice['grid_index'], effect='dice', safe_only=True)
        result = self.routes.annotate(result, state)
        if result: add('wait', 'route', '记住本轮跳过的拾取与可选消耗；仅继续有进展的免费路线和本地战斗', effect='none')
        return result

    def decision(self):
        with self.lock:
            self.agent_heartbeat = self.clock()
            if not self.pending: return {'pending': False, 'connected': self.fresh()}
            result = deepcopy(self.pending)
            result['remaining_ms'] = max(0, int((result.pop('deadline')-self.clock())*1000))
            result.pop('created', None)
            data = deepcopy(self.snapshot)
            context = {k: data[k] for k in ('health', 'inventory', 'inventory_known', 'inventory_revision',
                       'effects', 'actives', 'pockets', 'trinkets', 'resources', 'room', 'doors', 'map', 'pickups', 'enemies', 'bosses')}
            context['recent_room_observations'] = deepcopy(self.history['room_observations'][-10:])
            context['recent_results'] = deepcopy(list(self.receipts.values())[-5:])
            context['route_progress'] = self.routes.describe()
            rules = {domain: DOMAIN_GUIDANCE[domain] for domain in {o['domain'] for o in result['offers']}}
            for o in result['offers']:
                item = o.get('guard', {}).get('id')
                if o['op'] == 'use_active' and item in ACTIVE: o['mechanics'] = ACTIVE[item][2]
                if o['op'] == 'use_pocket' and item in CARD_RULES: o['mechanics'] = CARD_RULES[item][1]
            return {'pending': True, **result, 'context_id': digest(result['identity']),
                    'connected': self.fresh(), 'context': context, 'domain_rules': rules}

    def submit(self, body):
        with self.lock:
            if not isinstance(body, dict): raise StrategyError('plan must be an object')
            key = body.get('plan_id')
            if not isinstance(key, str) or not 1 <= len(key) <= 96: raise StrategyError('plan_id required (1..96 characters)')
            if key in self.receipts: return deepcopy(self.receipts[key])
            if len(self.receipts) >= 4096: raise StrategyError('receipt capacity reached; start a new protected session')
            if not self.enabled or not self.pending: raise StrategyError('no pending authorized decision')
            if not self.fresh(): raise StrategyError('state disconnected or stale')
            pending = self.pending
            identity_matches = body.get('context_id') == digest(pending['identity']) or body.get('identity') == pending['identity']
            if body.get('decision_id') != pending['id'] or not identity_matches:
                raise StrategyError('stale decision/context')
            if self.clock() >= pending['deadline']: raise StrategyError('decision deadline exceeded')
            offer = next((o for o in pending['offers'] if o['id'] == body.get('offer_id')), None)
            if not offer: raise StrategyError('offer is not in the locally constructed decision set')
            budget = body.get('budget')
            if not isinstance(budget, dict) or any(type(budget.get(k)) is not int or budget[k] < v for k, v in offer['cost'].items()):
                raise StrategyError('explicit resource budget must cover the displayed cost')
            self._validate(offer)
            receipt = {'plan_id': key, 'decision_id': pending['id'], 'offer_id': offer['id'],
                       'status': 'accepted' if self.live else 'observed', 'reason': str(body.get('reason', ''))[:1000],
                       'submitted_frame': self.raw.get('frame'), 'live': self.live}
            receipt['cost'] = deepcopy(offer['cost'])
            receipt['origin_room'] = self.snapshot['identity']['room']
            receipt['action_id'] = offer.get('action_id')
            receipt['route'] = deepcopy(offer.get('route'))
            self.receipts[key] = receipt
            self.resolved.add(pending['fingerprint'])
            self.pending = None
            if self.live and offer['op'] != 'wait':
                self.routes.choose(offer)
                self.command = {'plan_id': key, 'identity': deepcopy(self.snapshot['identity']), 'offer': deepcopy(offer),
                                'before': deepcopy(self.snapshot), 'deadline': self.clock()+min(20, max(1, float(body.get('execution_seconds', 12)))),
                                'issued': False, 'issued_frame': None}
            elif self.live:
                self.routes.defer(pending['offers'])
                receipt['status'] = 'succeeded'; receipt['effect'] = 'wait'
            self.emit('plan_received', receipt=deepcopy(receipt), offer=deepcopy(offer))
            return deepcopy(receipt)

    def _validate(self, o):
        s = self.snapshot; g = o.get('guard', {})
        if s['room']['dead']: raise StrategyError('player dead')
        if s['room']['paused']: raise StrategyError('game paused')
        if o.get('safe_only') and (not s['room']['clear'] or s['enemies'] or s['projectiles'] or self._threats()):
            raise StrategyError('local danger preempts strategic execution')
        if g.get('inventory_revision') and g['inventory_revision'] != s['inventory_revision']:
            raise StrategyError('inventory changed')
        if g.get('target_id'):
            target = next((p for p in s['pickups'] if p['target_id'] == g['target_id']), None)
            if target is None: raise StrategyError('target gone or entity identity changed')
            if target.get('price', 0) != g['price']: raise StrategyError('target price changed')
            if g['price'] > s['resources']['coins']: raise StrategyError('insufficient coins')
            if g.get('pickup_keys',0)>s['resources']['keys']:raise StrategyError('insufficient chest keys')
            if g['price'] < 0 and not self._health_spend(g['price']): raise StrategyError('unsafe health payment')
        if g.get('door'):
            d = g['door']; current = next((x for x in s['doors'] if x.get('slot') == d.get('slot')), None)
            if current != d: raise StrategyError('door changed')
            if d.get('door_locked') and s['resources']['keys'] < 1: raise StrategyError('no key')
        if o['op'] == 'use_active':
            a = next((x for x in s['actives'] if x.get('slot') == g.get('slot') and x.get('id') == g.get('id')), None)
            if not a or not a.get('ready'): raise StrategyError('active not ready or replaced')
            if g.get('combat_required') and (s['room']['clear'] or not s['enemies']): raise StrategyError('combat effect expired before execution')
            if a['id'] == 33 and any(x.get('type') == 84 for x in s['enemies']): raise StrategyError('Bible is lethal against Satan')
            if a['id'] == 295 and s['resources']['coins'] < 1: raise StrategyError('no coin for Magic Fingers')
            if a['id'] == 133 and not self._health_spend(price=-1): raise StrategyError('unsafe red-heart container payment')
        if o['op'] == 'use_pocket':
            if g.get('combat_required') and (s['room']['clear'] or not s['enemies']):raise StrategyError('combat pocket effect expired before execution')
            if not any(x.get('slot') == g['slot'] and x.get('kind') == g['kind'] and x.get('id') == g['id'] for x in s['pockets']):
                raise StrategyError('pocket changed')
        if o['op'] == 'sacrifice_once':
            sac = s['room']['sacrifice']
            if not sac.get('known') or sac.get('count') != g['count'] or not self._health_spend(damage=2):
                raise StrategyError('sacrifice count/health unknown or changed')
        if o['op'] == 'trigger_dice' and s['room']['dice'] != g['dice']: raise StrategyError('dice changed')

    def _finish(self, status, reason):
        if not self.command: return
        receipt = self.receipts[self.command['plan_id']]
        receipt.update(status=status, effect=reason, completed_frame=self.raw.get('frame'))
        offer=self.command['offer']
        if status != 'succeeded' and offer.get('guard', {}).get('door'):
            self.routes.suspend(reason)
        if status in {'rejected', 'expired', 'indeterminate'} and reason in {
                'no_current_safe_path_or_candidate', 'effect_timeout_no_retry', 'native_guard'}:
            self.routes.remember(offer, 'failure', reason, self.command['before'])
        if status=='succeeded' and offer.get('effect')=='pickup' and offer.get('guard',{}).get('price'):
            self.history['transactions'].append({'plan_id':receipt['plan_id'],'frame':self.raw.get('frame'),
                'identity':deepcopy(self.snapshot['identity']),'price':offer['guard']['price'],
                'before_resources':self.command['before']['resources'],'after_resources':deepcopy(self.snapshot['resources']),
                'before_health':self.command['before']['health'],'after_health':deepcopy(self.snapshot['health'])})
            self.history['transactions']=self.history['transactions'][-128:]
        self.emit('plan_effect', receipt=deepcopy(receipt))
        self.command = None

    def _observe_command(self):
        c = self.command
        if not c or not c.get('issued'): return
        s, b, o = self.snapshot, c['before'], c['offer']
        ack = (self.raw.get('strategy') or {}).get('command_ack') or {}
        if ack.get('plan_id') == c['plan_id'] and ack.get('status') == 'rejected':
            self.routes.remember(o, 'failure', ack.get('reason', 'native_guard'), c['before'])
            self._finish('rejected', ack.get('reason', 'native_guard')); return
        if o['op'] == 'use_active':
            g = o['guard']; a = next((x for x in s['actives'] if x.get('slot') == g['slot']), {})
            before = next((x for x in b['actives'] if x.get('slot') == g['slot']), {})
            if (a.get('id') != g['id'] or a.get('charge', 0) < before.get('charge', 0)
                    or s['resources']['coins'] < b['resources']['coins']
                    or g['id'] == 133 and s['health'].get('max_hearts', 0) < b['health'].get('max_hearts', 0)):
                self._finish('succeeded', 'native_active_consumption_observed')
        elif o['op'] == 'use_pocket' and s['pockets'] != b['pockets']:
            self._finish('succeeded', 'native_pocket_consumption_observed')
        elif o.get('effect') == 'pickup' and not any(p['target_id'] == o['target_id'] for p in s['pickups']):
            target = next((p for p in b['pickups'] if p['target_id'] == o['target_id']), {})
            if target.get('variant') == 100:
                count = lambda snapshot: sum(p.get('count', 0) for p in snapshot['inventory'] if p.get('id') == target.get('subtype'))
                confirmed = s['inventory_known'] and count(s) > count(b)
            else:
                confirmed = s['resources'] != b['resources'] or s['health'] != b['health'] or s['pockets'] != b['pockets'] or s['trinkets'] != b['trinkets']
            if confirmed:
                self._finish('succeeded', 'pickup_disappeared_and_inventory_or_resource_changed')
            else:
                # Native inventory refresh is every 15 game frames. Do not
                # confuse the first empty-pedestal packet with a failed effect.
                # While awaiting evidence, never chase or pick another target.
                missing_at = c.setdefault('pickup_missing_since', self.clock())
                if self.clock()-missing_at >= 1:
                    self._finish('indeterminate', 'pickup_disappeared_without_inventory_confirmation')
        elif o['op'] == 'sacrifice_once' and s['room']['sacrifice'].get('count', -1) == o['guard']['count'] + 1:
            self._finish('succeeded', 'one_native_sacrifice_payment_observed')
        elif o['op'] == 'trigger_dice' and (s['inventory_revision'] != b['inventory_revision'] or s['room']['dice'] != b['room']['dice']):
            self._finish('succeeded', 'native_dice_effect_observed')
        elif o['domain'] == 'bomb_entry':
            if s['resources']['bombs'] < b['resources']['bombs'] and not c.get('spent'):
                c['spent']=True
                self.receipts[c['plan_id']]['stage']='bomb_spent_waiting_for_target_effect'
                self.emit('plan_progress',plan_id=c['plan_id'],stage='bomb_spent_waiting_for_target_effect')
            if c.get('spent'):
                wall=o.get('guard',{}).get('bomb_wall')
                if wall and any(d.get('slot')==wall['slot'] and d.get('door_open') is True
                        and d.get('target_room_type')==wall['room_type'] for d in s['doors']):
                    self._finish('succeeded','native_bomb_opening_observed')
                elif 'bomb_hazard_id' in o.get('guard',{}):
                    target=o['guard']['bomb_hazard_id']
                    if not any(h.get('id')==target for h in self.raw.get('hazards',[])):
                        self._finish('succeeded','native_bomb_target_removal_observed')

    def decorate_response(self, response, state):
        with self.lock:
            response = deepcopy(response)
            owned = self.enabled and self.live and self.fresh()
            # Lua rechecks this lease per input/frame even if Python disconnects.
            response['strategy'] = {'owned': owned, 'lease_ms': 1500, 'hold': False,
                                    'identity': self.snapshot.get('identity'), 'command': None}
            if not owned or not response.get('enabled'): return response
            if self.snapshot['room']['paused']: return self._hold(response)
            c = self.command
            danger = not self.snapshot['room']['clear'] or bool(self.snapshot['enemies'] or self.snapshot['projectiles'] or self._threats())
            if c:
                if 'pickup_missing_since' in c:
                    if danger:self._finish('cancelled','danger_while_waiting_for_pickup_effect');return response
                    return self._hold(response)
                if c.get('spent') and c['offer']['domain']=='bomb_entry':
                    # Existing Lua bomb avoidance still preempts this hold.
                    # No second placement while waiting for the opening.
                    if danger:self._finish('cancelled','danger_after_bomb_spend');return response
                    return self._hold(response)
                try: self._validate(c['offer'])
                except StrategyError as exc:
                    if danger:
                        # Combat keeps full local control; dangerous macros are cancelled, not resumed later.
                        self._finish('cancelled', str(exc)); return response
                    if not c.get('issued'): self._finish('rejected', str(exc))
                    else: self._finish('indeterminate', str(exc))
                    return response
                o = c['offer']
                if o['op'] in {'use_active', 'use_pocket'}:
                    if not c['issued']:
                        response['strategy']['command'] = {'plan_id': c['plan_id'], 'op': o['op'], **o['guard']}
                        c['issued'] = True; c['issued_frame'] = self.raw.get('frame')
                        self.receipts[c['plan_id']]['status'] = 'issued'
                    if not danger: response = self._hold(response)
                else:
                    action = self._resolve_action(o, state)
                    if action is None:
                        self._finish('rejected', 'no_current_safe_path_or_candidate'); return self._hold(response)
                    response.update(action.as_message(True))
                    response['source_room_index'] = state.layout.room_index
                    selected_door = next((d for d in state.layout.doors if action.mode == 'navigate' and action.action_id == f'enter_door_{d.slot}'), None)
                    response['door_slot'] = selected_door.slot if selected_door else -1
                    response['target_room_index'] = selected_door.target_room_index if selected_door else -1
                    response['strategy']['command'] = {'plan_id': c['plan_id'], 'op': o['op'],
                        'grid_index': o.get('grid_index'), 'guard': o.get('guard')}
                    if o.get('target_id'):
                        target = next((p for p in self.snapshot['pickups'] if p['target_id']==o['target_id']), None)
                        if target:
                            response['strategy']['command']['target'] = {k: target.get(k) for k in
                                ('id', 'spawn_seed', 'type', 'variant', 'subtype', 'price')}
                    if not c['issued']:
                        c['issued'] = True; c['issued_frame'] = self.raw.get('frame')
                        self.receipts[c['plan_id']]['status'] = 'issued'
            elif not danger:
                # Deferring never authorizes the baseline policy to consume
                # that same item/key/bomb on the next frame.
                free_route = False
                if not self.pending:
                    # A free baseline suggestion cannot bypass the same route
                    # goal, cross-room refusals, failures and cycle constraints.
                    choices = self.routes.annotate(self._offers_without_wait(self._current_offers), state)
                    choices = [o for o in choices if self._free_route_offer(o, state)]
                    intent = self.routes.continuation(choices)
                    if intent is None:
                        intent = next((o for o in choices if o.get('guard', {}).get('door')
                            and not o['guard']['door'].get('door_locked')
                            and o['guard']['door'].get('target_room_type') in {'default', 'boss'}), None)
                    if intent:
                        action = self._resolve_action(intent, state)
                        if action:
                            door = next(d for d in state.layout.doors if action.action_id == f'enter_door_{d.slot}')
                            response.update(replace(action, source='local-strategy-fallback').as_message(True))
                            response.update(door_slot=door.slot, source_room_index=state.layout.room_index,
                                            target_room_index=door.target_room_index)
                            free_route = True
                    elif response.get('mode') == 'boss_exit':
                        free_route = True
                if not free_route: response = self._hold(response)
            return response

    @staticmethod
    def _offers_without_wait(offers):
        return [o for o in offers if o['op'] != 'wait']

    @staticmethod
    def _free_route_offer(offer, state):
        door = next((d for d in state.layout.doors
                     if offer.get('action_id') == f'enter_door_{d.slot}'), None)
        return bool(door and not door.locked and door.target_room_type in {'default', 'boss'}
                    and door.slot not in state.unreachable_door_slots and door_is_usable(door, state)
                    and math.isfinite(door_path_distance(state, door))
                    and not any(offer.get('cost', {}).values()))

    def _hold(self, response):
        response.update(id='strategy_safe_hold', mode='strategy_hold', move={'x': 0, 'y': 0}, shoot={'x': 0, 'y': 0},
                        bomb_site=None, waypoint=None, target='', door_slot=-1, target_room_index=-1, source='dsh', reason='waiting for bounded strategic judgment')
        response['strategy']['hold'] = True
        return response

    def _resolve_action(self, o, state):
        aid = o.get('action_id')
        current = next((a for a in build_candidate_set(state).admissible_candidates if a.action_id == aid), None)
        target, mode = None, ''
        grid = -1
        if o.get('guard', {}).get('door'):
            door = next((d for d in state.layout.doors if aid == f'enter_door_{d.slot}'), None)
            usable = door and (door_is_usable(door, state) or (door.target_room_type == 'planetarium' and door.lock_known and door.locked and state.keys > 0))
            if not usable or door.slot in state.unreachable_door_slots: return None
            if not math.isfinite(door_path_distance(state, door)): return None
            target, mode, grid = door.position, 'navigate', door.grid_index
        elif o.get('target_id'):
            p = next((p for p in self.snapshot['pickups'] if p['target_id'] == o['target_id']), None)
            if not p or not p.get('locally_eligible', True): return None
            if p: target, mode, grid = Vec2.from_value(p['pos']), 'item', p.get('grid_index', -1)
        elif o['op'] in {'sacrifice_once', 'trigger_dice'}:
            index = o['grid_index']; layout = self.raw.get('layout', {})
            origin = layout.get('top_left', {'x': 0, 'y': 0}); width = layout.get('width', 13)
            # Native telemetry supplies the engine's actual grid position, never infer room bounds here.
            entry = next((g for g in self.snapshot['room']['terrain'] if g.get('grid_index', g.get('index')) == index), None)
            position = (self.snapshot['room']['sacrifice'] if o['op']=='sacrifice_once' else self.snapshot['room']['dice']).get('pos')
            if position: target, mode, grid = Vec2.from_value(position), 'strategy_macro', index
        elif current:
            return replace(current, source='dsh', issued_frame=state.frame, expires_frame=state.frame+8)
        if target is None: return None
        if o['op'] == 'sacrifice_once':
            state = replace(state, layout=replace(state.layout, danger_grid_indices=state.layout.danger_grid_indices-{grid}))
        if mode != 'navigate' and not math.isfinite(path_distance(state, target, grid, allow_timed=o['domain']=='terrain')): return None
        move = move_towards(state, target, grid)
        return Action(aid or 'strategy_'+o['op'], move, Vec2(), source='dsh', mode=mode,
                      target=str(o.get('target_id', '')), reason=o['label'], issued_frame=state.frame, expires_frame=state.frame+8, waypoint=target)

    def _threats(self):
        return [x for x in self.snapshot.get('danger_effects', []) if x.get('kind') not in
                {'empty_pedestal', 'unsupported_pedestal', 'unselected_health_deal', 'retracted_spike'}]

    def status(self):
        with self.lock:
            samples = sorted(self.state_latency)
            return {'enabled': self.enabled, 'live': self.live, 'reason': self.reason, 'connected': self.fresh(),
                    'state_age_ms': round((self.clock()-self.received)*1000, 1) if self.received else None,
                    'identity': deepcopy(self.snapshot.get('identity')), 'frame': self.raw.get('frame'),
                    'pending': self.pending['id'] if self.pending else None,
                    'executing': self.command['plan_id'] if self.command else None,
                    'recent_receipts': deepcopy(list(self.receipts.values())[-15:]), 'last_event_seq': self.counter,
                    'state_copy_p95_ms': samples[min(len(samples)-1, int(len(samples)*.95))] if samples else None,
                    'domains': DOMAINS}

    def read_events(self, after=0):
        with self.lock:
            return {'events': deepcopy([x for x in self.events if x['seq'] > after]), 'cursor': self.counter,
                    'gap': bool(self.events and after and after < self.events[0]['seq']-1)}


DOMAIN_GUIDANCE = {
    'active': '按房间收益、充能补给和生存风险判断。保持本地战斗；不能等待 agent 躲弹。',
    'active_special': '重骰/吸收/传送/一次性动作不可撤销；比较当前房间完整目标与全局构筑，未知机制不执行。',
    'pickup': '结合完整道具、攻击方式、选择组、价格和现有主动比较；硬拒绝表示本地无法安全控制。',
    'pill': '未知药丸保持未知。已识别的 Speed/Tears/Range/Luck Up 在使用后立即提供本局持续属性收益，不是保留到下房才生效；通常立即使用，接近属性上限或操控风险等需说明理由。治疗按当前缺血判断；Bad Gas 仅当前有敌人时可用。',
    'card': '比较当前房间、楼层后续与占槽成本；仅槽 0 能直接原生输入，其余槽只读。',
    'route': '只使用可见/访问过的地图和当前门；保留补给与钥匙，不用隐藏未发现房间信息。',
    'deal': '天使/恶魔房分别判断；交易前重算半心单位生命、红心容器和魂心费用；未知特殊血量拒绝支付。',
    'bomb_entry': '炸门/开墙是预算宏；站位、爆炸撤离、动态敌弹均由本地逐帧否决。',
    'planetarium': '明确跳过宝箱房的机会成本；不能保证出现星象房；只按已知地图判断。',
    'dice': '1/6 点可能重骰角色构筑，2/3 点重骰资源，4 点重骰基座，5 点重启楼层；执行前核对点数和库存版本。',
    'sacrifice': '计数必须从本运行中的实际付款事件观察；一次只付一次，保留至少两整颗心，未知计数不猜测。',
    'terrain': 'agent 只选路线/目标；持续地刺的逐帧相位等待和穿越必须由本地执行器控制。',
}
