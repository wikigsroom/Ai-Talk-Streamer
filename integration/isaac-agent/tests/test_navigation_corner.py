"""A finite-size player must clear a rock corner before turning."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from isaac_jev.models import Door, Entity, GameState, RoomLayout, Vec2
from isaac_jev.decision import build_candidate_set, local_policy_action
from isaac_jev.navigation import move_towards


class NavigationCornerTests(unittest.TestCase):
    def test_stationary_enemy_behind_rocks_gets_a_reachable_firing_lane(self):
        blocked = frozenset([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,18,29,30,31,33,
                             44,45,46,48,59,60,74,75,86,88,89,90,101,103,104,105,116,
                             118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134])
        player = Entity(0,1,Vec2(222,240),Vec2(),hit_points=6)
        enemy = Entity(8,12,Vec2(120,160),Vec2(),hit_points=10,grid_index=17)
        state = GameState(frame=0,player=player,enemies=(enemy,),projectiles=(),
                          player_grid_index=50,room_clear=False,movement_progress=2,
                          safe_move_directions={k:"safe" for k in ["left","right","up","down"]},
                          layout=RoomLayout(grid_width=15,grid_height=9,blocked=blocked,
                                            doors=(Door(0,Vec2(40,280),grid_index=60),)))
        for tick in range(250):
            action = local_policy_action(state,build_candidate_set(state))
            if action.shoot != Vec2() and state.geometry_features().get("line_of_fire"):
                return
            position=Vec2(state.player.position.x+action.move.x*2,
                          state.player.position.y+action.move.y*2)
            for cell in blocked:
                row,col=divmod(cell,15)
                dx=max(abs(position.x-(40+col*40))-20,0)
                dy=max(abs(position.y-(120+row*40))-20,0)
                self.assertGreaterEqual(dx*dx+dy*dy,9*9)
            index=int((position.y-100)//40)*15+int((position.x-20)//40)
            state=replace(state,frame=tick+1,player=replace(player,position=position),
                          player_grid_index=index)
        self.fail("The local policy never reached a clear firing lane")

    def test_player_reaches_exit_through_a_one_cell_bend_without_clipping(self):
        width, height = 7, 7
        floor = {22, 23, 16, 9, 10, 11, 12}
        blocked = frozenset(set(range(width*height)) - floor)
        door = Door(2, Vec2(240, 40), target_room_index=2, grid_index=13)
        player = Entity(0, 1, Vec2(40, 120), Vec2(), hit_points=6)
        state = GameState(frame=0, player=player, enemies=(), projectiles=(),
                          player_grid_index=22, room_clear=True,
                          layout=RoomLayout(grid_width=width, grid_height=height,
                                            blocked=blocked, doors=(door,)))
        for tick in range(400):
            position = state.player.position
            if position.distance_to(door.position) <= 65:
                return
            move = move_towards(state, door.position, door.grid_index)
            position = Vec2(position.x + move.x*2, position.y + move.y*2)
            for cell in blocked:
                row, col = divmod(cell, width)
                dx = max(abs(position.x-col*40)-20, 0)
                dy = max(abs(position.y-row*40)-20, 0)
                self.assertGreaterEqual(dx*dx+dy*dy, 9*9,
                                        f"Player clipped a rock at tick {tick}: {position}")
            index = int((position.y+20)//40)*width + int((position.x+20)//40)
            state = replace(state, frame=tick+1, player=replace(player, position=position),
                            player_grid_index=index)
        self.fail("The route failed to reach the exit approach")


if __name__ == "__main__":
    unittest.main()
