"""Observe damage/clears, independently of moving frames or living services."""
from math import isfinite


def number(value):
    return type(value) in (int, float) and isfinite(value)


def combat_observation(view):
    data = view.get('data') or {}
    room, player = data.get('room') or {}, data.get('player') or {}
    identity = data.get('identity') or view.get('identity') or {}
    enemies = data.get('enemies')
    if (view.get('connected') is not True or not number(view.get('age_ms'))
            or not 0 <= view['age_ms'] < 1500 or room.get('clear') is not False
            or room.get('paused') is not False or room.get('dead') is not False
            or not number(player.get('hp')) or player['hp'] <= 0
            or type(data.get('frame', view.get('frame'))) is not int
            or not isinstance(enemies, list) or not enemies
            or any(identity.get(k) is None for k in ('seed', 'stage', 'room', 'visit'))):
        return None
    health = {}
    for enemy in enemies:
        if (not isinstance(enemy, dict) or type(enemy.get('id')) is not int
                or not number(enemy.get('hp')) or enemy['hp'] <= 0
                or enemy['id'] in health):
            return None
        health[enemy['id']] = enemy['hp']
    key = tuple(identity.get(k) for k in ('controller', 'seed', 'restart', 'stage', 'stage_type', 'dimension', 'room', 'visit', 'bridge'))
    return key, data.get('frame', view.get('frame')), health


class CombatProgress:
    def __init__(self, timeout_seconds=180):
        self.timeout_seconds = timeout_seconds
        self.reset()

    def reset(self):
        self.identity = self.since = self.last_frame = self.last_advanced_at = None
        self.health = {}
        self.seconds = 0
        self.stalled = False

    def update(self, view, *, enabled, now):
        observed = combat_observation(view) if enabled else None
        if observed is None:
            self.reset()
            return False
        identity, frame, health = observed
        if identity != self.identity or self.last_frame is None or frame < self.last_frame:
            self.reset()
            self.identity, self.since, self.last_advanced_at = identity, now, now
            self.health = dict(health)
        elif any(eid not in health or health[eid] < hp for eid, hp in self.health.items()):
            # Each enemy's lowest observed HP prevents a regenerating enemy
            # from disguising endless damage/heal cycles as forward progress.
            self.since = now
        self.health = {eid: min(hp, self.health.get(eid, hp)) for eid, hp in health.items()}
        if frame != self.last_frame:
            self.last_advanced_at = now
        self.last_frame = frame
        self.seconds = max(0, now-self.since)
        self.stalled = self.seconds >= self.timeout_seconds and now-self.last_advanced_at < 3
        return self.stalled

    def status(self):
        return {'observing_combat': self.identity is not None,
                'no_damage_progress_seconds': round(self.seconds, 1),
                'timeout_seconds': self.timeout_seconds, 'stalled': self.stalled,
                'enemy_count': len(self.health), 'lowest_enemy_hp': dict(self.health)}


def quiet_combat_boundary(view, decision, controller, core):
    """Permit source repair in a distant stationary stalemate, never a fight."""
    if (combat_observation(view) is None or controller.get('armed') is not True
            or controller.get('manual_override') is not False
            or (controller.get('live_cycle') or {}).get('phase') != 'playing'
            or (controller.get('strategy') or {}).get('executing') is not None
            or (controller.get('strategy') or {}).get('pending') is not None
            or decision.get('connected') is not True or decision.get('pending') is not False
            or core.get('ready') is not True or core.get('automatic') is not True
            or core.get('busy') is not False):
        return False
    data = view['data']
    pos = data['player'].get('pos') or {}
    if (not all(number(pos.get(k)) for k in ('x', 'y'))
            or not isinstance(data.get('projectiles'), list)
            or not isinstance(data.get('danger_effects'), list) or data['danger_effects']):
        return False
    for entity in data['enemies']:
        point = entity.get('pos') or {}
        if (not all(number(point.get(k)) for k in ('x', 'y'))
                or (point['x']-pos['x'])**2+(point['y']-pos['y'])**2 < 220**2):
            return False
    for enemy in data['enemies']:
        velocity = enemy.get('vel') or {}
        if (not all(number(velocity.get(k)) for k in ('x', 'y'))
                or abs(velocity['x'])+abs(velocity['y']) >= .2):
            return False
    for projectile in data['projectiles']:
        point, velocity = projectile.get('pos') or {}, projectile.get('vel') or {}
        if (not all(number(point.get(k)) and number(velocity.get(k)) for k in ('x', 'y'))
                or any((point['x']+velocity['x']*tick-pos['x'])**2
                       +(point['y']+velocity['y']*tick-pos['y'])**2 < 110**2 for tick in (0,4,8))):
            return False
    return True
