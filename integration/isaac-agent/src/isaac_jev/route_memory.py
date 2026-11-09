"""Observed-floor route continuity for the sole strategic actor.

This is graph bookkeeping, not a pickup/resource policy. A selected multi-room
goal permits only free ordinary doors; every paid/special step needs a new
current-room DSH offer and its existing native guard. Visit IDs remain fences.
"""
from collections import deque
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:20]


class RouteMemory:
    FREE = {'default', 'boss'}
    FLOOR_FIELDS = ('seed', 'restart', 'stage', 'stage_type', 'dimension')

    def __init__(self, path, emit):
        self.path, self.emit = Path(path), emit
        self.data = self.empty()
        try:
            value = json.loads(self.path.read_text(encoding='utf8'))
            if (value.get('schema') == 1 and isinstance(value.get('rooms'), dict)
                    and len(value['rooms']) <= 512 and len(value.get('constraints', {})) <= 512
                    and isinstance(value.get('edges'), dict) and isinstance(value.get('transitions'), list)):
                self.data = value
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.snapshot = {}

    @staticmethod
    def empty():
        return {'schema': 1, 'floor': None, 'rooms': {}, 'native_visited': [],
                'constraints': {}, 'edges': {}, 'transitions': [], 'goal': None,
                'progress': 0, 'last_room': None, 'last_resources': None,
                'last_inventory': None, 'last_health': None}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
        temporary.replace(self.path)

    @staticmethod
    def edge_key(source, target):
        return f'{source}>{target}'

    def observe(self, snapshot, raw):
        identity = snapshot['identity']
        floor = {k: identity.get(k) for k in self.FLOOR_FIELDS}
        if self.data['floor'] != floor:
            self.data = self.empty()
            self.data['floor'] = floor
        self.snapshot = snapshot
        room = identity.get('room')
        if not isinstance(room, int) or room < 0:
            return
        data = self.data
        old_room = data['rooms'].get(str(room))
        # Only supplied visible/visited map records are used; never infer edges
        # from grid adjacency or reveal undiscovered room contents.
        visited = set(data['native_visited'])
        visited.update(m['index'] for m in snapshot['map']
                       if isinstance(m.get('index'), int) and int(m.get('visited') or 0) > 0)
        visited.add(room)
        data['native_visited'] = sorted(visited)
        doors = [{k: d.get(k) for k in ('slot', 'target_room_index', 'target_room_type',
                  'target_clear', 'door_locked', 'door_lock_known', 'door_open', 'door_open_known')}
                 for d in snapshot['doors'] if isinstance(d.get('target_room_index'), int)
                 and d['target_room_index'] >= 0]
        # No moving positions, frame/visit numbers, or animation phases in the
        # progress token. Merely walking back through a room is not progress.
        geometry = signature({'blocked': sorted(raw.get('layout', {}).get('blocked', [])),
                              'hazards': sorted((h.get('id'), h.get('kind'), h.get('grid_index'))
                                                for h in raw.get('hazards', [])),
                              'doors': doors})
        content = signature({'geometry': geometry, 'clear': snapshot['room']['clear'],
                             'pickups': sorted(self.pickup_key(p) for p in snapshot['pickups'])})
        resources = snapshot['resources']
        previous_resources = data['last_resources'] or resources
        gained = any(resources.get(k, 0) > previous_resources.get(k, 0) for k in ('coins', 'keys', 'bombs'))
        inventory_changed = data['last_inventory'] is not None and data['last_inventory'] != snapshot['inventory_revision']
        health = sum(int(snapshot['health'].get(k) or 0) for k in ('red_hearts', 'soul_hearts'))
        healed = data['last_health'] is not None and health > data['last_health']
        progress = old_room is None or old_room['content'] != content or gained or inventory_changed or healed
        if progress:
            data['progress'] += 1
            data['edges'] = {}
        data['rooms'][str(room)] = {'index': room, 'type': snapshot['room']['type'],
                                    'clear': snapshot['room']['clear'], 'doors': doors,
                                    'geometry': geometry, 'content': content,
                                    'objectives': old_room.get('objectives', []) if old_room else []}
        last = data['last_room']
        changed_room = last is not None and last != room
        if changed_room:
            key = self.edge_key(last, room)
            data['edges'][key] = data['edges'].get(key, 0) + 1
            data['transitions'].append({'from': last, 'to': room, 'frame': snapshot['frame'],
                                        'progress': data['progress'], 'new_information': progress})
            data['transitions'] = data['transitions'][-32:]
            self.emit('route_transition', **data['transitions'][-1], goal=deepcopy(data['goal']))
        goal = data['goal']
        if goal and goal['room'] == room:
            self.emit('route_goal_reached', goal=deepcopy(goal), frame=snapshot['frame'])
            data['goal'] = None
        data['last_room'], data['last_resources'] = room, deepcopy(resources)
        data['last_inventory'], data['last_health'] = snapshot['inventory_revision'], health
        if progress or changed_room or self.path.exists() is False:
            self.save()

    @staticmethod
    def pickup_key(p):
        # Spawn seed + physical room identify the same pickup across visits;
        # action target_id remains visit-scoped for native authorization.
        return signature([p.get('spawn_seed', p.get('id')), p.get('type'), p.get('variant'),
                          p.get('subtype'), p.get('grid_index'), p.get('price', 0)])

    def key(self, offer, snapshot=None):
        s = snapshot or self.snapshot
        guard = offer.get('guard', {})
        door = guard.get('door')
        if door:
            physical = ['door', door.get('slot'), door.get('target_room_index')]
        elif offer.get('target_id'):
            p = next((p for p in s['pickups'] if p['target_id'] == offer['target_id']), None)
            physical = ['pickup', self.pickup_key(p)] if p else ['missing', offer['target_id']]
        else:
            physical = [offer['op'], offer.get('action_id'), guard]
        return signature([s['identity']['room'], physical])

    def condition(self, offer, snapshot=None):
        s = snapshot or self.snapshot
        g = offer.get('guard', {})
        if g.get('door'):
            d = g['door']
            return {'keys': s['resources']['keys'] if d.get('door_locked') else None,
                    'locked': d.get('door_locked'), 'open': d.get('door_open')}
        return {'resources': s['resources'], 'health': {k: s['health'].get(k) for k in
                    ('red_hearts', 'max_hearts', 'soul_hearts')},
                'inventory': s['inventory_revision'], 'actives': s['actives'], 'pockets': s['pockets']}

    def blocked(self, offer, snapshot=None):
        s = snapshot or self.snapshot
        record = self.data['constraints'].get(self.key(offer, s))
        if not record:
            return False
        room = self.data['rooms'].get(str(s['identity']['room']), {})
        if record['kind'] == 'failure':
            # Spending a bomb elsewhere must not reset a failed bomb target.
            return (record['geometry'] == room.get('geometry')
                    and record['inventory'] == s['inventory_revision']
                    and not any(s['resources'].get(k, 0) > record['resources'].get(k, 0)
                                for k in ('coins', 'keys', 'bombs')))
        return record['condition'] == self.condition(offer, s)

    def remember(self, offer, kind, reason, snapshot=None):
        s = snapshot or self.snapshot
        if {k: s['identity'].get(k) for k in self.FLOOR_FIELDS} != self.data['floor']:
            return
        key = self.key(offer, s)
        door = offer.get('guard', {}).get('door')
        record = {'kind': kind, 'room': s['identity']['room'], 'target_room': door.get('target_room_index') if door else None,
                  'action_id': offer.get('action_id'), 'reason': str(reason)[:200],
                  'condition': deepcopy(self.condition(offer, s)), 'resources': deepcopy(s['resources']),
                  'inventory': s['inventory_revision'],
                  'geometry': self.data['rooms'].get(str(s['identity']['room']), {}).get('geometry')}
        self.data['constraints'][key] = record
        room_info = self.data['rooms'].get(str(record['room']))
        if room_info and key in room_info['objectives']:
            room_info['objectives'].remove(key)
        if len(self.data['constraints']) > 512:
            del self.data['constraints'][next(iter(self.data['constraints']))]
        self.emit('route_constraint', constraint=deepcopy(record))
        # A declined terminal paid step invalidates the whole approach, rather
        # than returning to it via another adjacent cleared room.
        if door and self.data['goal'] and self.data['goal']['room'] == door.get('target_room_index'):
            self.data['goal'] = None
        self.save()

    def defer(self, offers):
        for o in offers:
            if o['op'] == 'wait':
                continue
            d = o.get('guard', {}).get('door')
            if d and not d.get('door_locked') and d.get('target_room_type') in self.FREE:
                continue
            self.remember(o, 'deferred', 'DSH explicitly skipped this optional target')

    def edge_allowed(self, source, door):
        target = door.get('target_room_index')
        if self.data['edges'].get(self.edge_key(source, target), 0) >= 2:
            return False
        # An edge remembered as deferred remains blocked across room visits.
        fake = {'op': 'select_route', 'guard': {'door': door}}
        s = {**self.snapshot, 'identity': {**self.snapshot['identity'], 'room': source}}
        return not self.blocked(fake, s)

    def routes(self):
        data, s = self.data, self.snapshot
        origin = s['identity']['room']
        found = []
        queue = deque([(origin, [origin], [])])
        seen = {origin}
        # Traverse only observed free ordinary edges. A paid/special room can
        # be an endpoint, never an implicitly authorized intermediate step.
        while queue:
            current, path, route_doors = queue.popleft()
            info = data['rooms'].get(str(current), {})
            for d in info.get('doors', []):
                target = d['target_room_index']
                if target in path or not self.edge_allowed(current, d):
                    continue
                if d.get('door_lock_known') is not True:
                    continue
                locked = bool(d.get('door_locked'))
                if locked and s['resources']['keys'] <= 0:
                    continue
                kind = d.get('target_room_type')
                if kind in {'curse', 'sacrifice', 'devil', 'angel', 'secret', 'supersecret'}:
                    continue
                destination = data['rooms'].get(str(target))
                unseen = target not in data['native_visited']
                label = None
                if unseen:
                    label = 'unvisited_' + str(kind)
                elif destination is None:
                    label = 'survey_previously_visited_room'
                elif kind == 'boss' and not destination.get('clear'):
                    label = 'observed_uncleared_boss'
                elif destination.get('objectives'):
                    label = 'observed_optional_target'
                if label:
                    rank = (0 if kind == 'treasure' and unseen else 1 if kind == 'boss' else
                            2 if unseen and kind == 'default' else 3 if unseen else
                            4 if label == 'observed_optional_target' else 5)
                    found.append({'room': target, 'kind': label, 'room_type': kind,
                                  'path': path + [target], 'first_slot': (route_doors + [d])[0]['slot'],
                                  'terminal_key_cost': int(locked), 'rank': rank,
                                  'previously_visited': not unseen})
                if (destination and destination.get('clear') and not locked and kind in self.FREE
                        and target not in seen and d.get('door_open') is True):
                    seen.add(target)
                    queue.append((target, path + [target], route_doors + [d]))
        goal = data['goal']
        found.sort(key=lambda r: (not bool(goal and r['room'] == goal['room']), r['rank'], len(r['path']), r['room']))
        return found

    def annotate(self, offers, state):
        s = self.snapshot
        filtered = [o for o in offers if not self.blocked(o)]
        # Publish only currently executable non-route objectives. Failures and
        # explicit refusals therefore cannot lure the actor back to a room.
        objectives = [self.key(o) for o in filtered if not o.get('guard', {}).get('door')
                      and o['op'] not in {'wait', 'use_active', 'use_pocket'}
                      and o.get('effect') != 'room_change']
        room = self.data['rooms'].get(str(s['identity']['room']))
        if room is not None and room['objectives'] != objectives:
            room['objectives'] = objectives
            self.save()
        routes = self.routes()
        result = []
        seen = set()
        for o in filtered:
            base_id = o.get('base_offer_id', o['id'])
            if base_id in seen:
                continue
            seen.add(base_id)
            d = o.get('guard', {}).get('door')
            if not d:
                result.append(o)
                continue
            candidates = [r for r in routes if r['first_slot'] == d.get('slot')]
            # Special resource/health offers retain existing explicit guards;
            # ordinary free doors with no productive destination are excluded.
            if not candidates and (d.get('door_locked') or d.get('target_room_type') not in self.FREE):
                result.append(o)
            for route in candidates[:3]:
                item = deepcopy(o)
                item['base_offer_id'] = base_id
                item['route'] = {k: v for k, v in route.items() if k != 'rank'}
                item['id'] = signature([base_id, item['route']])
                item['label'] = (f"路线到房间{route['room']}（{route['kind']}）；路径{route['path']}；"
                                 f"终点门钥匙成本{route['terminal_key_cost']}，付费步骤必须重新批准")
                result.append(item)
        return result

    def choose(self, offer):
        route = offer.get('route')
        door = offer.get('guard', {}).get('door', {})
        if route and not door.get('door_locked') and door.get('target_room_type') in self.FREE:
            self.data['goal'] = {k: deepcopy(route[k]) for k in ('room', 'kind', 'path', 'terminal_key_cost')}
            self.emit('route_goal_selected', goal=deepcopy(self.data['goal']))
            self.save()

    def continuation(self, offers):
        goal = self.data['goal']
        if not goal or goal.get('suspended'):
            return None
        return next((o for o in offers if o.get('route', {}).get('room') == goal['room']
                     and not o.get('guard', {}).get('door', {}).get('door_locked')
                     and o.get('guard', {}).get('door', {}).get('target_room_type') in self.FREE), None)

    def suspend(self, reason):
        goal = self.data['goal']
        if goal and not goal.get('suspended'):
            goal.update(suspended=True, suspension_reason=str(reason)[:160])
            self.save()

    def describe(self):
        return {'goal': deepcopy(self.data['goal']), 'progress_revision': self.data['progress'],
                'native_visited_rooms': self.data['native_visited'],
                'surveyed_rooms': sorted(int(k) for k in self.data['rooms']),
                'constraints': deepcopy(list(self.data['constraints'].values())[-12:]),
                'recent_transitions': deepcopy(self.data['transitions'][-12:]),
                'edge_repetition_limit_without_progress': 2,
                'boundary': 'observed graph only; paid/special terminal steps always need fresh DSH approval'}
