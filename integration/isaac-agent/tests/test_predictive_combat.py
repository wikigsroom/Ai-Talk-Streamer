"""Execute the actual Lua input planner against geometric failure cases."""
import sys
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "python-libs"))
from lupa.lua53 import LuaRuntime


class PredictiveCombatTests(unittest.TestCase):
    def setUp(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        source = (ROOT / "mods/IsaacJev/main.lua").read_text(encoding="utf-8")
        planner = "local function hostileLaser(entity)" + source.split("local function hostileLaser(entity)", 1)[1].split("local function resolveSafeMove(player, navigationBlocked)", 1)[0]
        self.api = lua.execute("""
            local mt = {}
            Vector = function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local entities = {}
            EntityType={ENTITY_PROJECTILE=9,ENTITY_LASER=7,ENTITY_PLAYER=1,ENTITY_FAMILIAR=3}
            Isaac={GetRoomEntities=function() return entities end}
            game={GetRoom=function() return {GetGridIndex=function(_,p) return p.X end,
                GetGridPath=function() return 0 end} end}
            local action={move=Vector(0,0)}
            local lastResolvedMove=Vector(0,0)
            local combatAimTargetId,combatAimLockFrame=-1,-10000
            local aimFrame=100
            game.GetFrameCount=function() return aimFrame end
            local enclosed=false
            local routeDirection=Vector(0,1)
            local function followGridRoute() return routeDirection end
            local function isCombatEnemy(e) return e.Type==12 or e.Type==10 or e.Type==16 or e.Type==250 or e.Type==25 or e.Type==29 or e.Type==27 or e.Type==24 or e.Type==39 or e.Type==43 or e.Type==49 or e.Type==55 or e.Type==60 or e.Type==81 or e.Type==84 end
            local function isMovingSpikeTrap(e) return e.Type==212 end
            local function safeMoveCandidate() return not enclosed end
            local function clearTearLine() return true end
            local function actualDoorPosition() return Vector(400,200) end
            local function doorSlotDirection() return Vector(1,0) end
        """ + planner + """
            return {choose_fixed_turret_route=function(withBullet)
                action.waypoint=Vector(520,280)
                routeDirection=Vector(1,0)
                entities={{Type=12,Variant=0,Position=Vector(520,400),Velocity=Vector(0,0),Size=13}}
                if withBullet then entities[2]={Type=9,Position=Vector(445,354),Velocity=Vector(-10,0),Size=5} end
                local move=predictiveCombatMove({Position=Vector(388.2,354.3),Velocity=Vector(0,0),Size=10,MoveSpeed=1,TearRange=260})
                return move.X,move.Y
            end,choose_projectile_window=function(cooldown)
                action.waypoint=Vector(500,200)
                routeDirection=Vector(1,0)
                entities={{Type=9,Position=Vector(320,200),Velocity=Vector(-10,0),Size=5}}
                local move=predictiveCombatMove({Position=Vector(200,200),Velocity=Vector(0,0),
                    Size=10,MoveSpeed=1,TearRange=260,GetDamageCooldown=function() return cooldown end})
                return move.X,move.Y
            end,choose_navigation=function()
                action.mode,action.id,action.move='navigate','enter_door_2',Vector(0,-1)
                routeDirection=Vector(1,0)
                entities={{Type=212,Position=Vector(200,390),Velocity=Vector(0,0),Size=12}}
                local move=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                return move.X,move.Y
            end,choose=function(px,py,ex,ey,bx,by,vx,vy,host,vulnerable)
                entities={{Type=10,Position=Vector(ex,ey),Velocity=Vector(0,0),Size=12}}
                if host then
                    entities[1].Type=27
                    entities[1].ToNPC=function(e) return e end
                    entities[1].IsVulnerableEnemy=function() return vulnerable end
                end
                if bx then entities[2]={Type=9,Position=Vector(bx,by),Velocity=Vector(vx,vy),Size=5} end
                local p={Position=Vector(px,py),MoveSpeed=1,TearRange=260,ShotSpeed=1,Size=10}
                local move,aim=predictiveCombatMove(p)
                return move.X,move.Y,aim.X,aim.Y
            end,
            choose_short_route=function()
                action.waypoint=Vector(400,160)
                entities={{Type=27,Position=Vector(400,280),Velocity=Vector(0,0),Size=12}}
                local move=predictiveCombatMove({Position=Vector(474.8,181.2),Size=10,MoveSpeed=1,TearRange=260})
                return move.X,move.Y
            end,
            choose_adjacent_host=function(threat,vulnerable)
                action.waypoint=Vector(200,200)
                routeDirection=Vector(0,0)
                entities={{Type=27,Variant=0,Position=Vector(240,200),Velocity=Vector(0,0),Size=13,
                    ToNPC=function(e) return e end,IsVulnerableEnemy=function() return vulnerable end}}
                if threat then entities[2]={Type=9,Position=Vector(200,150),Velocity=Vector(0,10),Size=5} end
                local move,aim=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                return move.X,move.Y,aim.X,aim.Y
            end,
            choose_waiting_route=function(threat)
                action.waypoint=Vector(400,160)
                routeDirection=Vector(0,0)
                entities={{Type=10,Position=Vector(370,240),Velocity=Vector(0,0),Size=12}}
                if threat then
                    entities[2]={Type=9,Position=Vector(110,200),Velocity=Vector(10,0),Size=5}
                end
                local move=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                return move.X,move.Y
            end,
            choose_finisher=function(regenerating)
                local corpse={Type=24,Index=1,HitPoints=regenerating and 10 or 3,Position=Vector(370,200),Velocity=Vector(0,0),Size=12,
                    GetSprite=function() return {GetAnimation=function() return regenerating and 'ReGen' or 'WalkHori' end} end,
                    ToNPC=function(e) return e end,IsVulnerableEnemy=function() return regenerating==true end}
                entities={corpse,{Type=10,Index=2,HitPoints=30,Position=Vector(200,370),Velocity=Vector(0,0),Size=12}}
                local _,aim=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                return aim.X,aim.Y
            end,
            choose_vulnerable_heart=function()
                entities={{Type=10,Index=3,HitPoints=150,Position=Vector(260,200),Velocity=Vector(0,0),Size=18,
                    ToNPC=function(e) return e end,IsVulnerableEnemy=function() return false end},
                    {Type=10,Index=23,HitPoints=106,Position=Vector(200,360),Velocity=Vector(0,0),Size=18,
                    ToNPC=function(e) return e end,IsVulnerableEnemy=function() return true end}}
                local move,aim=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                return move.X,move.Y,aim.X,aim.Y
            end,
            choose_stable_target=function()
                entities={{Type=10,Index=1,HitPoints=30,Position=Vector(350,200),Velocity=Vector(0,0),Size=12},
                    {Type=10,Index=2,HitPoints=30,Position=Vector(200,360),Velocity=Vector(0,0),Size=12}}
                local p={Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260}
                local _,a=predictiveCombatMove(p)
                entities[1].Position=Vector(360,200)
                entities[2].Position=Vector(200,350)
                aimFrame=101
                local _,b=predictiveCombatMove(p)
                aimFrame=180
                local _,c=predictiveCombatMove(p)
                return a.X,a.Y,b.X,b.Y,c.X,c.Y
            end,
            choose_enclosed=function()
                enclosed=true
                entities={{Type=9,Position=Vector(110,200),Velocity=Vector(10,0),Size=5}}
                local move=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                return move.X,move.Y
            end,
            choose_telegraph=function(animation,routed,kind,px,py,ex,ey,state,variant,vx,vy,speed)
                entities={{Type=kind or 39,Index=1,State=state,Variant=variant or 0,Position=Vector(ex or 370,ey or 200),Velocity=Vector(0,0),Size=12,
                    GetSprite=function() return {GetAnimation=function() return animation end} end}}
                action.waypoint=routed and Vector(500,200) or nil
                routeDirection=Vector(1,0)
                local move=predictiveCombatMove({Position=Vector(px or 200,py or 200),Velocity=Vector(vx or 0,vy or 0),MoveSpeed=speed or 1,TearRange=260,Size=10})
                return move.X,move.Y
            end,
            choose_fast_contact=function(routed,kind)
                entities={{Type=kind or 10,Position=Vector(-40,200),Velocity=Vector(40,0),Size=12}}
                action.waypoint=routed and Vector(500,200) or nil
                routeDirection=Vector(1,0)
                local move=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                return move.X,move.Y
            end,
            choose_deaths_head_target=function()
                entities={{Type=212,Position=Vector(260,200),Velocity=Vector(0,0),Size=13},
                    {Type=39,Position=Vector(200,370),Velocity=Vector(0,0),Size=13}}
                local _,aim=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                return aim.X,aim.Y
            end,
            choose_pending_tnt=function(routed)
                entities={}
                action.move=Vector(1,0)
                action.waypoint=routed and Vector(500,200) or nil
                routeDirection=Vector(1,0)
                tntBlastGuard={danger=function() return true end,
                    clearance=function(_,p,position) return position:Distance(Vector(340,200))-150 end}
                local move=predictiveCombatMove({Position=Vector(200,200),Size=10,MoveSpeed=1,TearRange=260})
                tntBlastGuard=nil
                return move.X,move.Y
            end,
            choose_death_blast=function(kind,champion,variant)
                entities={{Type=kind,Variant=variant or 0,Index=1,Position=Vector(370,200),Velocity=Vector(0,0),Size=12,
                    ToNPC=function(e) return e end,GetChampionColorIdx=function() return champion end,
                    IsVulnerableEnemy=function() return true end}}
                action.waypoint=Vector(500,200)
                routeDirection=Vector(1,0)
                local move=predictiveCombatMove({Position=Vector(200,200),MoveSpeed=1,TearRange=260,Size=10})
                return move.X,move.Y
            end,
            choose_contact_margin=function(kind)
                entities={{Type=kind,Position=Vector(200,330),Velocity=Vector(0,0),Size=12}}
                action.waypoint=Vector(200,400)
                routeDirection=Vector(0,1)
                local move=predictiveCombatMove({Position=Vector(200,200),MoveSpeed=1,TearRange=260,Size=10})
                return move.X,move.Y
            end,
            choose_mulliboom=function(px,py,vx,vy,speed,ex,ey,evx,evy,variant)
                entities={{Type=16,Variant=variant,Index=1,Position=Vector(ex,ey),Velocity=Vector(evx,evy),Size=12}}
                action.waypoint=Vector(ex,ey)
                routeDirection=Vector(-1,0)
                local move=predictiveCombatMove({Position=Vector(px,py),Velocity=Vector(vx,vy),MoveSpeed=speed,TearRange=260,Size=10})
                return move.X,move.Y
            end,
            choose_laser=function(friendly,damage)
                local laser={Type=7,Position=Vector(0,200),Velocity=Vector(0,0),Size=10,
                    CollisionDamage=damage or 1,SpawnerType=friendly and 1 or 20,
                    ToLaser=function(e) return e end,IsCircleLaser=function() return false end,
                    GetEndPoint=function() return Vector(600,200) end}
                entities={{Type=10,Position=Vector(370,200),Velocity=Vector(0,0),Size=12},laser}
                local p={Position=Vector(200,200),MoveSpeed=1,TearRange=260,ShotSpeed=1,Size=10}
                local move=predictiveCombatMove(p)
                return move.X,move.Y
            end}
        """)

    def test_fixed_horf_approach_uses_body_clearance_and_still_vetoes_a_real_bullet(self):
        self.assertEqual(self.api.choose_fixed_turret_route(False),(1,0))
        self.assertNotEqual(self.api.choose_fixed_turret_route(True),(1,0))

    def test_stationary_diagonal_does_not_hold_and_miss_forever(self):
        x,y,_,_=self.api.choose(218,363,322,277,None,None,None,None)
        before=min(abs(322-218),abs(277-363))
        after=min(abs(322-(218+x*36)),abs(277-(363+y*36)))
        self.assertLess(after,before)

    def test_existing_immunity_allows_plate_progress_but_not_after_it_expires(self):
        self.assertEqual(self.api.choose_projectile_window(60),(1,0))
        for cooldown in (0,5,10,23):
            with self.subTest(cooldown=cooldown):
                self.assertNotEqual(self.api.choose_projectile_window(cooldown),(1,0))

    def test_native_immunity_clock_is_two_units_per_game_frame(self):
        rows=json.loads((ROOT/'tests/fixtures/fallen-immunity-clock-native110.json').read_text(encoding='utf8'))
        elapsed=rows[1]['frame']-rows[0]['frame']
        decrease=rows[0]['player']['damage_cooldown']-rows[1]['player']['damage_cooldown']
        self.assertGreater(elapsed,0)
        self.assertEqual(decrease,2*elapsed)

    def test_vulnerable_heart_is_aimed_at_without_approaching_the_mask(self):
        x,y,ax,ay=self.api.choose_vulnerable_heart()
        self.assertEqual((ax,ay),(0,1))
        self.assertLessEqual(x,0)

    def test_invulnerable_deaths_head_is_a_contact_threat_but_never_an_aim_target(self):
        self.assertEqual(self.api.choose_deaths_head_target(),(0,1))
        for routed in (False,True):
            self.assertNotEqual(self.api.choose_fast_contact(routed,212),(0,0))
            self.assertNotEqual(self.api.choose_fast_contact(routed,212),(1,0))

    def test_monstro_two_stays_out_of_horizontal_beam_lane_including_during_routes(self):
        for routed in (False,True):
            x,y=self.api.choose_telegraph('Idle',routed,43)
            self.assertGreater(abs(y),0.5)

    def test_satan_mouth_windup_leaves_downward_lane_without_inventing_a_ring_beam(self):
        for routed in (False,True):
            x,y=self.api.choose_telegraph('Attack02',routed,84,200,370,200,200,9)
            self.assertGreater(abs(x),.5)
        # Shared Attack03 animation alone must not invent a mouth beam.
        self.assertEqual(self.api.choose_telegraph('Attack03',False,84,200,370,200,200,11),(0,0))
        # The mouth beam does not extend behind Satan.
        self.assertEqual(self.api.choose_telegraph('Attack02',True,84,200,30,200,200,9),(1,0))

    def test_fallen_brimstone_windup_leaves_both_axes(self):
        for routed in (False,True):
            x,y=self.api.choose_telegraph('Attack2',routed,81,200,200,370,200,10)
            self.assertGreater(abs(y),.5)
        self.assertNotEqual(self.api.choose_contact_margin(81),(0,1))

    def test_observed_gluttony_windup_breaks_fatal_horizontal_firing_alignment(self):
        row=json.loads((ROOT/'tests/fixtures/stage7-gluttony-laser-death.json').read_text(encoding='utf8'))
        enemy=row['enemies'][0]
        self.assertEqual(enemy['type'],49)
        for routed in (False,True):
            x,y=self.api.choose_telegraph(enemy['animation'],routed,49,row['x'],row['y'],enemy['x'],enemy['y'])
            self.assertGreater(abs(y),0.5)

    def test_observed_eye_shooting_uses_tangential_dodge_for_aimed_beam(self):
        row=json.loads((ROOT/'tests/fixtures/stage7-eye-laser-hit.json').read_text(encoding='utf8'))
        enemy=row['enemies'][0]
        self.assertEqual(enemy['type'],60)
        dx,dy=row['x']-enemy['x'],row['y']-enemy['y']
        length=(dx*dx+dy*dy)**.5
        for routed in (False,True):
            x,y=self.api.choose_telegraph(enemy['animation'],routed,60,row['x'],row['y'],enemy['x'],enemy['y'])
            self.assertGreater(abs(x*dy-y*dx)/length,.5)

    def test_actual_bloodshot_rotate_states_strafe_before_laser_damage(self):
        rows=json.loads((ROOT/'tests/fixtures/stage7-bloodshot-eye-lasers-native119.json').read_text(encoding='utf8'))
        states=set()
        for row in rows:
            eyes=[e for e in row['enemies'] if e['type']==60 and e['variant']==1]
            if not eyes:
                continue
            eye=eyes[0]
            states.add(eye['state'])
            p=row['player']
            dx,dy=p['pos']['x']-eye['pos']['x'],p['pos']['y']-eye['pos']['y']
            length=(dx*dx+dy*dy)**.5
            for routed in (False,True):
                with self.subTest(frame=row['frame'],routed=routed):
                    x,y=self.api.choose_telegraph(eye['telegraph'],routed,60,
                        p['pos']['x'],p['pos']['y'],eye['pos']['x'],eye['pos']['y'],
                        eye['state'],1,p['vel']['x'],p['vel']['y'],p['move_speed'])
                    self.assertGreater(abs(x*dy-y*dx)/length,.5)
        self.assertTrue({1,8}.issubset(states))

    def test_ordinary_eye_also_strafes_while_rotating_but_holy_eye_does_not(self):
        for variant in (0,1):
            for routed in (False,True):
                x,y=self.api.choose_telegraph('Rotate',routed,60,200,200,370,200,1,variant)
                self.assertGreater(abs(y),.5)
        self.assertEqual(self.api.choose_telegraph('Rotate',True,60,200,200,370,200,1,2),(1,0))

    def test_ignited_tnt_overrides_movement_toward_the_next_target(self):
        for routed in (False,True):
            x,y=self.api.choose_pending_tnt(routed)
            self.assertLess(x,0)

    def test_exploding_enemies_keep_routes_outside_death_blast_before_the_kill(self):
        self.assertEqual(self.api.choose_death_blast(29,-1),(1,0))
        for kind,champion in ((29,5),(25,-1)):
            with self.subTest(kind=kind,champion=champion):
                x,y=self.api.choose_death_blast(kind,champion)
                self.assertLessEqual(x,0)

    def test_kamikaze_leech_blast_is_distinct_from_a_normal_leech(self):
        self.assertEqual(self.api.choose_death_blast(55,-1,0),(1,0))
        x,y=self.api.choose_death_blast(55,-1,1)
        self.assertLessEqual(x,0)

    def test_mulliboom_and_ticking_spider_reserve_death_blast_space(self):
        for kind,variant in ((16,2),(250,0)):
            with self.subTest(kind=kind):
                x,y=self.api.choose_death_blast(kind,-1,variant)
                self.assertLessEqual(x,0)
        for variant in (0,1):
            self.assertEqual(self.api.choose_death_blast(16,-1,variant),(1,0))

    def test_observed_fast_mulliboom_overrides_firing_approach_before_death(self):
        rows=json.loads((ROOT/'tests/fixtures/stage4-explosive-chargers-native122.json').read_text(encoding='utf8'))
        row=next(s for s in rows if s['frame']==55324)
        enemy=next(e for e in row['enemies'] if e['id']==3)
        p=row['player']
        x,y=self.api.choose_mulliboom(p['pos']['x'],p['pos']['y'],p['vel']['x'],p['vel']['y'],p['move_speed'],
            enemy['pos']['x'],enemy['pos']['y'],enemy['vel']['x'],enemy['vel']['y'],enemy['variant'])
        away_x,away_y=p['pos']['x']-enemy['pos']['x'],p['pos']['y']-enemy['pos']['y']
        self.assertGreater(x*away_x+y*away_y,0)

    def test_walking_enemy_route_leaves_reaction_distance_but_host_alcove_still_works(self):
        self.assertLessEqual(self.api.choose_contact_margin(10)[1],0)
        self.assertEqual(self.api.choose_contact_margin(27),(0,1))

    def test_standing_globin_reaction_gap_vetoes_the_approach_before_contact(self):
        self.assertLess(self.api.choose_contact_margin(24)[1],0)

    def test_actual_gazing_globin_appearance_does_not_invite_a_close_approach(self):
        rows=json.loads((ROOT/'tests/fixtures/stage4-explosive-chargers-native122.json').read_text(encoding='utf8'))
        row=next(s for s in rows if s['frame']==54523)
        enemy=next(e for e in row['enemies'] if e['id']==3)
        p=row['player']
        x,y=self.api.choose_telegraph(enemy['telegraph'],True,24,p['pos']['x'],p['pos']['y'],
            enemy['pos']['x'],enemy['pos']['y'],enemy['state'],enemy['variant'],
            p['vel']['x'],p['vel']['y'],p['move_speed'])
        self.assertLess(y,0)

    def test_incoming_projectile_cannot_make_known_unsafe_floor_eligible(self):
        self.assertEqual(self.api.choose_enclosed(),(0,0))

    def test_short_safe_host_route_is_not_vetoed_by_comfort_distance(self):
        self.assertEqual(self.api.choose_short_route(),(0,1))

    def test_adjacent_fixed_host_lane_waits_for_vulnerability_and_still_dodges_bullets(self):
        self.assertEqual(self.api.choose_adjacent_host(False,False),(0,0,0,0))
        self.assertEqual(self.api.choose_adjacent_host(False,True),(0,0,1,0))
        x,y,_,_=self.api.choose_adjacent_host(True,True)
        self.assertGreater(abs(x)+abs(y),0)

    def test_safe_route_can_wait_for_inertia_without_combat_overriding_it(self):
        self.assertEqual(self.api.choose_waiting_route(False),(0,0))

    def test_incoming_bullet_still_overrides_a_waiting_route(self):
        self.assertNotEqual(self.api.choose_waiting_route(True),(0,0))

    def test_low_health_globin_is_finished_before_switching_to_another_enemy(self):
        self.assertEqual(self.api.choose_finisher(),(1,0))
        self.assertEqual(self.api.choose_finisher(True),(1,0))

    def test_aim_does_not_flip_for_small_distance_changes_but_lock_expires(self):
        self.assertEqual(self.api.choose_stable_target(),(1,0,1,0,0,1))

    def test_incoming_projectile_is_avoided_over_prediction_horizon(self):
        x,y,_,_=self.api.choose(200,200,400,200,110,200,10,0)
        separation=min(((200+x*6*t-(110+10*t))**2+(y*6*t)**2)**0.5 for t in (2,5,9))
        self.assertGreater(separation,26)

    def test_safe_aligned_lane_can_hold_and_fire(self):
        x,y,ax,ay=self.api.choose(200,200,370,200,None,None,None,None)
        self.assertEqual((x,y),(0,0))
        self.assertEqual((ax,ay),(1,0))

    def test_closed_host_is_not_kept_closed_by_continuous_shooting(self):
        _,_,ax,ay=self.api.choose(200,200,370,200,None,None,None,None,True,False)
        self.assertEqual((ax,ay),(0,0))
        _,_,ax,ay=self.api.choose(200,200,370,200,None,None,None,None,True,True)
        self.assertEqual((ax,ay),(1,0))

    def test_cleared_trap_room_follows_live_door_route_while_dodging(self):
        self.assertEqual(self.api.choose_navigation(),(1,0))

    def test_moving_trap_corridor_uses_swept_body_space_without_combat_comfort_gap(self):
        self.assertEqual(self.api.choose_contact_margin(212),(0,1))

    def test_enemy_laser_is_evaded_as_a_line_not_a_single_point(self):
        x,y=self.api.choose_laser(False)
        self.assertGreater(abs(y*6*9),40)

    def test_player_laser_does_not_force_an_unnecessary_dodge(self):
        x,y=self.api.choose_laser(True)
        self.assertEqual((x,y),(0,0))

    def test_vis_windup_leaves_horizontal_lane_before_laser_exists(self):
        self.assertGreater(abs(self.api.choose_telegraph('Attack01Horiz',False)[1]),.5)

    def test_route_cannot_override_vis_beam_windup_escape(self):
        self.assertGreater(abs(self.api.choose_telegraph('Attack01Horiz',True)[1]),.5)

    def test_enemy_laser_with_zero_reported_damage_is_not_assumed_safe(self):
        self.assertGreater(abs(self.api.choose_laser(False,0)[1]),.5)

    def test_fast_enemy_crossing_between_prediction_samples_is_evaded(self):
        self.assertGreater(abs(self.api.choose_fast_contact(False)[1]),.5)
        self.assertGreater(abs(self.api.choose_fast_contact(True)[1]),.5)

    def test_invulnerable_maws_and_brimstone_heads_are_not_clear_targets(self):
        source=(ROOT / "mods/IsaacJev/main.lua").read_text(encoding="utf-8")
        trap="local function isStoneTrap(entity)"+source.split("local function isStoneTrap(entity)",1)[1].split("local function liveHazardKind",1)[0]
        enemy="local function isCombatEnemy(entity)"+source.split("local function isCombatEnemy(entity)",1)[1].split("local function hasCombatEnemy",1)[0]
        choose=LuaRuntime().execute("""
            EntityType={ENTITY_SPIDER=85}; EntityFlag={FLAG_FRIENDLY=1}; Isaac={GetPlayer=function() return {} end}
            local function hazardKind() return nil end
            local function isMovingSpikeTrap() return false end
            local function trackingBombInfo() return nil end
        """+trap+enemy+"""
            return function(kind,active)
                local npc={IsActiveEnemy=function() return active~=false end,HasEntityFlags=function() return false end}
                return isCombatEnemy({Type=kind,HitPoints=100,ToNPC=function() return npc end})
            end
        """)
        for kind in (96,203,235,236,963):
            self.assertFalse(choose(kind))
        self.assertTrue(choose(27))
        self.assertTrue(choose(12))
        self.assertTrue(choose(24,False))
        self.assertFalse(choose(12,False))

    def test_frozen_remnants_do_not_override_clear_but_actual_enemy_still_does(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function isCombatEnemy(entity)'+source.split('local function isCombatEnemy(entity)',1)[1].split('local function bossExitInfo',1)[0]
        lua=LuaRuntime()
        choose=lua.execute('''
            EntityType={ENTITY_SPIDER=85};EntityFlag={FLAG_FRIENDLY=1}
            local entities={}
            Isaac={GetPlayer=function() return {} end,GetRoomEntities=function() return entities end}
            local function hazardKind() return nil end
            local function isMovingSpikeTrap() return false end
            local function isStoneTrap() return false end
            local function trackingBombInfo() return nil end
        '''+helper+'''
            return function(kinds)
                entities={}
                for _,kind in ipairs(kinds) do
                    local npc={IsActiveEnemy=function() return true end,HasEntityFlags=function() return false end}
                    entities[#entities+1]={Type=kind,HitPoints=9,ToNPC=function() return npc end}
                end
                return hasCombatEnemy()
            end
        ''')
        actual=json.loads((ROOT/'tests/fixtures/stage4-corner-blocked-by-ice.json').read_text(encoding='utf8'))
        kinds=[enemy['type'] for enemy in actual['enemies']]
        self.assertFalse(choose(lua.table_from([kind for kind in kinds if kind==963])))
        self.assertTrue(choose(lua.table_from(kinds)))


if __name__ == "__main__":
    unittest.main()
