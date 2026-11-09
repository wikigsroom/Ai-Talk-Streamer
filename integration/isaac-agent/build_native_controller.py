"""Reuse the local policy as an in-memory native input controller, without RegisterMod.

No achievement/persistence functions are called. Gameplay input uses the ordinary
input callback; direct tear spawning, fire-delay writes and velocity writes are removed.
The game retains sole responsibility for eligibility and unlocks.
"""
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def build(run_goal='normal_progress', output=None):
    if run_goal not in {'normal_progress','mom','heart','satan','isaac','blue_baby','lamb','hush','delirium','mother','beast'}:
        raise ValueError('Unsupported run goal')
    source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf-8')
    first='local mod = RegisterMod("Isaac Jev", 1)'
    assert source.count(first)==1
    source=source.replace(first,'''local previous = _G.__NativeIsaacController
if previous then
    if previous.NativeShutdown then previous:NativeShutdown() end
    for _,id in pairs(ModCallbacks) do
        if type(id)=="number" then
            local callbacks=Isaac.GetCallbacks(id)
            if callbacks then
                for i=#callbacks,1,-1 do
                    if callbacks[i].Mod==previous then Isaac.RemoveCallback(previous,id,callbacks[i].Function) end
                end
            end
        end
    end
end
_G.ISAAC_LOCAL_RUN_TARGET="__ISSAC_CURRENT_LEGAL_RUN_GOAL__"
local mod = {Name="Native Isaac Input Controller"}
function mod:AddCallback(id,fn,param) Isaac.AddCallback(self,id,fn,param) end
_G.__NativeIsaacController = mod''',1)
    source=source.replace('__ISSAC_CURRENT_LEGAL_RUN_GOAL__', '' if run_goal=='normal_progress' else run_goal)
    source=source.replace('local MOD_VERSION = "2026-11-06-local39"','local MOD_VERSION = "2026-11-07-native130-dsh"')
    strategy_module=(ROOT/'mods/IsaacJev/strategy_control.lua').read_text(encoding='utf-8')
    source=source.replace('include("strategy_control")','(function()\n'+strategy_module+'\nend)()')
    weapon_module=(ROOT/'mods/IsaacJev/weapon_control.lua').read_text(encoding='utf-8')
    source=source.replace('include("weapon_control")','(function()\n'+weapon_module+'\nend)()')
    spike_module=(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf-8')
    source=source.replace('include("timed_spikes")','(function()\n'+spike_module+'\nend)()')
    tnt_module=(ROOT/'mods/IsaacJev/tnt_safety.lua').read_text(encoding='utf-8')
    source=source.replace('include("tnt_safety")','(function()\n'+tnt_module+'\nend)()')
    profile_module=(ROOT/'mods/IsaacJev/runtime_profile.lua').read_text(encoding='utf-8')
    source=source.replace('include("runtime_profile")','(function()\n'+profile_module+'\nend)()')
    geometry_module=(ROOT/'mods/IsaacJev/gpu_geometry.lua').read_text(encoding='utf-8')
    source=source.replace('include("gpu_geometry")','(function()\n'+geometry_module+'\nend)()')
    source=source.replace('        player.Velocity = Vector(0, 0)','        -- Native input only: preserve normal inertia.')
    start=source.index('    if automatic and game:GetFrameCount() - lastActionFrame <= 45 and needsTearFallback')
    end=source.index('\nend\n\nfunction mod:onInput',start)
    source=source[:start]+'    -- Native firing is exclusively driven by input; no FireTear fallback.\n'+source[end:]
    start=source.index('    -- A fixed local reload marker')
    end=source.index('    if Input.IsButtonTriggered(Keyboard.KEY_F8, 0)',start)
    source=source[:start]+source[end:]
    # Keep the actual render/death heartbeat callback, while keeping private
    # controller diagnostics out of the recorded game picture.
    start=source.index('    local label = "LOCAL WAITING (bridge)"')
    end=source.index('\nend\n\nmod:AddCallback(ModCallbacks.MC_POST_UPDATE',start)
    source=source[:start]+'    -- Controller diagnostics remain in the private native state.\n'+source[end:]
    # A completed/dead run is observed and disarmed by the host. Never start a
    # new run through the console, even if a previous controller is still fresh.
    start=source.index('    -- The game stops simulation updates on the death screen.')
    end=source.index('    return true\nend\n\nlocal function collectState()',start)
    source=source[:start]+'''    -- Retain the actual end screen until ordinary menu input starts another run.
    restartPhase = "death_wait"
'''+source[end:]
    # Walking onto an authorized trinket lets the game apply its normal pickup
    # and swap rules. Direct DropTrinket would bypass those rules (notably Tick).
    start=source.index('    local wantedTrinketId = tonumber(string.match(action.id')
    end=source.index('    -- A response can arrive one state packet after',start)
    source=source[:start]+'    -- Trinket swaps use the normal, identity-fenced pickup collision only.\n'+source[end:]
    source += '''
function mod:NativeShutdown()
    automatic,controllerEnabled,manualOverride=false,false,true
    resolvedMove,fireDirection=Vector(0,0),Vector(0,0)
    closeClient()
    self.gpuGeometry:close()
end
function mod:NativeResume()
    if game:GetNumPlayers()~=1 or playerIsDead(Isaac.GetPlayer(0)) then return false end
    strategyControl:resumePauseHold()
    closeClient()
    lastStateFrame=-10000
    pendingState=nil
    manualOverride=false
    return true
end
function mod:NativeControlStatus()
    local player=Isaac.GetPlayer(0)
    local checks={}
    for name,direction in pairs({left=Vector(-1,0),right=Vector(1,0),up=Vector(0,-1),down=Vector(0,1)}) do
        local safe,reason=safeMoveCandidate(player,direction,false)
        checks[name]={safe=safe,reason=reason}
    end
    return Json.encode({frame=game:GetFrameCount(),action={id=action.id,mode=action.mode,
        move=vectorTable(action.move),shoot=vectorTable(action.shoot),
        waypoint=action.waypoint and vectorTable(action.waypoint) or nil,
        ignored_pickups=action.ignoredPickupIds,door_slot=action.doorSlot,
        strategy_target=strategyControl and strategyControl.target},
        move=vectorTable(resolvedMove),shoot=vectorTable(fireDirection),
        route=routeDebug,move_reason=lastMoveResolutionReason,safety=checks,
        input=self:inputLease(player),position=vectorTable(player.Position)})
end
function mod:onNativeNPCDeath(npc)
    if npc.Type == 45 or npc.Type == 78 or npc.Type == 84 then
        Isaac.DebugString("[NativeIsaac] BOSS_DEATH " .. Json.encode({
            type=npc.Type, variant=npc.Variant, stage=game:GetLevel():GetStage(),
            stage_type=game:GetLevel():GetStageType(), seed=startSeed(), frame=game:GetFrameCount()}))
    end
end
mod:AddCallback(ModCallbacks.MC_POST_NPC_DEATH, mod.onNativeNPCDeath)
return "native controller installed"
'''
    assert 'RegisterMod(' not in source
    assert ':FireTear(' not in source
    assert ':FireBomb(' not in source
    assert ':AddBombs(' not in source
    assert 'player.Velocity =' not in source
    assert 'player.FireDelay =' not in source
    assert 'luamod IsaacJev' not in source
    assert 'Isaac.ExecuteCommand(' not in source
    assert ':DropTrinket(' not in source
    output=Path(output) if output is not None else ROOT/'native-controller.lua'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(source,encoding='utf-8')
    return output

if __name__=='__main__': print(build())
