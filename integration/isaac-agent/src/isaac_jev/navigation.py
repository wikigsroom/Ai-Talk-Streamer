from __future__ import annotations

import heapq
from dataclasses import replace

from .models import Door, GameState, Vec2


def _path_blocked(state: GameState) -> frozenset[int]:
    """Include live fireplaces, which are entities rather than grid obstacles."""
    return state.layout.blocked | state.layout.danger_grid_indices | frozenset(
        hazard.grid_index for hazard in state.hazards
        if hazard.kind == "fire" and hazard.grid_index >= 0
    )


def door_is_usable(door: Door, state: GameState | None = None) -> bool:
    """Shared admission rules for planning and execution candidates."""
    special_route = (state is not None and state.progression_target == "satan"
                     and 2 <= state.stage <= 8 and door.target_room_type == "devil"
                     and door.open_known and door.open and not door.locked)
    if door.target_room_index < 0 and not special_route:
        return False
    # These branches are optional for a normal victory and deliberately cost
    # health or add combat. Leaving one still uses its ordinary exit door.
    if state is not None and door.target_room_type in {"curse", "sacrifice", "challenge"}:
        return False
    if door.target_room_type in {"secret", "super_secret"}:
        return not door.locked and ((door.open_known and door.open) or (not door.open_known and door.lock_known))
    if door.locked:
        if door.target_room_type == "shop" and state is not None and state.coins < 5:
            return False
        if door.target_room_type not in {"treasure", "shop", "library"} or state is None or state.keys <= 0:
            return False
        # Key doors stay closed until Isaac touches and unlocks them.
        return True
    if door.open_known and not door.open:
        return False
    if door.target_room_type == "curse":
        if state is None or sum(getattr(state, name, 0) for name in ("red_hearts", "soul_hearts", "black_hearts")) < 6:
            return False
    return True


def newly_opened_secret_door(state: GameState) -> Door | None:
    """Return the unvisited secret entrance opened by this room's bomb."""
    if not state.bomb_placed or state.bomb_target_id > -200000:
        return None
    slot = -200000 - state.bomb_target_id
    return next((door for door in state.layout.doors
                 if door.slot == slot
                 and door.target_room_type in {"secret", "super_secret"}
                 and door.open_known and door.open
                 and door.target_room_index not in state.visited_room_indices
                 and door_is_usable(door, state)), None)


def path_distance(state: GameState, target: Vec2, target_grid_index: int, *, allow_timed: bool = False) -> float:
    """Remaining grid route length, falling back to distance without geometry."""
    layout = state.layout
    if not layout.grid_width or not layout.grid_height or target_grid_index < 0 or state.player_grid_index < 0:
        return target.distance_to(state.player.position)
    start = state.player_grid_index
    blocked = _path_blocked(state)
    if allow_timed:
        # Admission can consider a future open spike window. Execution still
        # uses live floor safety and the native time-dependent route planner.
        blocked -= frozenset(event.grid_index for event in layout.grid_events
                             if event.kind == 'spike' and event.timed)
    queue = [(start, 0)]
    seen = {start}
    for current, distance in queue:
        if current == target_grid_index:
            return distance * 40.0 + (target.distance_to(state.player.position) if distance == 0 else 0.0)
        for neighbor in _neighbors(current, layout.grid_width, layout.grid_height):
            if neighbor not in seen and neighbor not in blocked:
                seen.add(neighbor)
                queue.append((neighbor, distance + 1))
    return float("inf")


def door_path_distance(state: GameState, door: Door) -> float:
    """Return the route to a walkable tile beside a door.

    Door grid cells are wall/threshold cells and are commonly marked blocked.
    Measuring a route to the door cell itself therefore reports infinity even
    though an adjacent approach tile is reachable, which can make navigation
    oscillate while repeatedly recomputing a false dead end.
    """
    layout = state.layout
    if not layout.grid_width or not layout.grid_height or door.grid_index < 0:
        return door.position.distance_to(state.player.position)
    blocked = _path_blocked(state)
    best = float("inf")
    for goal in _approach_goals(door.grid_index, layout.grid_width, layout.grid_height, blocked):
        distance = path_distance(state, Vec2(), goal)
        if distance < best:
            best = distance
    if best < float("inf"):
        return best
    # A player already at the threshold may be crossing it even if the grid
    # snapshot has no walkable approach tile for one frame.
    if state.player.position.distance_to(door.position) <= 70:
        return state.player.position.distance_to(door.position)
    effects = state.danger_effects + state.floor_danger_effects
    moving = tuple(effect for effect in effects
                   if effect.kind in {'moving_spike', 'moving_spike_future'})
    if moving:
        # A moving trap can temporarily span a one-cell corridor. It affects
        # movement now, not whether this branch exists in the floor graph.
        transient, persistent = set(), set()
        for index in layout.danger_grid_indices:
            center = grid_cell_center(state, index)
            if center is None:
                continue
            if any(center.distance_to(effect.position) <= effect.radius + 18 for effect in moving):
                transient.add(index)
            if any(effect.kind not in {'moving_spike', 'moving_spike_future', 'ghost_bomb', 'armed_bomb'}
                   and center.distance_to(effect.position) <= effect.radius + 18
                   for effect in effects):
                persistent.add(index)
        persistent.update(event.grid_index for event in layout.grid_events if event.active)
        future_danger = (layout.danger_grid_indices - transient) | persistent
        if future_danger != layout.danger_grid_indices:
            future = replace(state, layout=replace(layout, danger_grid_indices=frozenset(future_danger)),
                             danger_effects=tuple(effect for effect in state.danger_effects if effect not in moving),
                             floor_danger_effects=tuple(effect for effect in state.floor_danger_effects if effect not in moving))
            return door_path_distance(future, door)
    timed = frozenset(event.grid_index for event in layout.grid_events if event.kind == "spike" and event.timed)
    if timed & (layout.danger_grid_indices | layout.blocked):
        # A closed timing window does not make a floor branch unreachable.
        # This relaxes admission only: move_towards and Lua still check the
        # current live floor before sending each movement input.
        future = replace(state, layout=replace(layout, blocked=layout.blocked-timed,
            danger_grid_indices=layout.danger_grid_indices-timed))
        return door_path_distance(future, door)
    return float("inf")


def firing_position(state: GameState, target: Vec2, target_grid_index: int,
                    minimum_range: float = 105.0, *, avoid_dead_ends: bool = False,
                    firing_axis: str | None = None) -> tuple[Vec2, int, Vec2] | None:
    """Find a reachable cardinal firing lane inside the player's tear range."""
    layout = state.layout
    maximum_range = max(0.0, state.player.tear_range - 25.0)
    if maximum_range < minimum_range:
        return None
    if not layout.grid_width or not layout.grid_height or target_grid_index < 0:
        delta = Vec2(target.x - state.player.position.x, target.y - state.player.position.y)
        distance = target.distance_to(state.player.position)
        horizontal = firing_axis == "horizontal" or (firing_axis != "vertical" and abs(delta.x) >= abs(delta.y))
        direction = Vec2(_sign(delta.x) or 1, 0) if horizontal else Vec2(0, _sign(delta.y) or 1)
        aligned = abs(delta.y) <= 18 if horizontal else abs(delta.x) <= 18
        if minimum_range <= distance <= maximum_range and aligned:
            return state.player.position, state.player_grid_index, direction
        desired_distance = min(max(distance, minimum_range + 5), maximum_range)
        position = Vec2(target.x - direction.x * desired_distance,
                        target.y - direction.y * desired_distance)
        return position, -1, direction
    width, height = layout.grid_width, layout.grid_height
    target_row, target_col = divmod(target_grid_index, width)
    blocked = _path_blocked(state)
    def lane_has_escape(index: int) -> bool:
        if not avoid_dead_ends:
            return True
        row,col=divmod(index,width)
        exits=0
        for next_row,next_col in ((row-1,col),(row+1,col),(row,col-1),(row,col+1)):
            if (0<=next_row<height and 0<=next_col<width
                    and next_row*width+next_col not in blocked):
                exits+=1
        return exits>=2
    shot_blocked = (layout.shot_blocked if layout.shot_blocked is not None else layout.blocked) | frozenset(
        hazard.grid_index for hazard in state.hazards if hazard.kind == "fire" and hazard.grid_index >= 0)
    # A valid lane under Isaac's feet is the most stable choice: stop moving
    # and keep shooting instead of replanning an adjacent grid centre.
    delta = Vec2(target.x - state.player.position.x, target.y - state.player.position.y)
    distance_here = target.distance_to(state.player.position)
    if minimum_range <= distance_here <= maximum_range and min(abs(delta.x), abs(delta.y)) <= 14:
        player_index = state.player_grid_index
        if player_index >= 0 and lane_has_escape(player_index):
            player_row, player_col = divmod(player_index, width)
            same_row = firing_axis != "vertical" and player_row == target_row and abs(delta.y) <= 14
            same_col = firing_axis != "horizontal" and player_col == target_col and abs(delta.x) <= 14
            if same_row or same_col:
                if same_row:
                    between = (player_row * width + col for col in range(min(player_col, target_col) + 1,
                                                                           max(player_col, target_col)))
                    direction = Vec2(_sign(delta.x), 0)
                else:
                    between = (row * width + player_col for row in range(min(player_row, target_row) + 1,
                                                                           max(player_row, target_row)))
                    direction = Vec2(0, _sign(delta.y))
                if not any(index in shot_blocked for index in between):
                    return state.player.position, player_index, direction
    options: list[tuple[float, Vec2, int, Vec2]] = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if (firing_axis == "vertical" and dx) or (firing_axis == "horizontal" and dy):
            continue
        for cells in range(1, int(maximum_range // 40) + 1):
            row, col = target_row + dy * cells, target_col + dx * cells
            if not (0 <= row < height and 0 <= col < width):
                break
            index = row * width + col
            if index in shot_blocked:
                break
            if index in blocked:
                continue
            if not lane_has_escape(index):
                continue
            position = Vec2(target.x + dx * cells * 40, target.y + dy * cells * 40)
            distance = position.distance_to(target)
            if distance < minimum_range or distance > maximum_range:
                continue
            route = path_distance(state, position, index)
            if route < float("inf"):
                options.append((route + distance * 0.05, position, index, Vec2(-dx, -dy)))
    if not options:
        return None
    _, position, index, direction = min(options, key=lambda item: item[0])
    return position, index, direction


def bombing_position(state: GameState, target: Vec2, target_grid_index: int) -> tuple[Vec2, int] | None:
    """Find a reachable adjacent tile; nominal blast reach is not a hit guarantee."""
    layout = state.layout
    distance_here = target.distance_to(state.player.position)
    if 32 <= distance_here <= 60 and state.player_grid_index not in layout.danger_grid_indices:
        return state.player.position, state.player_grid_index
    if not layout.grid_width or not layout.grid_height or target_grid_index < 0:
        delta = Vec2(state.player.position.x - target.x, state.player.position.y - target.y)
        distance = max(1.0, target.distance_to(state.player.position))
        site = Vec2(target.x + delta.x / distance * 50, target.y + delta.y / distance * 50)
        return site, -1
    width, height = layout.grid_width, layout.grid_height
    target_row, target_col = divmod(target_grid_index, width)
    blocked = _path_blocked(state)
    options: list[tuple[float, Vec2, int]] = []
    for dr in range(-3, 4):
        for dc in range(-3, 4):
            row, col = target_row + dr, target_col + dc
            if not (0 <= row < height and 0 <= col < width):
                continue
            distance = (dr * dr + dc * dc) ** 0.5 * 40
            if not 32 <= distance <= 60:
                continue
            index = row * width + col
            if index in blocked:
                continue
            site = Vec2(target.x + dc * 40, target.y + dr * 40)
            route = path_distance(state, site, index)
            if route < float("inf"):
                options.append((route + abs(distance - 50) * 0.1, site, index))
    if not options:
        return None
    _, site, index = min(options, key=lambda option: option[0])
    return site, index


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _neighbors(index: int, width: int, height: int):
    row, col = divmod(index, width)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        next_row, next_col = row + dr, col + dc
        if 0 <= next_row < height and 0 <= next_col < width:
            yield next_row * width + next_col


def _first_path_step(start: int, goal: int, width: int, height: int, blocked: frozenset[int]) -> int | None:
    if start == goal or start < 0 or goal < 0 or start in blocked or goal in blocked:
        return None
    queue = [(0, start)]
    parents = {start: None}
    costs = {start: 0}
    while queue:
        _, current = heapq.heappop(queue)
        if current == goal:
            while parents[current] != start and parents[current] is not None:
                current = parents[current]
            return current
        for neighbor in _neighbors(current, width, height):
            if neighbor in blocked:
                continue
            cost = costs[current] + 1
            if cost < costs.get(neighbor, 1_000_000):
                parents[neighbor] = current
                costs[neighbor] = cost
                row, col = divmod(neighbor, width)
                goal_row, goal_col = divmod(goal, width)
                heapq.heappush(queue, (cost + abs(row - goal_row) + abs(col - goal_col), neighbor))
    return None


def _approach_goals(goal: int, width: int, height: int, blocked: frozenset[int]):
    """Yield walkable tiles next to a door/wall target, closest first."""
    if goal < 0:
        return
    target_row, target_col = divmod(goal, width)
    preferred: list[tuple[int, int]] = []
    if target_row == 0:
        preferred.append((1, 0))
    elif target_row == height - 1:
        preferred.append((-1, 0))
    if target_col == 0:
        preferred.append((0, 1))
    elif target_col == width - 1:
        preferred.append((0, -1))
    yielded: set[int] = set()
    for row_offset, col_offset in preferred:
        row, col = target_row + row_offset, target_col + col_offset
        if 0 <= row < height and 0 <= col < width:
            index = row * width + col
            if index not in blocked:
                yielded.add(index)
                yield index
    for radius in range(0, 4):
        for row_offset in range(-radius, radius + 1):
            col_offset = radius - abs(row_offset)
            for signed_col_offset in ({col_offset, -col_offset} if col_offset else {0}):
                row, col = target_row + row_offset, target_col + signed_col_offset
                if not (0 <= row < height and 0 <= col < width):
                    continue
                index = row * width + col
                if index not in blocked and index not in yielded:
                    yielded.add(index)
                    yield index


def grid_cell_center(state: GameState, index: int) -> Vec2 | None:
    """Recover cell coordinates from a door's reported world/grid positions."""
    layout = state.layout
    if not layout.grid_width or index < 0:
        return None
    anchor = next((door for door in layout.doors if door.grid_index >= 0), None)
    if anchor is None:
        return None
    row, col = divmod(index, layout.grid_width)
    anchor_row, anchor_col = divmod(anchor.grid_index, layout.grid_width)
    return Vec2(anchor.position.x + (col-anchor_col)*40,
                anchor.position.y + (row-anchor_row)*40)


def move_towards(state: GameState, target: Vec2, target_grid_index: int = -1) -> Vec2:
    layout = state.layout
    if layout.grid_width and layout.grid_height and target_grid_index >= 0:
        blocked = _path_blocked(state)
        for goal in _approach_goals(target_grid_index, layout.grid_width, layout.grid_height, blocked):
            if state.player_grid_index == goal:
                if goal == target_grid_index:
                    dx, dy = target.x - state.player.position.x, target.y - state.player.position.y
                    if abs(dx) + abs(dy) > 3:
                        return Vec2(_sign(dx), 0) if abs(dx) >= abs(dy) else Vec2(0, _sign(dy))
                return Vec2()
            next_step = _first_path_step(state.player_grid_index, goal, layout.grid_width, layout.grid_height, blocked - {state.player_grid_index})
            if next_step is not None:
                start_row, start_col = divmod(state.player_grid_index, layout.grid_width)
                next_row, next_col = divmod(next_step, layout.grid_width)
                # Crossing a cell boundary does not mean the player's body
                # has cleared the adjacent rock. Center the perpendicular
                # axis before turning, using a reported door as a grid anchor.
                center = grid_cell_center(state, state.player_grid_index)
                if center is not None and state.player_grid_index not in blocked:
                    if next_col != start_col:
                        offset = center.y - state.player.position.y
                        if 6 < abs(offset) <= 21:
                            direction = "down" if offset > 0 else "up"
                            if state.safe_move_directions.get(direction, "safe") == "safe":
                                return Vec2(0, _sign(offset))
                    if next_row != start_row:
                        offset = center.x - state.player.position.x
                        if 6 < abs(offset) <= 21:
                            direction = "right" if offset > 0 else "left"
                            if state.safe_move_directions.get(direction, "safe") == "safe":
                                return Vec2(_sign(offset), 0)
                return Vec2(next_col - start_col, next_row - start_row)
        # Room geometry was supplied but no walkable route exists. Stopping is
        # safer than blindly holding a diagonal direction into a wall.
        return Vec2()
    dx, dy = target.x - state.player.position.x, target.y - state.player.position.y
    return Vec2(_sign(dx), 0) if abs(dx) >= abs(dy) else Vec2(0, _sign(dy))
