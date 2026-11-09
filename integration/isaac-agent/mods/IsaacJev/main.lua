-- Isaac Jev: Repentance only. Requires Steam launch option --luadebug.
-- The high-frequency input callback only consumes cached local state; it never opens sockets.

local mod = RegisterMod("Isaac Jev", 1)
local game = Game()
local strategyControl = include("strategy_control").new(game)
mod.strategyControl = strategyControl
local socketOk, socket = pcall(require, "socket")
mod.gpuGeometry = include("gpu_geometry").new(socketOk and socket or nil, _G.ISAAC_GPU_GEOMETRY)
local Json = _G.json
if not Json then
    local jsonOk, jsonModule = pcall(require, "json")
    if jsonOk then Json = jsonModule end
end

mod.runtimeProfile = include("runtime_profile").new()

local HOST, PORT = "127.0.0.1", 9528
local client = nil
local pendingState = nil
local pendingStateRequiresReply = false
local pendingActionPartial = ""
local stateAwaitingReply = false
local pendingGameEvent = nil
local bridgeStatus = socketOk and (Json and "disconnected" or "json unavailable") or "socket unavailable"
local automatic = false
local controllerEnabled = false
local lastControlMessageAt = -10000
local manualOverride = false
local gridEscapeActive = false
local lastActionFrame = -10000
local action = { id = "", move = Vector(0, 0), shoot = Vector(0, 0), mode = "combat", target = "", reason = "", sourceRoomIndex = -1, targetRoomIndex = -1, ignoredHazardIds = {}, ignoredPickupIds = {} }
local bombTargetId = -1
local bombPlaced = false
local bombPlacedFrame = -1
local bombPosition = nil
local bombEntity = nil
local bombPlacementDistance = -1
local bombRetreatDirection = Vector(1, 0)
local bombRoomKey = ""
local bombRetreatActive = false
local ghostBombRetreatActive = false
local bombError = nil
local bombedWallKeys = {}
local lastLayoutRoom = -99999
local lastLayout = nil
local lastStateFrame = -99999
local sentStateCount = 0
local firedTearCount = 0
local fireError = nil
local fireBlockReason = "idle"
local MOD_VERSION = "2026-11-06-local39"
local RUN_TARGET = _G.ISAAC_LOCAL_RUN_TARGET or ""
local ROUTE_DIAGNOSTICS = false
local combatLiveAim = nil
local combatAimTargetId, combatAimLockFrame = -1, -10000
local gridRouteControlled = false
local lastReloadPollAt = 0
local fireDirection = Vector(0, 0)
local hazardLaneRoomKey = ""
local hazardLaneTargetId = -1
local hazardLaneAxis = ""
local nativeTearFrame = -10000
local nativeSeenTears = {}
local nativeFireStartFrame = -1
local nativeChargeStartFrame, nativeChargePhase = -1, "idle"
mod.weaponControl = include("weapon_control").new()
local resolvedMove = Vector(0, 0)
local lastRequestedMove = Vector(0, 0)
local lastResolvedMove = Vector(0, 0)
local lastMovementProgress = 0
local lastMovementBlocked = false
local lastMoveResolutionReason = "idle"
local lastPlayerPosition = nil
local transitionError = nil
local transitionGate = "idle"
local transitionDoorDistance = -1
local transitionPhase = "idle"
local transitionAttempt = 0
local doorAttemptRoomIndex = -1
local doorAttemptSlot = -1
local lastObservedRoomIndex = -99999
local lastTransitionSourceRoomIndex = -1
local lastTransitionTargetRoomIndex = -1
local roomEntryFrame = -10000
local backtrackGuardFrames = 180
local currentActionSequence = 0
local deathDetectedFrame = -1
local deathWaitTicks = 0
local deathDetectedAt = -1
local lastDeathStateAt = -10000
local restartAttempted = false
local restartCount = 0
local restartPhase = "alive"
local restartError = nil
local roomVisitSequence = 0
local roomEnteredFrame = -1
local roomClearedFrame = -1
local lastEnemyCount = 0
local damageEventSequence = 0
local damageEvents = {}
local tntBlastGuard = include("tnt_safety").new()
local damageEventLimit = 32
local lastUsedPill = {}
local pillUseResult = "idle"
local utilityButtons = {}
local lastUtilityFrame = -10000
local lastPyroHealFrame = -10000
local pyroHealPending = false
local utilityResult = "idle"
local routeDebug = {}
local routeDebugTrail = {}
local lastTrinketSwapTarget = -1
local trinketSwapResult = "idle"

local function startSeed()
    local ok, seeds = pcall(function() return game:GetSeeds() end)
    if not ok or not seeds then return 0 end
    local seedOk, seed = pcall(function() return seeds:GetStartSeed() end)
    if seedOk and seed then return tonumber(seed) or 0 end
    return 0
end

local function sourceMetadata(source)
    if not source then return -1, -1 end
    local typeOk, sourceType = pcall(function() return source.Type end)
    local variantOk, sourceVariant = pcall(function() return source.Variant end)
    if typeOk and sourceType ~= nil then
        return tonumber(sourceType) or -1, variantOk and (tonumber(sourceVariant) or -1) or -1
    end
    local entityOk, entity = pcall(function() return source.Entity end)
    if not entityOk or not entity then return -1, -1 end
    typeOk, sourceType = pcall(function() return entity.Type end)
    variantOk, sourceVariant = pcall(function() return entity.Variant end)
    return typeOk and (tonumber(sourceType) or -1) or -1,
        variantOk and (tonumber(sourceVariant) or -1) or -1
end

function mod:inputLease(player)
    local frame=game:GetFrameCount()
    local ok,controls=pcall(function() return player.ControlsEnabled end)
    return {response_age_frames=frame-lastActionFrame,
        message_age_ms=Isaac.GetTime()-lastControlMessageAt,
        controller_enabled=controllerEnabled,automatic=automatic,
        awaiting_reply=stateAwaitingReply,pending_action_bytes=#pendingActionPartial,
        controls_enabled=ok and controls or false,
        move_input_age_frames=self.lastAcceptedMoveFrame and frame-self.lastAcceptedMoveFrame or -1,
        shoot_input_age_frames=self.lastAcceptedShootFrame and frame-self.lastAcceptedShootFrame or -1}
end

local function appendDamageEvent(entity, amount, flags, source)
    local player = Isaac.GetPlayer(0)
    if not entity or not entity:ToPlayer() or not player or entity.Index ~= player.Index then return end
    damageEventSequence = damageEventSequence + 1
    local sourceType, sourceVariant = sourceMetadata(source)
    table.insert(damageEvents, {
        id = damageEventSequence,
        frame = game:GetFrameCount(),
        amount = tonumber(amount) or 0,
        flags = tonumber(flags) or 0,
        source_type = sourceType,
        source_variant = sourceVariant,
    })
    while #damageEvents > damageEventLimit do table.remove(damageEvents, 1) end
    -- Preserve native aim and regeneration state at damage time, including
    -- when a later restart has already replaced the live observation file.
    pcall(function()
        local nearby,bombs={},{}
        for _,other in ipairs(Isaac.GetRoomEntities()) do
            if other.Type==(EntityType.ENTITY_BOMB or 4) then
                bombs[#bombs+1]={id=other.Index,variant=other.Variant,x=other.Position.X,y=other.Position.Y,
                    vx=other.Velocity.X,vy=other.Velocity.Y,age=other.FrameCount}
            end
            local npc=other:ToNPC()
            if npc and other.Position:Distance(player.Position)<220 then
                local sprite=other:GetSprite()
                nearby[#nearby+1]={id=other.Index,type=other.Type,hp=other.HitPoints,
                    x=other.Position.X,y=other.Position.Y,active=npc:IsActiveEnemy(false),
                    vulnerable=npc:IsVulnerableEnemy(),champion=npc:GetChampionColorIdx(),
                    animation=sprite and sprite:GetAnimation() or ""}
            end
        end
        Isaac.DebugString("[IsaacJev] DAMAGE_CONTROL "..Json.encode({frame=game:GetFrameCount(),
            seed=game:GetSeeds():GetStartSeed(),action=action.id,
            x=player.Position.X,y=player.Position.Y,vx=player.Velocity.X,vy=player.Velocity.Y,
            mx=resolvedMove.X,my=resolvedMove.Y,ax=fireDirection.X,ay=fireDirection.Y,
            aim_target=combatAimTargetId,charge_phase=nativeChargePhase,
            tear_age=game:GetFrameCount()-nativeTearFrame,enemies=nearby,bombs=bombs,
            flags=tonumber(flags),amount=tonumber(amount),source_type=sourceType,source_variant=sourceVariant,
            stage=game:GetLevel():GetStage(),room=game:GetLevel():GetCurrentRoomIndex(),
            move_reason=lastMoveResolutionReason,route=routeDebug,input_lease=mod:inputLease(player)}))
    end)
end

local function resetRunObservations()
    roomVisitSequence = 0
    roomEnteredFrame = -1
    roomClearedFrame = -1
    lastEnemyCount = 0
    damageEvents = {}
    bombTargetId, bombPlaced, bombPosition, bombRoomKey = -1, false, nil, ""
    bombEntity = nil
    bombPlacementDistance = -1
    bombPlacedFrame = -1
    bombRetreatDirection = Vector(1, 0)
    bombRetreatActive = false
    ghostBombRetreatActive = false
    bombedWallKeys = {}
    bombError = nil
    nativeSeenTears = {}
    nativeTearFrame, nativeFireStartFrame = -10000, -1
    hazardLaneRoomKey, hazardLaneTargetId, hazardLaneAxis = "", -1, ""
end

local function vectorTable(v)
    return { x = math.floor(v.X * 10 + 0.5) / 10, y = math.floor(v.Y * 10 + 0.5) / 10 }
end

local function actualDoorPosition(room, slot)
    local fallback = room:GetDoorSlotPosition(slot)
    local door = room:GetDoor(slot)
    if door then
        local ok, position = pcall(function() return door.Position end)
        if ok and position and position.X and position.Y and position:Distance(fallback) < 180 then
            return position
        end
    end
    return fallback
end

local function doorSlotDirection(slot)
    -- DoorSlot uses the stable order LEFT, UP, RIGHT, DOWN for each door
    -- index. Some room shapes expose a misleading GridEntityDoor.Position;
    -- the slot direction remains reliable for ordinary door input.
    local side = slot % 4
    if side == 0 then return Vector(-1, 0) end
    if side == 1 then return Vector(0, -1) end
    if side == 2 then return Vector(1, 0) end
    return Vector(0, 1)
end

local function entityTable(entity)
    local telegraph = ""
    local spriteOk, sprite = pcall(function() return entity:GetSprite() end)
    if spriteOk and sprite then
        local animationOk, animation = pcall(function() return sprite:GetAnimation() end)
        if animationOk then telegraph = tostring(animation or "") end
    end
    local state = -1
    local npc = entity:ToNPC()
    local isBoss,champion,vulnerable = false,-1,nil
    if npc then
        local stateOk, npcState = pcall(function() return npc.State end)
        if stateOk and npcState then state = tonumber(npcState) or -1 end
        local bossOk, boss = pcall(function() return npc:IsBoss() end)
        isBoss = bossOk and boss == true
        local championOk,color=pcall(function() return npc:GetChampionColorIdx() end)
        if championOk then champion=tonumber(color) or -1 end
        local vulnerableOk,value=pcall(function() return npc:IsVulnerableEnemy() end)
        if vulnerableOk then vulnerable=value==true end
    end
    return {
        id = entity.Index,
        type = entity.Type,
        pos = vectorTable(entity.Position),
        vel = vectorTable(entity.Velocity),
        hp = entity.HitPoints or 0,
        variant = entity.Variant or -1,
        subtype = entity.SubType or -1,
        state = state,
        telegraph = telegraph,
        is_boss = isBoss,
        vulnerable = vulnerable,
        champion_color = champion,
        grid_index = game:GetRoom():GetGridIndex(entity.Position),
    }
end

-- Fireplaces and poop are not hostile NPCs, but they still block the room
-- exit. Keep them as a separate observation class so room:IsClear() cannot
-- accidentally authorize a door while one is still present.
local FIREPLACE_TYPE = EntityType.ENTITY_FIREPLACE or -1
local POOP_TYPE = EntityType.ENTITY_POOP or -1
-- Type 33 contains ordinary, red, blue and other fireplace variants. Blue
-- fire is invulnerable to tears; only the explicit bomb policy may target it.
local BLUE_FIRE_VARIANTS = { [2] = true, [12] = true }
local PURPLE_FIRE_VARIANTS = { [3] = true, [13] = true }
local GRID_FIREPLACE_TYPE = (GridEntityType and GridEntityType.GRID_FIREPLACE) or -1
local GRID_POOP_TYPE = (GridEntityType and GridEntityType.GRID_POOP) or -1
-- Tinted rocks are optional rewards. Ordinary rocks are reported separately;
-- the local policy may bomb one only when its removal opens a needed exit.
local GRID_TINTED_ROCK_TYPE = (GridEntityType and GridEntityType.GRID_ROCKT) or -1
local GRID_ROCK_TYPE = (GridEntityType and GridEntityType.GRID_ROCK) or -1
local GRID_SUPER_TINTED_ROCK_TYPE = (GridEntityType and GridEntityType.GRID_ROCK_SS) or -1
local GRID_TRAPDOOR_TYPE = (GridEntityType and GridEntityType.GRID_TRAPDOOR) or -1
local GRID_SPIKES_TYPE = (GridEntityType and GridEntityType.GRID_SPIKES) or -1
local GRID_SPIKES_ONOFF_TYPE = (GridEntityType and GridEntityType.GRID_SPIKES_ONOFF) or -1
local GRID_PRESSURE_PLATE_TYPE = (GridEntityType and GridEntityType.GRID_PRESSURE_PLATE) or -1
local GRID_TNT_TYPE = (GridEntityType and GridEntityType.GRID_TNT) or -1

local function gridState(grid)
    local ok, state = pcall(function() return grid.State end)
    return ok and tonumber(state) or nil
end

local function redPoopGrid(grid)
    if not grid or grid:GetType() ~= GRID_POOP_TYPE then return false end
    local ok, variant = pcall(function() return grid:GetVariant() end)
    if not ok or tonumber(variant)~=1 then return false end
    local collisionOk,collision=pcall(function() return grid.CollisionClass end)
    if not collisionOk or tonumber(collision)~=0 then return true end
    -- Red rubble regrows under a stationary player. Ordinary routes must
    -- reserve its cell even during the brief non-colliding phase. A closed
    -- pressure-plate puzzle needs the short opening to reach its button;
    -- activating that button converts this room's red barriers to normal poop.
    local room=game and game.GetRoom and game:GetRoom() or nil
    if room and room.IsClear and not room:IsClear() and room.GetGridSize then
        for index=0,room:GetGridSize()-1 do
            local button=room:GetGridEntity(index)
            if button and button:GetType()==GRID_PRESSURE_PLATE_TYPE and gridState(button)==0 then return false end
        end
    end
    return true
end

local function gridEvent(grid, index)
    if not grid then return nil end
    local kind = nil
    local gridType = grid:GetType()
    if gridType == GRID_SPIKES_TYPE or gridType == GRID_SPIKES_ONOFF_TYPE then kind = "spike"
    elseif gridType == GRID_PRESSURE_PLATE_TYPE then kind = "button"
    elseif gridType == GRID_TNT_TYPE then kind = "tnt" end
    if not kind then return nil end
    local state = gridState(grid)
    local active = false
    local triggered = false
    if kind == "spike" then
        -- SpikesOnOff enum is ON=0, OFF=1 (Repentance's SPIKES_ONOFF). The old generic
        -- `state ~= 0` check inverted this room hazard and let pickup paths
        -- cross active spike clusters. Ordinary SPIKES stay dangerous unless
        -- the engine explicitly reports no collision.
        if gridType == GRID_SPIKES_ONOFF_TYPE then
            active = state == nil or state == 0
        else
            -- Walk-through collision is not immunity to spike damage.
            active = true
        end
    elseif kind == "button" then
        -- Repentance pressure plates use state 3 (trigger) or 4 (reward)
        -- after being pressed. State 1/2 are still pending transitions.
        triggered = state ~= nil and state >= 3
        active = not triggered
    elseif kind == "tnt" then
        local collisionOk, collision = pcall(function() return grid.CollisionClass end)
        active = (state == nil or state < 2) and (not collisionOk or tonumber(collision) ~= 0)
    end
    return { kind = kind, id = -100000 - index, pos = vectorTable(grid.Position),
        grid_index = index, state = state or -1, active = active, triggered = triggered,
        timed = gridType == GRID_SPIKES_ONOFF_TYPE }
end

local function currentDimension(level)
    local descriptor = level:GetCurrentRoomDesc()
    if not descriptor or not GetPtrHash then return 0 end
    local okIndex, safeIndex = pcall(function() return descriptor.SafeGridIndex end)
    if not okIndex or safeIndex == nil then return 0 end
    for dimension = 0, 2 do
        local ok, same = pcall(function()
            local other = level:GetRoomByIdx(safeIndex, dimension)
            return other and GetPtrHash(descriptor) == GetPtrHash(other)
        end)
        if ok and same then return dimension end
    end
    return 0
end

local function canonicalRoomIndex(level, index)
    if index == nil then index = level:GetCurrentRoomIndex() end
    if index < 0 then return index end
    local descriptor = level:GetRoomByIdx(index, currentDimension(level))
    return descriptor and descriptor.SafeGridIndex or index
end

local function currentRoomKey()
    local level = game:GetLevel()
    return table.concat({ tostring(startSeed()), tostring(level:GetStage()),
        tostring(level:GetStageType()), tostring(currentDimension(level)),
        tostring(canonicalRoomIndex(level)) }, ":")
end

local function bombStillLive()
    if not bombPlaced or bombRoomKey ~= currentRoomKey()
        or game:GetFrameCount() - bombPlacedFrame >= 120 then return false end
    if game:GetFrameCount() - bombPlacedFrame < 2 then return true end
    local ok, exists = pcall(function() return bombEntity and bombEntity:Exists() end)
    return ok and exists == true
end

local function weaponKind(player)
    if not WeaponType then return "unknown", false end
    local kinds = {
        { "WEAPON_BRIMSTONE", "brimstone" }, { "WEAPON_LASER", "laser" },
        { "WEAPON_KNIFE", "knife" }, { "WEAPON_BOMBS", "bombs" },
        { "WEAPON_ROCKETS", "rockets" }, { "WEAPON_MONSTROS_LUNGS", "monstros_lungs" },
        { "WEAPON_LUDOVICO_TECHNIQUE", "ludovico" }, { "WEAPON_TECH_X", "tech_x" },
        { "WEAPON_BONE", "bone" }, { "WEAPON_SPIRIT_SWORD", "spirit_sword" },
        { "WEAPON_FETUS", "fetus" },
    }
    for _, entry in ipairs(kinds) do
        local value = WeaponType[entry[1]]
        if value then
            local ok, present = pcall(function() return player:HasWeaponType(value) end)
            if ok and present then return entry[2], true end
        end
    end
    local tears = WeaponType.WEAPON_TEARS
    if tears then
        local ok, present = pcall(function() return player:HasWeaponType(tears) end)
        if ok and present then return "tear", true end
    end
    return "unknown", false
end

local function chargeReleaseFrames(player, weapon)
    local profile=mod.weaponControl:profile(player,weapon)
    return (profile.mode=="release" or profile.mode=="melee") and profile.charge or nil
end

local function hazardKind(entity)
    if entity.Type == FIREPLACE_TYPE then
        if BLUE_FIRE_VARIANTS[tonumber(entity.Variant) or -1] then return "blue_fire" end
        if PURPLE_FIRE_VARIANTS[tonumber(entity.Variant) or -1] then return "purple_fire" end
        return "fire"
    end
    if entity.Type == POOP_TYPE then return "poop" end
    return nil
end

local function trackingBombInfo(entity, player)
    -- Observe live explosives independently of placement history. Reloading or
    -- reconnecting must not erase a bomb which is still in the room.
    if not entity or not player then return nil end
    local entityType = entity.Type
    local isBomb = entityType == (EntityType.ENTITY_BOMB or 4)
    if not isBomb and entityType ~= (EntityType.ENTITY_EFFECT or 1000) then return nil end
    if isBomb then
        if player.HasCollectible and player:HasCollectible(223) then return nil end
        local multiplier = 1
        local ok, bomb = pcall(function() return entity:ToBomb() end)
        if ok and bomb then multiplier = tonumber(bomb.RadiusMultiplier) or 1 end
        local radius = 100 * math.max(1, multiplier) + (tonumber(player.Size) or 10) + 15
        if entity.Position:Distance(player.Position) > radius + 65 then return nil end
        return {id=entity.Index, kind="armed_bomb", type=entityType,
            pos=vectorTable(entity.Position), vel=vectorTable(entity.Velocity or Vector(0,0)),
            radius=radius, variant=entity.Variant or -1, subtype=entity.SubType or -1,
            animation="", state=-1}
    end
    local ownerOk, owner = pcall(function() return entity.SpawnerEntity end)
    if ownerOk and owner and owner.Index == player.Index then return nil end
    local parentOk, parent = pcall(function() return entity.Parent end)
    if parentOk and parent and parent.Index == player.Index then return nil end
    local animation = ""
    local spriteOk, sprite = pcall(function() return entity:GetSprite() end)
    if spriteOk and sprite then
        local animationOk, current = pcall(function() return sprite:GetAnimation() end)
        if animationOk then animation = string.lower(tostring(current or "")) end
    end
    local ghostAnimation = string.find(animation, "ghost", 1, true)
        or string.find(animation, "homing", 1, true)
        or string.find(animation, "chase", 1, true)
        or string.find(animation, "follow", 1, true)
    if not isBomb and not ghostAnimation then return nil end
    local delta = player.Position - entity.Position
    local distance = delta:Length()
    local velocity = entity.Velocity or Vector(0, 0)
    local closing = delta.X * velocity.X + delta.Y * velocity.Y > 0.25
    -- A non-player bomb is only promoted when it is actually moving toward
    -- Isaac. Ghost effects with a recognizable animation use the same test,
    -- which avoids treating decorative or expired effects as threats.
    if not closing or distance > 300 then return nil end
    local radius = math.max(34, math.min(62, (tonumber(entity.Size) or 20) + (tonumber(player.Size) or 10) + 18))
    return {
        id = entity.Index, kind = "ghost_bomb", type = entityType,
        pos = vectorTable(entity.Position), vel = vectorTable(velocity),
        radius = radius, variant = entity.Variant or -1, subtype = entity.SubType or -1,
        animation = animation, state = -1,
    }
end

local function nearestTrackingBomb(player)
    local nearest, nearestDistance = nil, nil
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        local threat = trackingBombInfo(entity, player)
        if threat then
            local distance = entity.Position:Distance(player.Position)
            if not nearestDistance or distance < nearestDistance then
                nearest, nearestDistance = threat, distance
            end
        end
    end
    return nearest
end

local function bombOnlyFireKind(kind)
    return kind == "blue_fire" or kind == "purple_fire"
end

local function isRetractedSpikeTrap(entity)
    if entity.Type~=(EntityType.ENTITY_POKY or 44) or entity.CollisionDamage~=0
        or not game:GetRoom():IsClear() then return false end
    local npc=entity.ToNPC and entity:ToNPC() or entity
    if not npc or npc.State~=16 or not entity.GetSprite then return false end
    local sprite=entity:GetSprite()
    return sprite and sprite:GetAnimation()=="No-Spikes"
        and (not entity.Velocity or entity.Velocity:Length()<.1)
end

local function isMovingSpikeTrap(entity)
    if isRetractedSpikeTrap(entity) then return false end
    -- Poky/Slide share one entity type; Wall Hugger is another. Both can be
    -- reported as active NPCs despite being invulnerable room machinery.
    return entity.Type == (EntityType.ENTITY_POKY or 44)
        or entity.Type == (EntityType.ENTITY_WALL_HUGGER or 218)
        or (entity.Type == (EntityType.ENTITY_DEATHS_HEAD or 212) and (entity.Variant or 0)==0)
        -- Peep's detached eyes keep the boss's HP but cannot be damaged.
        -- They remain swept contact hazards, without attracting firing routes.
        or (entity.Type == (EntityType.ENTITY_PEEP or 68) and entity.Variant==10)
end

local function isStoneTrap(entity)
    return entity.Type == (EntityType.ENTITY_STONEHEAD or 42)
        or entity.Type == (EntityType.ENTITY_STONE_EYE or 201)
        or entity.Type == (EntityType.ENTITY_CONSTANT_STONE_SHOOTER or 202)
        or entity.Type == (EntityType.ENTITY_BRIMSTONE_HEAD or 203)
        or entity.Type == (EntityType.ENTITY_GAPING_MAW or 235)
        or entity.Type == (EntityType.ENTITY_BROKEN_GAPING_MAW or 236)
end

local function liveHazardKind(entity)
    local kind = hazardKind(entity)
    if not kind then return nil end
    local npc = entity:ToNPC()
    if npc then
        -- Fireplaces are not hostile NPCs on all Repentance builds, so
        -- IsActiveEnemy alone cannot be used as a whitelist. Use the full
        -- lifecycle below (dead/HP/sprite) to detect extinction.
        -- Lit fireplaces can report both NPC active predicates as false.
        -- Their native HP/death/animation lifecycle determines extinction.
        local deadOk, dead = pcall(function() return npc:IsDead() end)
        if deadOk and dead then return nil end
        local hpOk, hp = pcall(function() return entity.HitPoints end)
        if hpOk and hp and hp <= 0 then return nil end

        -- Repentance builds use several names for the post-hit fireplace
        -- animation. They can still report IsActive for a few frames, so
        -- explicitly exclude those visual lifecycle states as well.
        local spriteOk, sprite = pcall(function() return entity:GetSprite() end)
        if spriteOk and sprite then
            local animationOk, animation = pcall(function() return sprite:GetAnimation() end)
            local name = animationOk and string.lower(tostring(animation or "")) or ""
            if string.find(name, "death", 1, true)
                or string.find(name, "destroy", 1, true)
                or string.find(name, "poof", 1, true)
                or string.find(name, "dissapear", 1, true)
                or string.find(name, "disappear", 1, true)
                or string.find(name, "extingu", 1, true)
                or string.find(name, "off", 1, true)
                or string.find(name, "nofire", 1, true)
                or string.find(name, "no_fire", 1, true)
                or string.find(name, "unlit", 1, true)
            then
                return nil
            end
            for _, animationName in ipairs({ "Death", "Destroy", "Poof", "Dissapear", "Dissapear2", "Dissapear3", "Disappear", "Disappear2", "Disappear3", "Extinguish", "Off", "NoFire", "NoFire2", "Unlit" }) do
                local finishedOk, finished = pcall(function() return sprite:IsFinished(animationName) end)
                local playingOk, playing = pcall(function() return sprite:IsPlaying(animationName) end)
                if (finishedOk and finished) or (playingOk and playing) then return nil end
            end
        end
    end
    return kind
end

local function gridHazardKind(grid)
    if not grid then return nil end
    local gridType = grid:GetType()
    if gridType == GRID_FIREPLACE_TYPE then
        local ok, variant = pcall(function() return grid:GetVariant() end)
        variant = ok and tonumber(variant) or -1
        if PURPLE_FIRE_VARIANTS[variant] then return "purple_fire" end
        if BLUE_FIRE_VARIANTS[variant] then return "blue_fire" end
        return "fire"
    end
    if gridType == GRID_POOP_TYPE then return redPoopGrid(grid) and "red_poop" or "poop" end
    if gridType == GRID_TINTED_ROCK_TYPE or gridType == GRID_SUPER_TINTED_ROCK_TYPE then return "xrock" end
    if gridType == GRID_ROCK_TYPE then return "passage_rock" end
    return nil
end

local function liveGridHazardKind(grid)
    local kind = gridHazardKind(grid)
    if not kind then return nil end
    local collisionOk, collision = pcall(function() return grid.CollisionClass end)
    -- Repentance exposes this as an integer on some builds and an enum value
    -- on others. Zero is COLLISION_NONE in both representations.
    if collisionOk and tonumber(collision) == 0 then return nil end
    local spriteOk, sprite = pcall(function() return grid:GetSprite() end)
    if spriteOk and sprite then
        local animationOk, animation = pcall(function() return sprite:GetAnimation() end)
        local name = animationOk and string.lower(tostring(animation or "")) or ""
        if (kind == "fire" or bombOnlyFireKind(kind)) and (string.find(name, "dissapear", 1, true)
            or string.find(name, "disappear", 1, true)) then return nil end
        for _, animation in ipairs({ "Death", "Destroy", "Poof", "NoFire", "NoFire2", "Unlit", "Off" }) do
            local finishedOk, finished = pcall(function() return sprite:IsFinished(animation) end)
            local playingOk, playing = pcall(function() return sprite:IsPlaying(animation) end)
            if (finishedOk and finished) or (playingOk and playing) then return nil end
        end
    end
    return kind
end

local function hazardTable(entity, kind)
    local spriteName = ""
    local npcState = -1
    local spriteOk, sprite = pcall(function() return entity:GetSprite() end)
    if spriteOk and sprite then
        local animationOk, animation = pcall(function() return sprite:GetAnimation() end)
        if animationOk then spriteName = tostring(animation or "") end
    end
    local npc = entity:ToNPC()
    if npc then
        local stateOk, state = pcall(function() return npc.State end)
        if stateOk and state then npcState = tonumber(state) or -1 end
    end
    return {
        id = entity.Index, type = entity.Type, kind = kind,
        pos = vectorTable(entity.Position), vel = vectorTable(entity.Velocity),
        grid_index = game:GetRoom():GetGridIndex(entity.Position),
        hp = entity.HitPoints or 0, destructible = true, animation = spriteName,
        requires_bomb = bombOnlyFireKind(kind),
        variant = entity.Variant or -1, subtype = entity.SubType or -1, state = npcState,
        telegraph = spriteName,
    }
end

local function gridHazardTable(grid, gridIndex, kind)
    local animation = ""
    local variantOk, variant = pcall(function() return grid:GetVariant() end)
    variant = variantOk and tonumber(variant) or -1
    local spriteOk, sprite = pcall(function() return grid:GetSprite() end)
    if spriteOk and sprite then
        local animationOk, current = pcall(function() return sprite:GetAnimation() end)
        if animationOk then animation = tostring(current or "") end
    end
    return {
        id = -100000 - gridIndex, type = grid:GetType(), kind = kind,
        pos = vectorTable(grid.Position), vel = { x = 0, y = 0 },
        hp = 0, destructible = true, requires_bomb = kind == "xrock" or kind == "passage_rock" or bombOnlyFireKind(kind), grid_index = gridIndex, animation = animation,
        variant = variant,
    }
end

local function ignoredPickup(id)
    for _, value in ipairs(action.ignoredPickupIds or {}) do
        if tonumber(value) == id then return true end
    end
    return false
end

local function collectLayout(room, level)
    local descriptor = level:GetCurrentRoomDesc()
    local roomIndex = canonicalRoomIndex(level)
    local blocked, doors, gridEvents, dangerGridIndices, bombWalls = {}, {}, {}, {}, {}
    local shotBlocked = {}
    local function roomTypeName(data)
        if not data then return "unknown" end
        local roomType = data.Type
        local names = {}
        local function add(name, label)
            local value = RoomType[name]
            if value ~= nil then names[value] = label end
        end
        add("ROOM_DEFAULT", "default")
        add("ROOM_SHOP", "shop")
        add("ROOM_TREASURE", "treasure")
        add("ROOM_BOSS", "boss")
        add("ROOM_SECRET", "secret")
        add("ROOM_SUPERSECRET", "super_secret")
        add("ROOM_CURSE", "curse")
        add("ROOM_SACRIFICE", "sacrifice")
        add("ROOM_CHALLENGE", "challenge")
        add("ROOM_LIBRARY", "library")
        add("ROOM_DEVIL", "devil")
        add("ROOM_ANGEL", "angel")
        add("ROOM_DICE", "dice")
        add("ROOM_PLANETARIUM", "planetarium")
        return names[roomType] or "special"
    end
    for index = 0, room:GetGridSize() - 1 do
        if room:GetGridPath(index) >= 1000 then table.insert(blocked, index) end
        if room:GetGridCollision(index) >= GridCollisionClass.COLLISION_OBJECT then table.insert(shotBlocked, index) end
        local grid = room:GetGridEntity(index)
        local event = gridEvent(grid, index)
        if event then
            table.insert(gridEvents, event)
            if event.kind == "spike" and event.active then table.insert(dangerGridIndices, index) end
            if event.kind == "tnt" and event.active then table.insert(dangerGridIndices, index) end
        end
        local gridHazard = liveGridHazardKind(grid)
        if gridHazard == "fire" or bombOnlyFireKind(gridHazard) or redPoopGrid(grid) then table.insert(dangerGridIndices, index) end
    end
    for slot = 0, 7 do
        local door = room:GetDoor(slot)
        if door then
            local targetIndex = door.TargetRoomIndex or -1
            local target = targetIndex >= 0 and level:GetRoomByIdx(targetIndex) or nil
            local targetData = target and target.Data or nil
            if not targetData then
                local kindOk, kind = pcall(function() return door.TargetRoomType end)
                if kindOk and kind ~= nil then targetData = { Type = kind } end
            end
            local lockKnown, locked = false, false
            local lockOk, lockValue = pcall(function() return door:IsLocked() end)
            if lockOk and type(lockValue) == "boolean" then lockKnown, locked = true, lockValue end
            local openKnown, open = false, false
            local openOk, openValue = pcall(function() return door:IsOpen() end)
            if openOk and type(openValue) == "boolean" then openKnown, open = true, openValue end
            table.insert(doors, {
                slot = slot,
                pos = vectorTable(actualDoorPosition(room, slot)),
                target_room_index = canonicalRoomIndex(level, targetIndex),
                target_is_boss = targetData and targetData.Type == RoomType.ROOM_BOSS or false,
                target_clear = target and target.Clear or false,
                target_room_type = roomTypeName(targetData),
                door_locked = locked,
                door_lock_known = lockKnown,
                door_open = open,
                door_open_known = openKnown,
                grid_index = room:GetGridIndex(actualDoorPosition(room, slot)),
            })
        end
    end
    -- Only infer neighboring hidden rooms for 1x1 rooms; larger room shapes
    -- need shape-specific grid offsets and are deliberately skipped.
    if room:GetRoomShape() == RoomShape.ROOMSHAPE_1x1 then
        local offsets = { -1, -13, 1, 13 }
        local dimension = currentDimension(level)
        for slot = 0, 3 do
            local targetIndex = roomIndex + offsets[slot + 1]
            local sameRow = slot ~= 0 and slot ~= 2 or math.floor(roomIndex / 13) == math.floor(targetIndex / 13)
            if targetIndex >= 0 and targetIndex < 169 and sameRow and room:IsDoorSlotAllowed(slot)
                and room:GetGridWidth() <= 15 and room:GetGridHeight() <= 9 then
                local target = level:GetRoomByIdx(targetIndex, dimension)
                local targetType = target and target.Data and target.Data.Type or -1
                if targetType == RoomType.ROOM_SECRET or targetType == RoomType.ROOM_SUPERSECRET then
                    local door = room:GetDoor(slot)
                    local open = door and door:IsOpen()
                    local position = actualDoorPosition(room, slot)
                    local inward = room:GetCenterPos() - position
                    if inward:Length() > 0 then
                        local site = position + inward:Normalized() * 60
                        local siteIndex = room:GetGridIndex(site)
                        if not open and room:IsPositionInRoom(site, 12) and room:GetGridPath(siteIndex) < 1000 then
                            table.insert(bombWalls, { slot = slot, pos = vectorTable(position), site = vectorTable(site),
                                grid_index = siteIndex, room_type = targetType == RoomType.ROOM_SECRET and "secret" or "super_secret",
                                bombed = bombedWallKeys[currentRoomKey() .. ":" .. tostring(slot)] == true })
                        end
                    end
                end
            end
        end
    end
    return {
        room_index = roomIndex, room_type = roomTypeName(descriptor.Data),
        is_boss = descriptor.Data and descriptor.Data.Type == RoomType.ROOM_BOSS or false,
        grid_width = room:GetGridWidth(), grid_height = room:GetGridHeight(), blocked = blocked, shot_blocked = shotBlocked, doors = doors,
        grid_events = gridEvents, danger_grid_indices = dangerGridIndices, bomb_walls = bombWalls,
    }
end

function mod:keepProgressionActive(player,subtype)
    if RUN_TARGET~="satan" or not player.GetActiveItem then return false end
    local held=player:GetActiveItem(0)
    if held==subtype or (held~=33 and held~=84) then return false end
    local stage=game:GetLevel():GetStage()
    if stage>8 then return false end
    local config=Isaac.GetItemConfig():GetCollectible(subtype)
    if not config or config.Type~=((ItemType and ItemType.ITEM_ACTIVE) or 3) then return false end
    -- The owned shovel provides a normal Sheol entrance even before It Lives.
    -- Keep it for that route; it also takes priority over the Mom/Heart Bible.
    if held==84 then return true end
    if subtype==84 then return false end
    local room=game:GetRoom()
    if stage==8 and room:GetType()==RoomType.ROOM_BOSS and room:IsClear() then return false end
    return true
end

local function pickupTable(entity)
    -- This trinket periodically stomps the player. Refuse it rather than
    -- treating every trinket as a beneficial upgrade, including golden ones.
    if entity.Variant == PickupVariant.PICKUP_TRINKET
        and entity.SubType % 32768 == (TrinketType.TRINKET_MOMS_TOENAIL or 16) then return nil end
    local pickup = entity:ToPickup()
    local collectible = entity.Variant == PickupVariant.PICKUP_COLLECTIBLE
    -- After a collectible is taken, Repentance can leave the stone pedestal as
    -- an ENTITY_PICKUP with subtype 0 for several frames. It is scenery, not a
    -- second item target, so never expose it to Python navigation.
    if collectible and (tonumber(entity.SubType) or 0) <= 0 then return nil end
    -- These change aiming geometry beyond the current cardinal tear policy.
    -- The observed Wiz pickup preceded the lethal Globin encounter: do not
    -- accept a build which the movement/firing planner cannot yet aim.
    if collectible and (entity.SubType == 168 or entity.SubType == 329 or entity.SubType == 358
        or entity.SubType == 233 or entity.SubType == 394 or entity.SubType == 273) then return nil end
    -- Glass Cannon adds two whole hearts of damage when it breaks, including
    -- while merely held. Prefer survival and a safer normal active swap.
    if collectible and (entity.SubType == 352 or entity.SubType == 474) then return nil end
    if collectible and entity.SubType == 316 and not Isaac.GetPlayer(0):HasCollectible(260) then return nil end
    if collectible and mod:keepProgressionActive(Isaac.GetPlayer(0),entity.SubType) then return nil end
    local quality, name, kind = 0, "pickup", "other"
    local function variant(name)
        return PickupVariant[name]
    end
    local chestNames = {
        PICKUP_CHEST = "chest",
        PICKUP_LOCKEDCHEST = "locked_chest",
        PICKUP_REDCHEST = "red_chest",
        PICKUP_BOMBCHEST = "bomb_chest",
        PICKUP_SPIKED_CHEST = "spiked_chest",
        PICKUP_SPIKEDCHEST = "spiked_chest",
        PICKUP_ETERNALCHEST = "eternal_chest",
        PICKUP_MIMICCHEST = "mimic_chest",
        PICKUP_OLDCHEST = "old_chest",
        PICKUP_WOODENCHEST = "wooden_chest",
        PICKUP_HAUNTEDCHEST = "haunted_chest",
    }
    for variantName, chestKind in pairs(chestNames) do
        local chestVariant = variant(variantName)
        if chestVariant and entity.Variant == chestVariant then
            kind, name = chestKind, chestKind
            collectible = true
            quality = 1
            break
        end
    end
    if collectible and kind == "other" then
        kind = "collectible"
        local config = Isaac.GetItemConfig():GetCollectible(entity.SubType)
        if config then
            quality = config.Quality or 0
            name = config.Name or "collectible"
        end
    elseif entity.Variant == PickupVariant.PICKUP_BIGCHEST then
        kind, name = "ending_chest", "ending chest"
    elseif entity.Variant == PickupVariant.PICKUP_TROPHY then
        kind, name = "ending_trophy", "ending trophy"
    elseif entity.Variant == PickupVariant.PICKUP_KEY then
        kind, name = "key", "key"
    elseif entity.Variant == PickupVariant.PICKUP_COIN then
        kind, name = "coin", "coin"
    elseif entity.Variant == PickupVariant.PICKUP_BOMB then
        kind, name = "bomb", "bomb"
    elseif entity.Variant == PickupVariant.PICKUP_HEART then
        local subtype = entity.SubType
        local full = HeartSubType and HeartSubType.HEART_FULL or 1
        local half = HeartSubType and HeartSubType.HEART_HALF or 2
        local soul = HeartSubType and HeartSubType.HEART_SOUL or 3
        local eternal = HeartSubType and HeartSubType.HEART_ETERNAL or 4
        local double = HeartSubType and HeartSubType.HEART_DOUBLEPACK or 5
        local black = HeartSubType and HeartSubType.HEART_BLACK or 6
        local golden = HeartSubType and HeartSubType.HEART_GOLDEN or 7
        local halfSoul = HeartSubType and HeartSubType.HEART_HALF_SOUL or 8
        local scared = HeartSubType and HeartSubType.HEART_SCARED or 9
        local blended = HeartSubType and HeartSubType.HEART_BLENDED or 10
        local bone = HeartSubType and HeartSubType.HEART_BONE or 11
        local rotten = HeartSubType and HeartSubType.HEART_ROTTEN or 12
        if subtype == soul then kind, name = "soul_heart", "soul heart"
        elseif subtype == black then kind, name = "black_heart", "black heart"
        elseif subtype == eternal then kind, name = "eternal_heart", "eternal heart"
        elseif subtype == golden then kind, name = "golden_heart", "golden heart"
        elseif subtype == bone then kind, name = "bone_heart", "bone heart"
        elseif subtype == halfSoul then kind, name = "half_soul_heart", "half soul heart"
        elseif subtype == scared then kind, name = "scared_heart", "scared heart"
        elseif subtype == blended then kind, name = "blended_heart", "blended heart"
        elseif subtype == rotten then kind, name = "rotten_heart", "rotten heart"
        elseif subtype == half then kind, name = "red_half_heart", "half red heart"
        elseif subtype == double then kind, name = "red_double_heart", "double red heart"
        elseif subtype == full then kind, name = "red_heart", "red heart"
        else kind, name = "heart", "heart" end
    elseif ((variant("PICKUP_CARD") and entity.Variant == variant("PICKUP_CARD")) or (variant("PICKUP_TAROTCARD") and entity.Variant == variant("PICKUP_TAROTCARD"))) then
        kind, name = "card", "card"
    elseif variant("PICKUP_PILL") and entity.Variant == variant("PICKUP_PILL") then
        kind, name = "pill", "pill"
    elseif variant("PICKUP_GRAB_BAG") and entity.Variant == variant("PICKUP_GRAB_BAG") then
        kind, name = "grab_bag", "grab bag"
    elseif variant("PICKUP_TRINKET") and entity.Variant == variant("PICKUP_TRINKET") then
        kind, name = "trinket", "trinket"
        local config = Isaac.GetItemConfig():GetTrinket(entity.SubType)
        if config and config.Name then name = config.Name end
    end
    return { id = entity.Index, pos = vectorTable(entity.Position), grid_index = game:GetRoom():GetGridIndex(entity.Position), subtype = entity.SubType, price = pickup.Price or 0,
        quality = quality, name = name, kind = kind, is_collectible = collectible }
end

local function isCombatEnemy(entity)
    -- Fireplaces/poop have NPC-like entities on some rooms, but they are
    -- obstacles, never combat targets. Keep them in the hazard channel even
    -- when the engine reports them as active enemies.
    -- Eternal Flies cannot be shot while orbiting their host. They remain
    -- contact hazards below, but must not override the engine's clear flag.
    if entity.Type == (EntityType.ENTITY_ETERNALFLY or 96)
        or entity.Type == (EntityType.ENTITY_FROZEN_ENEMY or 963)
        or entity.Type==(EntityType.ENTITY_POKY or 44)
        or hazardKind(entity) or isMovingSpikeTrap(entity) or isStoneTrap(entity)
        -- Gemini's cord pieces copy HP but are neither targets nor bodies.
        or (entity.Type==(EntityType.ENTITY_GEMINI or 79) and entity.Variant==20)
        or (entity.Type==(EntityType.ENTITY_SWINGER or 216) and entity.Variant==10)
        or trackingBombInfo(entity, Isaac.GetPlayer(0)) then return false end
    local npc = entity:ToNPC()
    -- IsVulnerableEnemy also includes several non-hostile NPCs (for example
    -- props and friendly entities). Only active, non-friendly hostile NPCs
    -- may keep the room in combat or influence aim/navigation.
    -- X rocks can release spiders into a room whose native clear flag stays
    -- true. Keep this specific hostile type even if IsActiveEnemy lags behind.
    return npc and (npc:IsActiveEnemy(false) or entity.Type == EntityType.ENTITY_SPIDER
        or entity.Type == (EntityType.ENTITY_GLOBIN or 24))
        and not npc:HasEntityFlags(EntityFlag.FLAG_FRIENDLY)
        and entity.HitPoints > 0
end

local function hasCombatEnemy()
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if isCombatEnemy(entity) then return true end
    end
    return false
end

local function bossExitInfo(room)
    if not room:IsClear() or GRID_TRAPDOOR_TYPE < 0 then
        return false, { x = 0, y = 0 }, -1
    end
    for index = 0, room:GetGridSize() - 1 do
        local grid = room:GetGridEntity(index)
        if grid then
            local ok, gridType = pcall(function() return grid:GetType() end)
            if ok and gridType == GRID_TRAPDOOR_TYPE then
                return true, vectorTable(grid.Position), index
            end
        end
    end
    return false, { x = 0, y = 0 }, -1
end

local function dangerousCreep(entity)
    if entity.Type ~= EntityType.ENTITY_EFFECT then return false end
    local variant = entity.Variant
    local hostile = variant == EffectVariant.CREEP_RED or variant == EffectVariant.CREEP_GREEN
        or variant == EffectVariant.CREEP_YELLOW or variant == EffectVariant.CREEP_BLACK
        or variant == EffectVariant.CREEP_BROWN
    if not hostile then return false end
    local ok, friendly = pcall(function() return EntityEffect.IsPlayerCreep(variant) end)
    return not (ok and friendly)
end

local function contactObstacle(entity, player)
    if isRetractedSpikeTrap and isRetractedSpikeTrap(entity) then
        -- Cleared Pokys have no damage but retain their physical bodies.
        -- Reserve only that body, without live moving-spike danger padding.
        return (entity.Size or 16)+(player.Size or 10)+3,"retracted_spike"
    end
    -- Entering an offer room must not brush against an unselected health deal.
    if entity.Type == (EntityType.ENTITY_PICKUP or 5)
        and entity.Variant == (PickupVariant.PICKUP_COLLECTIBLE or 100)
        and entity.ToPickup then
        local pickup = entity:ToPickup()
        if pickup and pickup.Price and pickup.Price < 0 and pickup.Price ~= -1000
            and (not action or action.id ~= "take_item_" .. tostring(entity.Index)) then
            return math.max(32, (entity.Size or 12) + (player.Size or 10) + 10), "unselected_health_deal"
        end
    end
    -- Avoid brushing the ending chest while heading to a natural Sheol route.
    if RUN_TARGET == "satan" and entity.Type == (EntityType.ENTITY_PICKUP or 5)
        and entity.Variant == (PickupVariant.PICKUP_BIGCHEST or 340)
        and game:GetLevel():GetStage() == 8 then
        if player.GetCard and player:GetCard(0)==(Card.CARD_JOKER or 31) then return 48,"ending_chest" end
        if player.GetActiveItem and player:GetActiveItem(0)==84 and player.GetActiveCharge then
            local config=Isaac.GetItemConfig():GetCollectible(84)
            if config and config.MaxCharges>0 and player:GetActiveCharge(0)>=config.MaxCharges then
                return 48,"ending_chest"
            end
        end
        local room = game:GetRoom()
        for slot=0,7 do
            local door=room:GetDoor(slot)
            if door and door:IsOpen() and door.TargetRoomType == RoomType.ROOM_DEVIL then
                return 48, "ending_chest"
            end
        end
    end
    -- Empty item pedestals still push the player even though GetGridPath
    -- reports their tile as walkable. Route around the remaining pedestal.
    if entity.Type == (EntityType.ENTITY_PICKUP or 5)
        and entity.Variant == (PickupVariant.PICKUP_COLLECTIBLE or 100)
        and (entity.SubType == 0 or entity.SubType == 168 or entity.SubType == 329 or entity.SubType == 358
            or entity.SubType == 233 or entity.SubType == 394 or entity.SubType == 352 or entity.SubType == 474
            or entity.SubType == 273
            or (mod and mod.keepProgressionActive and mod:keepProgressionActive(player,entity.SubType))
            or (entity.SubType==316 and not (player.HasCollectible and player:HasCollectible(260)))) then
        return math.max(30, (tonumber(entity.Size) or 12) + (tonumber(player.Size) or 10) + 8),
            entity.SubType == 0 and "empty_pedestal" or "unsupported_pedestal"
    end
    if entity.Type == (EntityType.ENTITY_SLOT or 6) then
        return math.max(32, math.min(48, (entity.Size or 16) + (player.Size or 10) + 8)), "interactive_slot"
    end
    if entity.Type == EntityType.ENTITY_EFFECT
        and entity.Variant == (EffectVariant.MOM_FOOT_STOMP or 29) then return 90, "stomp" end
    if (entity.Variant or 0)==10
        and (entity.Type==(EntityType.ENTITY_SATAN or 84) or entity.Type==(EntityType.ENTITY_MOM or 45)) then
        local npc=entity.ToNPC and entity:ToNPC() or entity
        local state=npc and npc.State or -1
        if state==7 or (entity.Type==(EntityType.ENTITY_MOM or 45) and state==6) then
            return 90,"stomp"
        end
    end
    return nil
end

local function playerIsDead(player)
    local ok, dead = pcall(function() return player:IsDead() end)
    if ok and dead then return true end
    return (player:GetHearts() + player:GetSoulHearts() + player:GetBoneHearts() * 2) <= 0
end

local function handleDeathAndRestart(player)
    if not player then return false end
    if not playerIsDead(player) then
        if restartPhase ~= "alive" then
            restartPhase = "alive"
            deathDetectedFrame = -1
            deathWaitTicks = 0
            deathDetectedAt = -1
            restartAttempted = false
            restartError = nil
            automatic = not manualOverride
            lastStateFrame = -10000
            lastLayoutRoom = -99999
            lastLayout = nil
            lastObservedRoomIndex = -99999
            lastPlayerPosition = nil
            lastTransitionSourceRoomIndex = -1
            lastTransitionTargetRoomIndex = -1
            roomEntryFrame = -10000
            action = { id = "", move = Vector(0, 0), shoot = Vector(0, 0), mode = "wait", target = "", reason = "new run starting", sourceRoomIndex = -1 }
            lastActionFrame = -10000
            resetRunObservations()
            lastUsedPill = {}
            pillUseResult = "idle"
            lastTrinketSwapTarget = -1
            trinketSwapResult = "idle"
        end
        return false
    end
    if deathDetectedFrame < 0 then
        deathDetectedFrame = game:GetFrameCount()
        deathDetectedAt = Isaac.GetTime()
        deathWaitTicks = 0
        restartPhase = "death_wait"
        restartAttempted = false
        restartError = nil
        automatic = false
        action = { id = "dead_wait", move = Vector(0, 0), shoot = Vector(0, 0), mode = "wait", target = "", reason = "dead; waiting to restart", sourceRoomIndex = -1 }
        resolvedMove = Vector(0, 0)
    end
    deathWaitTicks = deathWaitTicks + 1
    -- The game stops simulation updates on the death screen. A render-time
    -- clock and fresh controller messages keep restart independent of focus
    -- and prevent an observing/disconnected controller from restarting a run.
    if not restartAttempted and controllerEnabled and not manualOverride
        and Isaac.GetTime() - lastControlMessageAt < 1500
        and Isaac.GetTime() - deathDetectedAt >= 2000 then
        restartAttempted = true
        restartPhase = "restarting"
        local ok, err = pcall(function()
            Isaac.ExecuteCommand("restart")
        end)
        if ok then
            restartCount = restartCount + 1
            restartPhase = "waiting_new_run"
            lastActionFrame = -10000
            lastStateFrame = -10000
            lastLayoutRoom = -99999
            lastLayout = nil
            lastObservedRoomIndex = -99999
            lastPlayerPosition = nil
            lastTransitionSourceRoomIndex = -1
            lastTransitionTargetRoomIndex = -1
            roomEntryFrame = -10000
            action = { id = "", move = Vector(0, 0), shoot = Vector(0, 0), mode = "wait", target = "", reason = "restart requested", sourceRoomIndex = -1 }
            resetRunObservations()
            lastUsedPill = {}
            pillUseResult = "idle"
            lastTrinketSwapTarget = -1
            trinketSwapResult = "idle"
        else
            restartError = tostring(err)
            restartPhase = "restart_error"
        end
    end
    return true
end

local function collectState()
    local player = Isaac.GetPlayer(0)
    local level, room = game:GetLevel(), game:GetRoom()
    local roomClear = room:IsClear()
    local frame = game:GetFrameCount()
    local roomIndex = canonicalRoomIndex(level)
    local currentWeapon, weaponKnown = weaponKind(player)
    local heldTrinkets = {}
    local trinketSlots = math.max(1, math.min(2, player:GetMaxTrinkets()))
    for slot = 0, trinketSlots - 1 do
        local id = player:GetTrinket(slot)
        if id and id ~= 0 then table.insert(heldTrinkets, id) end
    end
    local heldPills, heldCards = {}, {}
    for slot = 0, 3 do
        local color = player:GetPill(slot)
        if color and color ~= 0 then table.insert(heldPills, { slot = slot, color = color }) end
        local card = player:GetCard(slot)
        if card and card ~= 0 then table.insert(heldCards, { slot = slot, card = card }) end
    end
    local bossExitAvailable, bossExitPosition, bossExitGridIndex = bossExitInfo(room)
    local enemies, projectiles, pickups, hazards, dangerEffects = {}, {}, {}, {}, {}
    local diagnosticEntities = {}
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if ROUTE_DIAGNOSTICS and action.mode == "boss_exit" then
            diagnosticEntities[#diagnosticEntities+1] = {type=entity.Type,variant=entity.Variant,
                subtype=entity.SubType,id=entity.Index,pos=vectorTable(entity.Position),
                vel=vectorTable(entity.Velocity),size=entity.Size}
        end
        local trackingBomb = trackingBombInfo(entity, player)
        if trackingBomb then
            table.insert(dangerEffects, trackingBomb)
        elseif isCombatEnemy(entity) then
            table.insert(enemies, entityTable(entity))
        elseif isMovingSpikeTrap(entity) or entity.Type == (EntityType.ENTITY_ETERNALFLY or 96) then
            -- Moving spike blocks are a collision threat, not something tears
            -- can kill. Feed their current and near-future cells to routing.
            local radius = math.max(35, math.min(55, (tonumber(entity.Size) or 20) + (tonumber(player.Size) or 10) + 10))
            table.insert(dangerEffects, { id = entity.Index, kind = "moving_spike",
                pos = vectorTable(entity.Position), radius = radius, variant = entity.Variant })
            if entity.Velocity:Length() > 1 then
                table.insert(dangerEffects, { id = entity.Index, kind = "moving_spike_future",
                    pos = vectorTable(entity.Position + entity.Velocity * 4), radius = radius,
                    variant = entity.Variant })
            end
        elseif contactObstacle(entity, player) then
            local radius, kind = contactObstacle(entity, player)
            table.insert(dangerEffects, {id=entity.Index, kind=kind, pos=vectorTable(entity.Position),
                radius=radius, variant=entity.Variant})
        elseif entity.Type == EntityType.ENTITY_PROJECTILE then
            table.insert(projectiles, entityTable(entity))
        elseif entity.Type == EntityType.ENTITY_PICKUP and entity:ToPickup() then
            local pickup = pickupTable(entity)
            if pickup then table.insert(pickups, pickup) end
        elseif dangerousCreep(entity) then
            table.insert(dangerEffects, { id = entity.Index, pos = vectorTable(entity.Position),
                radius = math.max(24, math.min(65, tonumber(entity.Size) or 28)), variant = entity.Variant })
        else
            local kind = liveHazardKind(entity)
            if kind then table.insert(hazards, hazardTable(entity, kind)) end
        end
    end
    -- Bombed rocks can spawn spiders after the engine has already marked the
    -- room clear. Live hostile entities must take priority over that flag.
    if #enemies > 0 then
        roomClear = false
        bossExitAvailable = false
    end
    if roomClear and roomClearedFrame < 0 then roomClearedFrame = frame end
    for index = 0, room:GetGridSize() - 1 do
        local grid = room:GetGridEntity(index)
        local kind = liveGridHazardKind(grid)
        if kind then table.insert(hazards, gridHazardTable(grid, index, kind)) end
    end
    local enemyTotalHp = 0
    for _, enemy in ipairs(enemies) do enemyTotalHp = enemyTotalHp + (tonumber(enemy.hp) or 0) end
    local enemyCount = #enemies
    local enemyKillDelta = math.max(0, lastEnemyCount - enemyCount)
    lastEnemyCount = enemyCount
    local state = {
        type = "state",
        mod_version = MOD_VERSION,
        bridge_generation = strategyControl.generation, restart_count = restartCount,
        floor_id = "canonical-room-v1",
        frame = frame,
        start_seed = startSeed(),
        progression_target = RUN_TARGET,
        room_visit_sequence = roomVisitSequence,
        room_entered_frame = roomEnteredFrame,
        room_cleared_frame = roomClearedFrame,
        damage_events = damageEvents,
        room_clear = roomClear,
        boss_exit_available = bossExitAvailable,
        boss_exit_position = bossExitPosition,
        boss_exit_grid_index = bossExitGridIndex,
        hostile_enemy_count = #enemies,
        enemy_count = enemyCount,
        enemy_total_hp = enemyTotalHp,
        enemy_kill_delta = enemyKillDelta,
        enemy_observation_valid = true,
        hazards_observation_valid = true,
        room_index = roomIndex,
        held_trinkets = heldTrinkets, trinket_slots = trinketSlots,
        held_pills = heldPills, pill_use_result = pillUseResult,
        held_cards = heldCards,
        utility_result = utilityResult, active_item = player:GetActiveItem(0),
        route_debug = routeDebug,
        route_debug_trail = ROUTE_DIAGNOSTICS and routeDebugTrail or nil,
        diagnostic_entities = ROUTE_DIAGNOSTICS and diagnosticEntities or nil,
        active_charge = player:GetActiveCharge(0), control_waypoint = action.waypoint and vectorTable(action.waypoint) or nil,
        charge_phase = nativeChargePhase, control_shoot = vectorTable(fireDirection),
        weapon_control = mod.weaponControl:diagnostics(frame),
        input_lease = mod:inputLease(player),
        native_tear_age = math.max(0,frame-nativeTearFrame),
        trinket_swap_result = trinketSwapResult,
        stage = level:GetStage(), stage_type = level:GetStageType(), dimension = currentDimension(level),
        transition_phase = transitionPhase,
        transition_attempt = transitionAttempt,
        transition_error = transitionError or "",
        transition_gate = transitionGate,
        transition_door_distance = transitionDoorDistance,
        last_transition_source_room_index = lastTransitionSourceRoomIndex,
        last_transition_target_room_index = lastTransitionTargetRoomIndex,
        room_entry_age_frames = math.max(0, game:GetFrameCount() - roomEntryFrame),
        backtrack_guard_active = game:GetFrameCount() - roomEntryFrame < backtrackGuardFrames,
        player_dead = playerIsDead(player),
        restart_phase = restartPhase,
        restart_count = restartCount,
        restart_error = restartError or "",
        requested_move = vectorTable(lastRequestedMove),
        resolved_move = vectorTable(lastResolvedMove),
        movement_progress = lastMovementProgress,
        movement_blocked = lastMovementBlocked,
        move_resolution_reason = lastMoveResolutionReason,
        last_action_id = action.id or "",
        last_action_mode = action.mode or "",
        last_action_sequence = currentActionSequence,
        action_age_frames = math.max(0, frame - lastActionFrame),
        bomb_placed = bombPlaced and bombRoomKey == currentRoomKey(),
        bomb_active = bombStillLive(),
        bomb_target_id = bombTargetId,
        bomb_position = bombPosition and vectorTable(bombPosition) or { x = 0, y = 0 },
        bomb_placed_frame = bombPlacedFrame,
        bomb_placement_distance = bombPlacementDistance,
        bomb_escape_direction = vectorTable(bombRetreatDirection),
        bomb_error = bombError or "",
        coins = player:GetNumCoins(), keys = player:GetNumKeys(), bombs = player:GetNumBombs(), player_grid_index = room:GetGridIndex(player.Position),
        player = {
            move_speed = player.MoveSpeed,
            id = player.Index,
            type = player.Type,
            pos = vectorTable(player.Position),
            vel = vectorTable(player.Velocity),
            hp = player:GetHearts() + player:GetSoulHearts() + player:GetBoneHearts() * 2,
            red_hearts = player:GetHearts(),
            max_hearts = player:GetMaxHearts(),
            damage_cooldown = player.GetDamageCooldown and player:GetDamageCooldown() or 0,
            soul_hearts = player:GetSoulHearts(),
            black_hearts = player:GetBlackHearts(),
            bone_hearts = player:GetBoneHearts(),
            eternal_hearts = player:GetEternalHearts(),
            tear_range = player.TearRange,
            tear_speed = player.ShotSpeed,
            weapon_type = currentWeapon,
            weapon_type_known = weaponKnown,
        },
        enemies = enemies, projectiles = projectiles, pickups = pickups, hazards = hazards,
        danger_effects = dangerEffects,
        fired_tears = firedTearCount, fire_error = fireError,
        fire_block_reason = fireBlockReason,
    }
    -- Grid events and door state can change between packets.
    lastLayout = collectLayout(room, level)
    lastLayoutRoom = roomIndex
    local dangerousIndices = {}
    for _, index in ipairs(lastLayout.danger_grid_indices) do dangerousIndices[index] = true end
    for _, effect in ipairs(dangerEffects) do
        if effect.kind ~= "ghost_bomb" and effect.kind ~= "armed_bomb" then
        local center = Vector(effect.pos.x, effect.pos.y)
        -- Pedestal radii already include Isaac's body. Inflating them by a
        -- second cell margin falsely seals the only row beneath a pedestal.
        -- Damaging effects retain the conservative extra grid margin.
        local padding = (effect.kind == "empty_pedestal" or effect.kind == "unsupported_pedestal"
            or effect.kind == "unselected_health_deal" or effect.kind == "retracted_spike") and 0 or 18
        for index = 0, room:GetGridSize() - 1 do
            if room:GetGridPosition(index):Distance(center) <= effect.radius + padding then
                dangerousIndices[index] = true
            end
        end
        end
    end
    lastLayout.danger_grid_indices = {}
    for index in pairs(dangerousIndices) do table.insert(lastLayout.danger_grid_indices, index) end
    -- Layout is cached because it is relatively expensive to build, but it
    -- must still be present in every state packet. Omitting it between the
    -- refresh frames makes Python fall back to an empty layout and emit
    -- wait_for_exit with a zero movement vector.
    state.layout = lastLayout
    strategyControl.manualOverride = manualOverride
    state.strategy = strategyControl:observe(player,state)
    return state
end

local function localFireDirection(player)
    local nearest, distance, priority = nil, nil, math.huge
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if isCombatEnemy(entity) then
            local currentDistance = entity.Position:Distance(player.Position)
            local npc=entity:ToNPC()
            local score=currentDistance+((npc and not npc:IsVulnerableEnemy()) and 100000 or 0)
            if score < priority then
                nearest, distance = entity, currentDistance
                priority=score
            end
        end
    end
    if not nearest then
        for _, entity in ipairs(Isaac.GetRoomEntities()) do
            if liveHazardKind(entity) then
                local currentDistance = entity.Position:Distance(player.Position)
                if not distance or currentDistance < distance then
                    nearest, distance = entity, currentDistance
                end
            end
        end
    end
    if not nearest then
        local room = game:GetRoom()
        for index = 0, room:GetGridSize() - 1 do
            local grid = room:GetGridEntity(index)
            if liveGridHazardKind(grid) then
                local currentDistance = grid.Position:Distance(player.Position)
                if not distance or currentDistance < distance then
                    nearest, distance = grid, currentDistance
                end
            end
        end
    end
    if not nearest then
        return Vector(0, 0)
    end
    -- Lead moving targets by the time a tear needs to cross the current
    -- distance. Keep the lead bounded so a reversing enemy is not over-shot.
    local velocity = Vector(0, 0)
    local velocityOk, nearestVelocity = pcall(function() return nearest.Velocity end)
    if velocityOk and nearestVelocity then velocity = nearestVelocity end
    local distance = nearest.Position:Distance(player.Position)
    local tearSpeed = math.max(1, (player.ShotSpeed or 1) * 10)
    local profile=mod and mod.weaponControl and mod.weaponControl:profile(player,weaponKind(player)) or {lead=10}
    local leadFrames = math.min(profile.lead, math.max(1, distance / tearSpeed))
    local predicted = nearest.Position + velocity * leadFrames
    local delta = predicted - player.Position
    if math.abs(delta.X) >= math.abs(delta.Y) then
        return Vector(delta.X >= 0 and 1 or -1, 0)
    end
    return Vector(0, delta.Y >= 0 and 1 or -1)
end

local timedSpikeNavigator
local function safeMoveCandidate(player, candidate, allowDoorThreshold, plannedBombRetreat, lookaheadDistance, evaluateBombsTogether, evaluateGroundTogether)
    if candidate:Length() < 0.5 then return false, "zero_direction" end
    local room = game:GetRoom()
    local lookahead = math.max(12, math.min(28, tonumber(lookaheadDistance) or 28))
    local nextPosition = player.Position + candidate * lookahead
    if room.GetDoor then
        local selected=action and action.mode=="navigate"
            and tonumber(string.match(action.id or "","^enter_door_(%d+)$")) or nil
        for slot=0,7 do
            if slot~=selected and room:GetDoor(slot) then
                local center,side=actualDoorPosition(room,slot),doorSlotDirection(slot)
                local before,after=player.Position-center,nextPosition-center
                local inward=-(before.X*side.X+before.Y*side.Y)
                local nextInward=-(after.X*side.X+after.Y*side.Y)
                local lateral=math.abs(after.X*side.Y-after.Y*side.X)
                -- Combat/reward movement must not back into a curse door or
                -- cross another room's threshold when clearing opens it.
                -- Moving back into the room remains legal from an overlap.
                if lateral<38 and nextInward<50 and nextInward<inward-.01 then
                    return false,"unintended_room_exit"
                end
            end
        end
    end
    local intendedExit=action and action.mode=="boss_exit"
        and tonumber(string.match(action.id or "","^enter_boss_exit_(%-?%d+)$")) or nil
    if tntBlastGuard and not tntBlastGuard:safe(player,nextPosition) then return false,"pending_tnt_explosion" end
    local gridIndex = room:GetGridIndex(nextPosition)
    if not allowDoorThreshold and room:GetGridPath(gridIndex) >= 1000 then return false, "grid_wall" end
    local bodyOffsets={Vector(0,0),Vector(16,0),Vector(-16,0),Vector(0,16),Vector(0,-16)}
    for _, point in ipairs({ player.Position + candidate * (lookahead / 2), nextPosition }) do
        for _, offset in ipairs(bodyOffsets) do
            local sampled = point + offset
            local index = room:GetGridIndex(sampled)
            local redPoop = room:GetGridEntity(index)
            local event = gridEvent(redPoop, index)
            if redPoop and redPoop.GetType and redPoop:GetType()==GRID_TRAPDOOR_TYPE
                and intendedExit~=index
                and nextPosition:Distance(redPoop.Position)<42
                and nextPosition:Distance(redPoop.Position)<=player.Position:Distance(redPoop.Position)
            then return false,"unintended_floor_exit" end
            if redPoopGrid(redPoop) and sampled:Distance(redPoop.Position) < 43
                and nextPosition:Distance(redPoop.Position) <= player.Position:Distance(redPoop.Position)
            then return false, "red_poop" end
            local eventPosition = event and Vector(event.pos.x, event.pos.y) or nil
            if event and event.active and (event.kind == "spike" or event.kind == "tnt")
                and sampled:Distance(eventPosition) < 32
                and nextPosition:Distance(eventPosition) <= player.Position:Distance(eventPosition)
                and not (strategyControl and strategyControl:macroAllowed(index,player))
            then return false, "spike_or_tnt" end
        end
    end
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        local obstacleRadius = contactObstacle(entity, player)
            or (strategyControl and strategyControl:effectObstacle(entity,player))
        if obstacleRadius then
            local currentDistance = player.Position:Distance(entity.Position)
            local nextDistance = nextPosition:Distance(entity.Position)
            local middleDistance = (player.Position + candidate * (lookahead / 2)):Distance(entity.Position)
            if math.min(nextDistance, middleDistance) < obstacleRadius
                and nextDistance <= currentDistance then return false, "contact_obstacle" end
        end
        local trackingBomb = trackingBombInfo(entity, player)
        if trackingBomb and not evaluateBombsTogether then
            local center = entity.Position + (entity.Velocity or Vector(0, 0)) * 8
            local radius = trackingBomb.radius + 18
            local currentDistance = player.Position:Distance(center)
            local nextDistance = nextPosition:Distance(center)
            local middleDistance = (player.Position + candidate * 14):Distance(center)
            if (nextDistance < radius or middleDistance < radius)
                and nextDistance <= currentDistance then return false, "ghost_bomb" end
        end
        if isMovingSpikeTrap(entity) or entity.Type == (EntityType.ENTITY_ETERNALFLY or 96) then
            local radius = math.max(35, math.min(55, (tonumber(entity.Size) or 20) + (tonumber(player.Size) or 10) + 10))
            for _, center in ipairs({ entity.Position, entity.Position + entity.Velocity * 4 }) do
                local currentDistance = player.Position:Distance(center)
                local nextDistance = nextPosition:Distance(center)
                local middleDistance = (player.Position + candidate * 14):Distance(center)
                if (nextDistance < radius or middleDistance < radius)
                    and nextDistance <= currentDistance then return false, "moving_spike" end
            end
        end
        if not evaluateGroundTogether and (liveHazardKind(entity) == "fire" or bombOnlyFireKind(liveHazardKind(entity))) then
            local radius = math.max(36, (tonumber(player.Size) or 10) + (tonumber(entity.Size) or 15) + 8)
            local currentDistance = player.Position:Distance(entity.Position)
            local nextDistance = nextPosition:Distance(entity.Position)
            local middleDistance = (player.Position + candidate * 14):Distance(entity.Position)
            if (nextDistance < radius or middleDistance < radius)
                and nextDistance <= currentDistance then return false, "fire" end
        end
        if not evaluateGroundTogether and not player.CanFly and dangerousCreep(entity) then
            local radius = math.max(24, math.min(65, tonumber(entity.Size) or 28)) + 18
            local currentDistance = player.Position:Distance(entity.Position)
            local nextDistance = nextPosition:Distance(entity.Position)
            local middleDistance = (player.Position + candidate * 14):Distance(entity.Position)
            if (nextDistance < radius or middleDistance < radius)
                and nextDistance <= currentDistance then return false, "creep" end
        end
    end
    for _, offset in ipairs({ Vector(0, 0), Vector(-40, 0), Vector(40, 0),
        Vector(0, -40), Vector(0, 40), Vector(-40, -40), Vector(40, -40),
        Vector(-40, 40), Vector(40, 40) }) do
        local other = room:GetGridEntity(room:GetGridIndex(nextPosition + offset))
        if other and (liveGridHazardKind(other) == "fire" or bombOnlyFireKind(liveGridHazardKind(other)))
            and nextPosition:Distance(other.Position) < 36
            and nextPosition:Distance(other.Position) <= player.Position:Distance(other.Position) then return false, "grid_fire" end
    end
    if bombStillLive() and bombPosition and not plannedBombRetreat
        and nextPosition:Distance(bombPosition) < player.Position:Distance(bombPosition)
        and nextPosition:Distance(bombPosition) < 120 then return false, "bomb_blast" end
    if timedSpikeNavigator and not timedSpikeNavigator:motionSafe(player,candidate,game:GetFrameCount()) then
        return false,"closing_spike_window"
    end
    return true, "safe"
end

local function firstSafeMove(player, desired, allowDoorThreshold)
    if desired:Length() < 0.5 then return Vector(0, 0) end
    if allowDoorThreshold then
        return safeMoveCandidate(player, desired, true) and desired or Vector(0, 0)
    end
    local candidates = { desired, Vector(-desired.Y, desired.X), Vector(desired.Y, -desired.X), Vector(-desired.X, -desired.Y) }
    for index, candidate in ipairs(candidates) do
        if safeMoveCandidate(player, candidate, false) then return candidate end
    end
    return Vector(0, 0)
end

local function projectedHazardLaneClear(room, startPosition, targetPosition, direction)
    if room:GetGridPath(room:GetGridIndex(startPosition)) >= 1000 then return false end
    local distance = startPosition:Distance(targetPosition)
    for step = 40, distance - 40, 20 do
        local point = startPosition + direction * step
        if room:GetGridPath(room:GetGridIndex(point)) >= 1000 then return false end
    end
    return true
end

local function hazardLaneCorrection(player, target, targetId)
    local roomKey = currentRoomKey()
    if hazardLaneRoomKey ~= roomKey or hazardLaneTargetId ~= targetId then
        hazardLaneRoomKey, hazardLaneTargetId, hazardLaneAxis = roomKey, targetId, ""
    end
    local delta = target.Position - player.Position
    local maximumRange = math.max(0, player.TearRange - 25)
    local horizontal = math.abs(delta.X) >= 70 and math.abs(delta.X) <= maximumRange
    local vertical = math.abs(delta.Y) >= 70 and math.abs(delta.Y) <= maximumRange
    local room = game:GetRoom()
    local horizontalDirection = Vector(delta.X >= 0 and 1 or -1, 0)
    local verticalDirection = Vector(0, delta.Y >= 0 and 1 or -1)
    local horizontalClear = horizontal and projectedHazardLaneClear(room,
        Vector(player.Position.X, target.Position.Y), target.Position, horizontalDirection)
    local verticalClear = vertical and projectedHazardLaneClear(room,
        Vector(target.Position.X, player.Position.Y), target.Position, verticalDirection)
    if hazardLaneAxis == "horizontal" and (not horizontalClear or math.abs(delta.Y) > 80) then hazardLaneAxis = "" end
    if hazardLaneAxis == "vertical" and (not verticalClear or math.abs(delta.X) > 80) then hazardLaneAxis = "" end
    if hazardLaneAxis == "" then
        if horizontalClear and math.abs(delta.Y) <= 36 then hazardLaneAxis = "horizontal"
        elseif verticalClear and math.abs(delta.X) <= 36 then hazardLaneAxis = "vertical" end
    end
    if hazardLaneAxis == "" then return nil end
    local offset = hazardLaneAxis == "horizontal" and delta.Y or delta.X
    local velocity = hazardLaneAxis == "horizontal" and player.Velocity.Y or player.Velocity.X
    if math.abs(offset) <= 14 and math.abs(velocity) <= 1.3 then return Vector(0, 0) end
    local correction = offset - velocity * 4
    if math.abs(correction) <= 10 then return Vector(0, 0) end
    local move = hazardLaneAxis == "horizontal"
        and Vector(0, correction > 0 and 1 or -1)
        or Vector(correction > 0 and 1 or -1, 0)
    -- Never replace a blocked braking step with a perpendicular detour: that
    -- would move the player out of the firing lane and restart the oscillation.
    return safeMoveCandidate(player, move, false) and move or Vector(0, 0)
end

-- Score ordinary input directions against future collision positions. This
-- only chooses movement/tears; it never changes stats, entities or game rules.
local liveGridRoute = nil
timedSpikeNavigator = include("timed_spikes").new()
local function followGridRoute(player, target, stopDistance)
    local room = game:GetRoom()
    local width, size = room:GetGridWidth(), room:GetGridSize()
    local start, goal = room:GetGridIndex(player.Position), room:GetGridIndex(target)
    if player.Position:Distance(target) <= (stopDistance or 8) then
        if timedSpikeNavigator.active and timedSpikeNavigator.goal==goal then timedSpikeNavigator:finish(goal) end
        return Vector(0, 0)
    end
    local key = currentRoomKey() .. ":" .. tostring(goal)
    local frame = game:GetFrameCount()
    timedSpikeNavigator:observe(room,frame,currentRoomKey(),gridEvent)
    local contactObstacles = {}
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        local radius = contactObstacle(entity, player)
            or (strategyControl and strategyControl:effectObstacle(entity,player))
        if not radius and not player.CanFly and dangerousCreep(entity) then
            radius=math.max(24,math.min(65,tonumber(entity.Size) or 28))+18
        end
        if not radius and (liveHazardKind(entity)=="fire" or bombOnlyFireKind(liveHazardKind(entity))) then
            radius=math.max(36,(player.Size or 10)+(entity.Size or 15)+8)
        end
        if not radius and isCombatEnemy(entity) then
            radius=(player.Size or 10)+math.min(40,entity.Size or 12)+26
        end
        if radius then contactObstacles[#contactObstacles+1] = {position=entity.Position, radius=radius} end
    end
    local function walkable(index, allowTimed)
        if index < 0 or index >= size or room:GetGridPath(index) >= 1000 then return false end
        local grid = room:GetGridEntity(index)
        if grid and grid.GetType and grid:GetType()==GRID_TRAPDOOR_TYPE then
            local intendedExit=action and action.mode=="boss_exit"
                and tonumber(string.match(action.id or "","^enter_boss_exit_(%-?%d+)$")) or nil
            if intendedExit~=index then return false end
        end
        local event = gridEvent(grid, index)
        if redPoopGrid(grid) or (event and event.kind == "spike" and event.timed and not allowTimed)
            or (event and event.active and (event.kind == "spike" or event.kind == "tnt")
            and not (allowTimed and event.kind == "spike" and event.timed)
            and not (strategyControl and strategyControl:macroAllowed(index,player))) then return false end
        local center = room:GetGridPosition(index)
        for _, obstacle in ipairs(contactObstacles) do
            if center:Distance(obstacle.position) < obstacle.radius then return false end
        end
        return true
    end
    if not liveGridRoute or liveGridRoute.key ~= key or frame - liveGridRoute.frame > 90
        or not walkable(liveGridRoute.path[liveGridRoute.cursor],true) then
        local parents, found, requiresTiming
        -- Prefer a permanent safe detour even when the direct spikes happen
        -- to be down. Use a timed crossing only if there is no stable route.
        for _,allowTimed in ipairs({false,true}) do
            local goals = {}
            if walkable(goal,allowTimed) then goals[goal] = true
            else
                for _, index in ipairs({goal - 1, goal + 1, goal - width, goal + width}) do
                    if walkable(index,allowTimed) and room:GetGridPosition(index):Distance(target) <= 61 then goals[index] = true end
                end
            end
            local queue, head = {start}, 1
            parents, found = {[start] = -1}, nil
            while head <= #queue do
                local index = queue[head]
                head = head + 1
                if goals[index] then found = index break end
                for _, nextIndex in ipairs({index - 1, index + 1, index - width, index + width}) do
                    local adjacent = math.abs(index % width - nextIndex % width)
                        + math.abs(math.floor(index / width) - math.floor(nextIndex / width)) == 1
                    if adjacent and parents[nextIndex] == nil and walkable(nextIndex,allowTimed) then
                        parents[nextIndex] = index
                        queue[#queue + 1] = nextIndex
                    end
                end
            end
            if found then requiresTiming=allowTimed break end
        end
        if not found then
            liveGridRoute = nil
            routeDebug={goal=goal,start=start,reason="no_live_route",path={}}
            return nil
        end
        local path, index = {}, found
        while index ~= -1 do table.insert(path, 1, index) index = parents[index] end
        liveGridRoute = {key=key, frame=frame, path=path, cursor=math.min(2, #path),timed=requiresTiming}
    end
    local route = liveGridRoute
    if not route.timed and timedSpikeNavigator.active and not timedSpikeNavigator.history[start] then
        -- A shorter ordinary route can become available after the plate
        -- lowers spikes or after reaching the approach tile beside a door.
        -- Its existence must release the previous temporal movement owner.
        timedSpikeNavigator.active,timedSpikeNavigator.plan,timedSpikeNavigator.waiting=false,nil,false
    end
    if route.timed then
        local move,waiting=timedSpikeNavigator:move(room,player,target,route.path[#route.path],frame,
            function(index) return walkable(index,true) end)
        timedSpikeNavigator.waiting=waiting
        if move then
            routeDebug={timed=true,reason=timedSpikeNavigator.reason,goal=goal,
                path=timedSpikeNavigator.plan and timedSpikeNavigator.plan.points or {}}
            gridRouteControlled=true
            return move
        end
        route.cursor=#route.path
    end
    local waypoint = room:GetGridPosition(route.path[route.cursor])
    local velocity = player.Velocity or Vector(0,0)
    local function turnsHere()
        if route.cursor >= #route.path then return true end
        local before = room:GetGridPosition(route.path[math.max(1,route.cursor-1)])
        local after = room:GetGridPosition(route.path[route.cursor+1])
        return (waypoint.X-before.X)*(after.Y-waypoint.Y)
            ~= (waypoint.Y-before.Y)*(after.X-waypoint.X)
    end
    while route.cursor < #route.path and player.Position:Distance(waypoint) <= math.max(8, stopDistance or 8) do
        -- Reaching a corner at full speed does not mean the body can turn:
        -- the previous direction keeps sliding after its input is released.
        if turnsHere() and velocity:Length() > 1.4 then break end
        route.cursor = route.cursor + 1
        waypoint = room:GetGridPosition(route.path[route.cursor])
    end
    if route.cursor == #route.path and player.Position:Distance(waypoint) <= 8 then waypoint = target end
    local delta = waypoint - player.Position
    routeDebug = {goal=goal, start=start, cursor=route.cursor, path=route.path,
        waypoint={x=waypoint.X,y=waypoint.Y}, position={x=player.Position.X,y=player.Position.Y}}
    if delta:Length() <= (stopDistance or 8) then return Vector(0, 0) end
    local previous = room:GetGridPosition(route.path[math.max(1, route.cursor - 1)])
    local horizontal = math.abs(waypoint.X - previous.X) > math.abs(waypoint.Y - previous.Y)
    local perpendicular = horizontal and delta.Y or delta.X
    local perpendicularVelocity = horizontal and velocity.Y or velocity.X
    -- Measured native coasting distance with 0.7 velocity decay. Correct the
    -- eventual resting position, rather than chasing the current coordinate.
    local restingError = perpendicular-perpendicularVelocity*(1.7/0.3)
    local desired
    if math.abs(perpendicular)>6 or math.abs(restingError)>9 then
        if math.abs(restingError)<=3 then desired=Vector(0,0)
        else desired=horizontal and Vector(0,restingError>0 and 1 or -1)
            or Vector(restingError>0 and 1 or -1,0) end
    else
        local along = horizontal and delta.X or delta.Y
        local alongVelocity = horizontal and velocity.X or velocity.Y
        local alongError = turnsHere() and (along-alongVelocity*(1.7/0.3)) or along
        if math.abs(alongError)<=3 then desired=Vector(0,0)
        else desired=horizontal and Vector(alongError>0 and 1 or -1,0)
            or Vector(0,alongError>0 and 1 or -1) end
    end
    if desired:Length()<0.5 then gridRouteControlled=true return desired end
    local alongDistance = math.abs(desired.X) > 0 and math.abs(delta.X) or math.abs(delta.Y)
    local safe, reason = safeMoveCandidate(player, desired, false, false, alongDistance)
    if not safe and reason=="unintended_room_exit" then
        -- A body entering from a door can be off the grid centerline. Moving
        -- toward that center would cross the guarded threshold; first move
        -- along the route until clear of the door, with full live safety.
        local along=horizontal and Vector(delta.X>0 and 1 or -1,0)
            or Vector(0,delta.Y>0 and 1 or -1)
        local distance=horizontal and math.abs(delta.X) or math.abs(delta.Y)
        if distance>8 and safeMoveCandidate(player,along,false,false,distance) then
            desired,safe=along,true
        end
    end
    if not safe and (reason == "grid_wall" or reason == "spike_or_tnt") then
        -- A six-pixel centering correction must not be vetoed because a wall
        -- lies 28 pixels beyond the waypoint at the coming right-angle turn.
        local step = player.Position + desired * math.min(12, delta:Length())
        safe = true
        for _, offset in ipairs({Vector(0,0),Vector(12,0),Vector(-12,0),Vector(0,12),Vector(0,-12)}) do
            if not walkable(room:GetGridIndex(step + offset)) then safe = false break end
        end
    end
    gridRouteControlled = true
    return safe and desired or Vector(0,0)
end

local function clearTearLine(room, from, to)
    local delta = to - from
    local distance = delta:Length()
    if distance < 1 then return true end
    local direction = delta * (1 / distance)
    local targetIndex = room:GetGridIndex(to)
    for step = 16, distance - 16, 16 do
        local index = room:GetGridIndex(from + direction * step)
        if index == targetIndex then
            -- The destructible target occupies this cell; hit its front.
        elseif room.GetGridCollision then
            if room:GetGridCollision(index) >= GridCollisionClass.COLLISION_OBJECT then return false end
        elseif room:GetGridPath(index) >= 1000 then return false end
    end
    return true
end

local function bobsBrainShotSafe(player)
    if not player.HasCollectible or not player:HasCollectible(273)
        or player:HasCollectible(223) or player:HasCollectible(375) then return true end
    -- An already owned brain cannot be discarded. Shooting launches it after
    -- a delay, so reserve room for a nearby enemy's approach during that delay.
    -- Do not rely on the familiar's undocumented state counter as readiness.
    for _,entity in ipairs(Isaac.GetRoomEntities()) do
        if isCombatEnemy(entity) then
            local delta=entity.Position-player.Position
            local relative=(entity.Velocity or Vector(0,0))-(player.Velocity or Vector(0,0))
            for tick=0,6,2 do
                if (delta+relative*tick):Length()<165 then return false end
            end
        end
    end
    return true
end

local function chargedShootDirection(player,wanted,weapon)
    local control,frame,room=mod.weaponControl,game:GetFrameCount(),game:GetRoom()
    local profile=control:profile(player,weapon)
    control:configure(profile)
    local context={engaged=false,ready=false,active_beam=false,shot=false}
    local entities=Isaac.GetRoomEntities()
    local best,bestScore=nil,math.huge
    for _,entity in ipairs(entities) do
        if isCombatEnemy(entity) then
            context.engaged=true
            local npc=entity:ToNPC()
            local distance=entity.Position:Distance(player.Position)
            local lead=math.min(profile.lead,distance/math.max(4,(player.ShotSpeed or 1)*10))
            local delta=entity.Position+(entity.Velocity or Vector(0,0))*lead-player.Position
            local minor=math.min(math.abs(delta.X),math.abs(delta.Y))
            local locked=profile.lockAim and distance>65 and control.start>=0 and control.last
                and math.abs(control.last.x)+math.abs(control.last.y)>.5
            local behind=false
            if locked then
                minor=math.abs(delta.X*control.last.y-delta.Y*control.last.x)
                behind=delta.X*control.last.x+delta.Y*control.last.y<=0
            end
            local vulnerable=npc and npc:IsVulnerableEnemy()
            local clear=profile.pierces or clearTearLine(room,player.Position,entity.Position)
            local score=minor*7+distance*.1+(vulnerable and 0 or 2000)+(clear and 0 or 1000)
            if entity.Index==combatAimTargetId then score=score-60 end
            if score<bestScore then
                bestScore=score
                best={id=entity.Index,distance=distance,hp=entity.HitPoints,pos=vectorTable(entity.Position),
                    direction=locked and Vector(control.last.x,control.last.y)
                    or math.abs(delta.X)>=math.abs(delta.Y)
                    and Vector(delta.X>=0 and 1 or -1,0) or Vector(0,delta.Y>=0 and 1 or -1),
                    ready=vulnerable and clear and not behind and minor<=math.min(50,entity.Size or 12)+profile.width}
            end
        end
        -- Ignore continuum descendants: they are part of the same shot and
        -- must not confirm several releases or extend charge timing forever.
        local owner=entity.SpawnerEntity
        if owner and owner.Type==EntityType.ENTITY_PLAYER and owner.Index==player.Index then
            local parent=entity.Parent
            local primary=not parent or parent.Type==EntityType.ENTITY_PLAYER
            if entity.Type==EntityType.ENTITY_LASER and primary then
                local identity="l:"..tostring(entity.InitSeed or entity.Index)
                if not control.seen[identity] then context.shot=true;control.seen[identity]=frame end
                local laser=entity:ToLaser()
                if weapon=="brimstone" and laser and (laser.Timeout or 0)>0 then context.active_beam=true end
            elseif entity.Type==EntityType.ENTITY_TEAR then
                local identity="t:"..tostring(entity.InitSeed or entity.Index)
                if not control.seen[identity] then context.shot=true;control.seen[identity]=frame end
            elseif entity.Type==EntityType.ENTITY_KNIFE then
                local knife=entity:ToKnife()
                if knife then
                    local flying=knife:IsFlying()
                    context.knife_flying=context.knife_flying or flying
                    context.knife_charge=math.max(context.knife_charge or 0,tonumber(knife.Charge) or 0)
                    if flying and not control.knifeWasFlying then context.shot=true end
                end
            end
        end
    end
    control.knifeWasFlying=context.knife_flying or false
    if frame%90==0 then
        for identity,seenFrame in pairs(control.seen) do if frame-seenFrame>180 then control.seen[identity]=nil end end
    end
    if best and (profile.mode=="release" or profile.mode=="melee") then
        wanted=best.direction
        context.ready,context.distance=best.ready,best.distance
    elseif action.mode=="hazard" or action.mode=="tnt" then
        context.ready=wanted:Length()>.5
        local targetId=tonumber(string.match(action.id or "","^clear_hazard_(%-?%d+)$")
            or string.match(action.id or "","^shoot_tnt_(%-?%d+)$"))
        local target=nil
        if targetId and targetId<=-100000 then target=room:GetGridEntity(-100000-targetId)
        elseif targetId then for _,entity in ipairs(entities) do if entity.Index==targetId then target=entity break end end end
        if target then
            local delta=target.Position-player.Position
            context.engaged=true
            control.hazardId=targetId
            if profile.mode=="release" or profile.mode=="melee" then
                wanted=math.abs(delta.X)>=math.abs(delta.Y)
                    and Vector(delta.X>=0 and 1 or -1,0) or Vector(0,delta.Y>=0 and 1 or -1)
            end
        else context.engaged=false end
    else
        context.ready=wanted:Length()>.5
        -- A brief projectile dodge may replace an obstacle action with wait
        -- or evade. Keep the same living obstacle charged through that gap.
        if not context.engaged and not room:IsClear() and control.start>=0 and control.hazardId then
            local target=nil
            if control.hazardId<=-100000 then
                target=room:GetGridEntity(-100000-control.hazardId)
                if target and not liveGridHazardKind(target) then target=nil end
            else
                for _,entity in ipairs(entities) do
                    if entity.Index==control.hazardId and liveHazardKind(entity) then target=entity break end
                end
            end
            if target then context.engaged=true;context.ready=false;wanted=Vector(control.last.x,control.last.y) end
        end
    end
    if not context.engaged and not room:IsClear() and control.start>=0 then
        context.engaged,context.ready=true,false
        wanted=Vector(control.last.x,control.last.y)
    end
    context.hard_stop=not automatic or ghostBombRetreatActive
        or (fireBlockReason=="special_fire_bomb_only")
    control.required,control.targetId,control.targetReady=profile.charge+(control.extra or 0),best and best.id or -1,context.ready
    control.profileKind=profile.kind
    local output=control:step(frame,profile,{x=wanted.X,y=wanted.Y},context)
    if (profile.mode=="release" or profile.mode=="melee") and Json
        and (control.phase=="release" or context.shot) then
        Isaac.DebugString("[NativeIsaac] WEAPON_CONTROL "..Json.encode({
            seed=startSeed(),frame=frame,room=canonicalRoomIndex(game:GetLevel()),
            weapon=weapon,profile=profile.kind,phase=control.phase,charge_frames=control.required,
            elapsed=control.start>=0 and frame-control.start or 0,
            release_count=control.releases,confirmed_releases=control.confirmations,
            observed_attack=context.shot,active_beam=context.active_beam,
            target=best and {id=best.id,hp=best.hp,pos=best.pos,ready=best.ready} or nil,
            player=vectorTable(player.Position),aim={x=wanted.X,y=wanted.Y},
            input=output,failed_releases=control.failures}))
    end
    nativeChargeStartFrame,nativeChargePhase=control.start,control.phase
    return Vector(output.x,output.y)
end

local function escapeStomp(player)
    local threats, entities = {}, Isaac.GetRoomEntities()
    local threatened=false
    for _, entity in ipairs(entities) do
        local radius, kind = contactObstacle(entity, player)
        if not player.CanFly and dangerousCreep(entity) then
            radius, kind = math.max(24, math.min(65, tonumber(entity.Size) or 28)) + 18, "creep"
        end
        if liveHazardKind(entity)=="fire" or bombOnlyFireKind(liveHazardKind(entity)) then
            radius,kind=math.max(36,(player.Size or 10)+(entity.Size or 15)+8),"fire"
        end
        local margin = kind == "stomp" and 30 or 0
        if radius then
            threats[#threats+1]={entity=entity,radius=radius}
            if player.Position:Distance(entity.Position)<radius+margin then threatened=true end
        end
    end
    if not threatened then return nil end
    local best, bestScore = nil, -math.huge
    for _, direction in ipairs({Vector(1,0),Vector(-1,0),Vector(0,1),Vector(0,-1),
        Vector(0.7071,0.7071),Vector(0.7071,-0.7071),Vector(-0.7071,0.7071),Vector(-0.7071,-0.7071)}) do
        -- Judge overlapping pools together. Escaping one pool can briefly
        -- approach another; pairwise vetoes previously froze Isaac to death.
        if safeMoveCandidate(player, direction, false,false,nil,false,true) then
            local position,speed,score=player.Position,player.Velocity or Vector(0,0),0
            local clearance=math.huge
            for tick=1,8 do
                local following=speed*.7+direction*(1.14*(player.MoveSpeed or 1))
                local nextPosition=position+speed+following
                if game:GetRoom():GetGridPath(game:GetRoom():GetGridIndex(nextPosition))<1000 then
                    position,speed=nextPosition,following
                else speed=Vector(0,0) end
                clearance=math.huge
                for _,threat in ipairs(threats) do
                    local margin=position:Distance(threat.entity.Position)-threat.radius
                    clearance=math.min(clearance,margin)
                    score=score-math.max(0,-margin)*(1+tick*.1)
                end
            end
            score=score+math.min(100,clearance)*8
            for _, enemy in ipairs(entities) do
                if isCombatEnemy(enemy) then
                    score = score - math.max(0, 80 - position:Distance(enemy.Position + enemy.Velocity * 5)) * 3
                elseif enemy.Type == EntityType.ENTITY_PROJECTILE then
                    score = score - math.max(0, 40 - position:Distance(enemy.Position + enemy.Velocity * 5)) * 6
                end
            end
            if score > bestScore then best, bestScore = direction, score end
        end
    end
    return best
end

local function gridDangerClearance(player, position, center)
    local dx = math.max(0, math.abs(position.X - center.X) - 18)
    local dy = math.max(0, math.abs(position.Y - center.Y) - 18)
    return math.sqrt(dx * dx + dy * dy) - (player.Size or 10) - 3
end

local function escapeGridDanger(player)
    if player.CanFly then return nil end
    local room, dangers, seen, threatened = game:GetRoom(), {}, {}, false
    for _, x in ipairs({-40,0,40}) do
        for _, y in ipairs({-40,0,40}) do
            local index = room:GetGridIndex(player.Position + Vector(x,y))
            if not seen[index] then
                seen[index] = true
                local grid = room:GetGridEntity(index)
                local event = gridEvent(grid, index)
                if (event and event.kind == "spike" and event.active) or redPoopGrid(grid) then
                    dangers[#dangers+1] = grid.Position
                    if gridDangerClearance(player,player.Position,grid.Position) <= 3 then threatened = true end
                end
            end
        end
    end
    if not threatened then return nil end
    local best, bestScore = Vector(0,0), -math.huge
    for _, direction in ipairs({Vector(1,0),Vector(-1,0),Vector(0,1),Vector(0,-1),
        Vector(0.7071,0.7071),Vector(0.7071,-0.7071),Vector(-0.7071,0.7071),Vector(-0.7071,-0.7071)}) do
        if safeMoveCandidate(player,direction,false) then
            local future = player.Position + direction * 28 + (player.Velocity or Vector(0,0)) * 2
            local clearance = math.huge
            for _, danger in ipairs(dangers) do
                clearance = math.min(clearance,gridDangerClearance(player,future,danger))
            end
            if clearance > bestScore then best,bestScore = direction,clearance end
        end
    end
    return best
end

local function hostileLaser(entity)
    if entity.Type ~= EntityType.ENTITY_LASER then return nil end
    local laser = entity:ToLaser()
    if not laser then return nil end
    if laser.SpawnerType == EntityType.ENTITY_PLAYER or laser.SpawnerType == EntityType.ENTITY_FAMILIAR then return nil end
    local owner = laser.SpawnerEntity or laser.Parent
    for _ = 1, 4 do
        if not owner then break end
        if owner.Type == EntityType.ENTITY_PLAYER or owner.Type == EntityType.ENTITY_FAMILIAR then return nil end
        local npc = owner:ToNPC()
        if npc and npc:HasEntityFlags(EntityFlag.FLAG_FRIENDLY) then return nil end
        owner = owner.SpawnerEntity
    end
    return laser
end

local function laserClearance(laser, position, tick)
    local start = laser.Position + laser.Velocity * math.min(tick, 6)
    if laser:IsCircleLaser() then
        return math.abs(position:Distance(start) - laser.Radius)
    end
    local delta = laser:GetEndPoint() - laser.Position
    if laser.IsActiveRotating and tick > (laser.RotationDelay or 0) then
        local angle = math.rad((laser.RotationSpd or 0) * (tick - math.max(0, laser.RotationDelay or 0)))
        delta = Vector(delta.X * math.cos(angle) - delta.Y * math.sin(angle),
            delta.X * math.sin(angle) + delta.Y * math.cos(angle))
    end
    local offset = position - start
    local lengthSquared = delta.X * delta.X + delta.Y * delta.Y
    local fraction = lengthSquared > 0.01 and math.max(0, math.min(1,
        (offset.X * delta.X + offset.Y * delta.Y) / lengthSquared)) or 0
    return position:Distance(start + delta * fraction)
end

local function movementForecast(player, move, horizon, room, collision)
    local profile=mod and mod.runtimeProfile
    local started=profile and Isaac.GetTime()
    -- Native samples: velocity retention ~0.707, displacement ~2 * average
    -- velocity per game update. A released direction still has momentum.
    local position=Vector(player.Position.X,player.Position.Y)
    local velocity=player.Velocity or Vector(0,0)
    local acceleration=1.14*math.max(0.3,player.MoveSpeed or 1)
    local positions={[0]=position}
    local radius=math.max(6,math.min(12,player.Size or 10)-1)
    -- This cache lives for one synchronous prediction only. No engine update,
    -- grid mutation or room transition occurs between these candidate paths.
    -- The next prediction starts fresh, including after a door/rock changes.
    collision=collision or {}
    if room and not collision.offsets then
        collision.offsets={Vector(0,0),Vector(radius,0),Vector(-radius,0),Vector(0,radius),Vector(0,-radius),
            Vector(radius*.707,radius*.707),Vector(-radius*.707,radius*.707),
            Vector(radius*.707,-radius*.707),Vector(-radius*.707,-radius*.707)}
        collision.gridSize=room.GetGridSize and room:GetGridSize() or nil
        collision.paths={};collision.centers={}
    end
    local function clearBody(point,from)
        for _,offset in ipairs(collision.offsets) do
            local index=room:GetGridIndex(point+offset)
            if collision.gridSize and (index<0 or index>=collision.gridSize) then return false end
            local path=collision.paths[index]
            if path==nil then path=room:GetGridPath(index);collision.paths[index]=path end
            if path>=1000 then
                -- A native body may already overlap a closed door/wall edge.
                -- Rejecting every partially overlapping forecast freezes all
                -- escape predictions at that position. Permit leaving only
                -- this already touched cell, with strictly less penetration;
                -- a new blocked cell still stops normal collision movement.
                local oldIndex=room:GetGridIndex(from+offset)
                local center=collision.centers[index]
                if not center and room.GetGridPosition then center=room:GetGridPosition(index);collision.centers[index]=center end
                if oldIndex~=index or not center
                    or point:Distance(center)<=from:Distance(center)+.001 then return false end
            end
        end
        return true
    end
    for tick=1,horizon do
        local nextVelocity=velocity*0.7+move*acceleration
        local nextPosition=position+velocity+nextVelocity
        if room and not clearBody(nextPosition,position) then
            local xOnly=Vector(nextPosition.X,position.Y)
            local yOnly=Vector(position.X,nextPosition.Y)
            if clearBody(xOnly,position) then nextPosition=xOnly;nextVelocity.Y=0
            elseif clearBody(yOnly,position) then nextPosition=yOnly;nextVelocity.X=0
            else nextPosition=position;nextVelocity=Vector(0,0) end
        end
        position=nextPosition
        velocity=nextVelocity
        positions[tick]=position
    end
    if profile then profile:detail("movement_forecast",Isaac.GetTime()-started) end
    return positions
end

local function predictiveCombatMove(player, ignoreWaypoint)
    local room, entities = game:GetRoom(), Isaac.GetRoomEntities()
    local enemies, projectiles, lasers, telegraphs, contacts = {}, {}, {}, {}, {}
    local deathBlasts,finishGlobins,attackTargets,reactiveChargers={},{},{},{}
    for _, entity in ipairs(entities) do
        if isMovingSpikeTrap(entity) or entity.Type == (EntityType.ENTITY_ETERNALFLY or 96) then
            contacts[#contacts+1]=entity
        elseif isCombatEnemy(entity) then
            enemies[#enemies + 1] = entity
            contacts[#contacts+1]=entity
            local npc=entity.ToNPC and entity:ToNPC() or nil
            reactiveChargers[entity]=entity.Type==(EntityType.ENTITY_GURDY_JR or 99)
                or (entity.Type==(EntityType.ENTITY_FALLEN or 81) and (entity.Variant or 0)==0)
            local champion=npc and npc.GetChampionColorIdx and npc:GetChampionColorIdx() or -1
            if entity.Type==(EntityType.ENTITY_BOOMFLY or 25)
                or (entity.Type==(EntityType.ENTITY_MULLIGAN or 16) and (entity.Variant or 0)==2)
                or entity.Type==(EntityType.ENTITY_TICKING_SPIDER or 250)
                or (entity.Type==(EntityType.ENTITY_LEECH or 55) and (entity.Variant or 0)==1)
                or champion==((ChampionColor and ChampionColor.BLACK) or 5) then
                -- Death explosions happen before a new bomb observation can
                -- arrive. Keep their firing approaches outside the blast.
                deathBlasts[entity]=true
            end
            if entity.Type==(EntityType.ENTITY_GLOBIN or 24) then
                local ok,animation=pcall(function() return string.lower(entity:GetSprite():GetAnimation()) end)
                finishGlobins[entity]=(entity.HitPoints or math.huge)<=3.5
                    or (ok and string.find(animation,"regen",1,true)~=nil)
                -- A standing/appearing Globin can start pursuing before a
                -- zero-velocity linear forecast reacts. Its downed form must
                -- still be finished promptly instead of keeping this gap.
                reactiveChargers[entity]=not finishGlobins[entity]
            end
            if not npc or not npc.IsVulnerableEnemy or npc:IsVulnerableEnemy() or finishGlobins[entity] then
                attackTargets[#attackTargets+1]=entity
            end
            -- Monstro II can repeatedly fire a horizontal beam with a very
            -- short wind-up. Keep a vertical offset throughout this fight.
            if entity.Type == (EntityType.ENTITY_MONSTRO2 or 43) then
                telegraphs[#telegraphs+1]={position=entity.Position,horizontal=true}
            end
            if entity.Type==(EntityType.ENTITY_FALLEN or 81) and (entity.Variant or 0)==0
                and (npc and npc.State or entity.State)==10 then
                telegraphs[#telegraphs+1]={position=entity.Position,horizontal=true}
                telegraphs[#telegraphs+1]={position=entity.Position,horizontal=false}
            end
            -- Satan's Attack03 is shared by hand beams and tear rings. Only
            -- the documented mouth state defines this straight downward ray;
            -- curved hand beams retain their observed laser geometry below.
            if entity.Type==(EntityType.ENTITY_SATAN or 84) and (entity.Variant or 0)==0
                and (npc and npc.State or entity.State)==9 then
                telegraphs[#telegraphs+1]={position=entity.Position,direction=Vector(0,1),forwardOnly=true}
            end
            -- Vis beams hurt immediately; leave their visible wind-up lane
            -- before the beam entity exists, including during routed movement.
            if entity.Type == (EntityType.ENTITY_VIS or 39)
                or entity.Type == (EntityType.ENTITY_GLUTTONY or 49) then
                local ok, animation=pcall(function() return string.lower(entity:GetSprite():GetAnimation()) end)
                if ok and string.find(animation,"attack",1,true) then
                    local horizontal=string.find(animation,"horiz",1,true)
                    local vertical=string.find(animation,"up",1,true) or string.find(animation,"down",1,true)
                        or string.find(animation,"vert",1,true)
                    if horizontal or vertical then
                        telegraphs[#telegraphs+1]={position=entity.Position,horizontal=horizontal~=nil}
                    end
                end
            end
            if entity.Type==(EntityType.ENTITY_EYE or 60) and (entity.Variant or 0)<=1 then
                -- Both ordinary and Bloodshot Eyes aim while their sprite is
                -- still named Rotate (observed in states 1 and 8). Waiting for
                -- a Shoot animation misses the damaging beam entirely. Keep
                -- strafing across their aim, including on navigation routes.
                -- Holy Eyes (variant 2) use a different attack and are excluded.
                local delta=player.Position-entity.Position
                local length=math.max(1,delta:Length())
                telegraphs[#telegraphs+1]={position=entity.Position,direction=delta*(1/length),
                    forwardOnly=true,clearance=(entity.Variant or 0)==1 and 52 or 42}
            end
        elseif entity.Type == EntityType.ENTITY_PROJECTILE then projectiles[#projectiles + 1] = entity
        else
            local laser = hostileLaser(entity)
            if laser then lasers[#lasers + 1] = laser end
        end
    end
    if #attackTargets==0 then attackTargets=enemies end
    local bouncePaths={}
    if room.GetGridCollision then
        for _,entity in ipairs(contacts) do
            if entity.Type==212 or (entity.Type==68 and entity.Variant==10) then
                local position,velocity=entity.Position,entity.Velocity
                local path={[0]=position}
                local radius=math.max(4,math.min(18,(entity.Size or 14)*.5))
                local wallOffsets={Vector(0,0),Vector(radius,0),Vector(-radius,0),Vector(0,radius),Vector(0,-radius)}
                local gridSize=room.GetGridSize and room:GetGridSize() or nil
                local wallCollision={}
                local function wallAt(point)
                    for _,offset in ipairs(wallOffsets) do
                        local index=room:GetGridIndex(point+offset)
                        if gridSize and (index<0 or index>=gridSize) then return true end
                        local value=wallCollision[index]
                        if value==nil then value=room:GetGridCollision(index);wallCollision[index]=value end
                        if value>=((GridCollisionClass and GridCollisionClass.COLLISION_WALL) or 4) then return true end
                    end
                    return false
                end
                for tick=1,10 do
                    for substep=1,2 do
                        local vx,vy=velocity.X,velocity.Y
                        if wallAt(position+Vector(vx,0)) then vx=-vx end
                        if wallAt(position+Vector(0,vy)) then vy=-vy end
                        velocity=Vector(vx,vy)
                        local nextPosition=position+velocity
                        if not wallAt(nextPosition) then position=nextPosition end
                    end
                    path[tick]=position
                end
                bouncePaths[entity]=path
            end
        end
    end
    -- Enemy/projectile trajectories are identical for every candidate in this
    -- callback. Retain native Vector arithmetic and reuse its exact results.
    local projectedPositions={}
    local function projectedPosition(entity,frames)
        local path=projectedPositions[entity]
        if not path then path={};projectedPositions[entity]=path end
        if not path[frames] then path[frames]=entity.Position+entity.Velocity*frames end
        return path[frames]
    end
    local function contactClearance(enemy,forecast,horizon)
        local separation=math.huge
        -- Wall rebounds are an additional possible trajectory. Retain the
        -- straight path too, since exact collision radii can differ by NPC.
        for mode=1,bouncePaths[enemy] and 2 or 1 do
            local previous=enemy.Position-player.Position
            separation=math.min(separation,previous:Length())
            for tick=1,horizon do
                local center=mode==2 and bouncePaths[enemy][tick] or projectedPosition(enemy,tick*2)
                local relative=center-forecast[tick]
                local segment=relative-previous
                local vv=segment.X*segment.X+segment.Y*segment.Y
                local fraction=vv>0.01 and math.max(0,math.min(1,-(previous.X*segment.X+previous.Y*segment.Y)/vv)) or 0
                separation=math.min(separation,(previous+segment*fraction):Length())
                previous=relative
            end
        end
        return separation
    end
    local tntThreat=tntBlastGuard and tntBlastGuard:danger(player)
    if #enemies == 0 and #contacts == 0 and #lasers == 0 and #projectiles == 0 and not tntThreat then return action.move, Vector(0, 0) end
    local explosive = player.HasCollectible and (player:HasCollectible(CollectibleType.COLLECTIBLE_EXPLOSIVO)
        or player:HasCollectible(CollectibleType.COLLECTIBLE_IPECAC)
        or (player:HasCollectible(273) and not player:HasCollectible(223) and not player:HasCollectible(375)))
    local safeDistance = explosive and 165 or 130
    local range = math.max(110, math.min(235, player.TearRange - 25))
    local function beamSeparation(beam,position)
        if beam.direction then
            local delta=position-beam.position
            if beam.forwardOnly and delta.X*beam.direction.X+delta.Y*beam.direction.Y<0 then return math.huge end
            return math.abs(delta.X*beam.direction.Y-delta.Y*beam.direction.X)
        end
        return beam.horizontal and math.abs(position.Y-beam.position.Y)
            or math.abs(position.X-beam.position.X)
    end
    local moves = { Vector(0, 0), Vector(1, 0), Vector(-1, 0), Vector(0, 1), Vector(0, -1),
        Vector(0.7071, 0.7071), Vector(0.7071, -0.7071), Vector(-0.7071, 0.7071), Vector(-0.7071, -0.7071) }
    local bestMove, bestScore = Vector(0, 0), math.huge
    -- Ordinary projectile damage respects the engine's existing post-hit
    -- immunity. Forecast the moment that immunity ends instead of treating
    -- every bullet as immediately lethal throughout a narrow trap corridor.
    -- GetDamageCooldown decreases by 2 per game frame in the native audit;
    -- each forecast step covers 2 game frames, hence 4 cooldown units.
    -- Floor hazards, explosives, telegraphs and contact guards stay active.
    local bulletImmunity=player.GetDamageCooldown and math.max(0,player:GetDamageCooldown()-4) or 0
    local function fixedTurret(enemy)
        return (enemy.Type==(EntityType.ENTITY_HORF or 12) or enemy.Type==(EntityType.ENTITY_PSY_HORF or 248))
            and (enemy.Variant or 0)==0
            and enemy.Velocity and enemy.Velocity:Length()<0.2
    end
    -- A locally clear retreat into a one-exit rock pocket lets chasing NPCs
    -- seal its entrance. Apply this to safety rewrites as well as waypoints.
    local pocketCostCache={}
    local function pocketCost(position)
        if #enemies==0 or not room.GetGridWidth or not room.GetGridSize then return 0 end
        local threatened=false
        for _,enemy in ipairs(enemies) do
            if enemy.Type~=27 and enemy.Type~=204 and not fixedTurret(enemy) and position:Distance(enemy.Position)<300 then
                threatened=true break
            end
        end
        if not threatened then return 0 end
        local index=room:GetGridIndex(position)
        if pocketCostCache[index]~=nil then return pocketCostCache[index] end
        local width,size=room:GetGridWidth(),room:GetGridSize()
        local exits=0
        for _,neighbor in ipairs({index-width,index+width,index-1,index+1}) do
            if neighbor>=0 and neighbor<size and
                (math.abs(neighbor-index)==width or math.floor(neighbor/width)==math.floor(index/width))
                and room:GetGridPath(neighbor)<1000 then exits=exits+1 end
        end
        local cost=exits<=1 and 30000 or 0
        pocketCostCache[index]=cost
        return cost
    end
    local graceEscape=false
    if player.GetDamageCooldown and player:GetDamageCooldown()>=48 then
        local touching=false
        for _,enemy in ipairs(enemies) do
            if player.Position:Distance(enemy.Position)<(player.Size or 10)+(enemy.Size or 12)+24 then
                touching=true break
            end
        end
        graceEscape=touching or pocketCost(player.Position)>0
        if graceEscape then
            -- The real Globin death stayed in a sealed alcove throughout
            -- successive post-hit grace periods. Leave through the ordinary
            -- NPC contact while the game's existing immunity still lasts.
            -- Ground hazards, bullets, beams and death blasts remain guarded.
            local hazardousContacts={}
            for _,enemy in ipairs(contacts) do
                if not isCombatEnemy(enemy) or deathBlasts[enemy] then
                    hazardousContacts[#hazardousContacts+1]=enemy
                end
            end
            contacts=hazardousContacts
        end
    end
    local routeMove = not graceEscape and not ignoreWaypoint and action.waypoint and followGridRoute(player, action.waypoint, 10) or nil
    if not ignoreWaypoint and action.mode=="navigate" then
        local slot=tonumber(string.match(action.id or "","^enter_door_(%d+)$"))
        if slot then
            local target=actualDoorPosition(room,slot)
            local delta,side=target-player.Position,doorSlotDirection(slot)
            if delta:Length()>70 then routeMove=followGridRoute(player,target,10)
            elseif math.abs(side.X)>.5 and math.abs(delta.Y)>12 then
                routeMove=Vector(0,delta.Y>0 and 1 or -1)
            elseif math.abs(side.Y)>.5 and math.abs(delta.X)>12 then
                routeMove=Vector(delta.X>0 and 1 or -1,0)
            else routeMove=side end
        end
    end
    local forecastCollision={}
    local scoringOffsets={Vector(0,0),Vector(11,0),Vector(-11,0),Vector(0,11),Vector(0,-11)}
    local gpuForecasts,gpuDistances,gpuMainIndex,gpuBounceIndex=nil,nil,{},{}
    if mod and mod.gpuGeometry and mod.gpuGeometry:wants(#projectiles+#contacts) and #projectiles+#contacts*2<=256 then
        local tracks={}
        local function addTrack(entity,first,initial,bounce)
            local path={[0]=entity.Position}
            for tick=1,10 do path[tick]=bounce and bounce[tick] or projectedPosition(entity,tick*2) end
            tracks[#tracks+1]={path=path,first=first,initial=initial}
            return #tracks
        end
        for _,projectile in ipairs(projectiles) do
            gpuMainIndex[projectile]=addTrack(projectile,math.min(11,math.max(1,math.ceil(bulletImmunity/4))),bulletImmunity<=0)
        end
        for _,enemy in ipairs(contacts) do
            gpuMainIndex[enemy]=addTrack(enemy,1,true)
            if bouncePaths[enemy] then gpuBounceIndex[enemy]=addTrack(enemy,1,true,bouncePaths[enemy]) end
        end
        if #tracks>0 then
            gpuForecasts={}
            for index,move in ipairs(moves) do
                local forecast=movementForecast(player,move,10,room,forecastCollision)
                forecast[0]=player.Position;gpuForecasts[index]=forecast
            end
            local profile=mod.runtimeProfile;local started=Isaac.GetTime()
            gpuDistances=mod.gpuGeometry:distances({frame=game:GetFrameCount(),seed=startSeed(),
                room=game:GetLevel():GetCurrentRoomIndex(),stage=game:GetLevel():GetStage()},gpuForecasts,tracks)
            profile:detail("gpu_geometry_transport",Isaac.GetTime()-started)
        end
    end
    for moveIndex, move in ipairs(moves) do
        local score = 0
        local profile=mod and mod.runtimeProfile
        local started=profile and Isaac.GetTime()
        -- Known unsafe floor directions are constraints. A weighted penalty
        -- could otherwise choose a spike to reduce predicted bullet risk.
        if move:Length() > 0.5 and not safeMoveCandidate(player, move, false) then score = math.huge end
        if profile then profile:detail("candidate_safety",Isaac.GetTime()-started) end
        local forecast=gpuForecasts and gpuForecasts[moveIndex] or movementForecast(player,move,10,room,forecastCollision)
        score=score+math.max(pocketCost(forecast[3]),pocketCost(forecast[6]),pocketCost(forecast[10]))
        if tntThreat then
            for _,tick in ipairs({2,5,9}) do
                score=score+math.max(0,-tntBlastGuard:clearance(player,forecast[tick]))*10000
            end
        end
        for _, projectile in ipairs(projectiles) do
            local radius = (player.Size or 10) + (projectile.Size or 5) + 6
            local gpuSeparation=gpuDistances and gpuDistances[moveIndex][gpuMainIndex[projectile]]
            -- Native Vector arithmetic rounds to float32. Recheck the original
            -- CPU path around every collision boundary; no threat is dropped.
            local useGpu=gpuSeparation and math.abs(gpuSeparation-radius)>.25
            local previous=projectile.Position-player.Position
            local separation=useGpu and gpuSeparation or (bulletImmunity>0 and math.huge or previous:Length())
            for tick=1,useGpu and 0 or 10 do
                local relative=projectedPosition(projectile,tick*2)-forecast[tick]
                local segment=relative-previous
                local vv=segment.X*segment.X+segment.Y*segment.Y
                local fraction=vv>0.01 and math.max(0,math.min(1,-(previous.X*segment.X+previous.Y*segment.Y)/vv)) or 0
                if tick*4>=bulletImmunity then
                    separation=math.min(separation,(previous+segment*fraction):Length())
                end
                previous=relative
            end
            if separation < radius then score = score + (radius - separation + 1) * 6000 end
        end
        -- Fast charging enemies can cross Isaac between sampled endpoints.
        -- Check their swept relative path just as for projectiles.
        for _,enemy in ipairs(contacts) do
            local radius=deathBlasts[enemy] and 145
                or ((player.Size or 10)+math.min(50,enemy.Size or 12)+10)
            local separation=gpuDistances and gpuDistances[moveIndex][gpuMainIndex[enemy]]
            if separation and gpuBounceIndex[enemy] then
                separation=math.min(separation,gpuDistances[moveIndex][gpuBounceIndex[enemy]])
            end
            if not separation or math.abs(separation-radius)<=.25 then separation=contactClearance(enemy,forecast,10) end
            if separation<radius then score=score+(radius-separation+1)*6000 end
        end
        for _, tick in ipairs({ 2, 5, 9 }) do
            local position = forecast[tick]
            if timedSpikeNavigator and not player.CanFly then
                score=score+timedSpikeNavigator:exposure(position,game:GetFrameCount()+tick)*6000
            end
            for _, beam in ipairs(telegraphs) do
                local separation=beamSeparation(beam,position)
                local radius=beam.clearance or 42
                if separation<radius then score=score+(radius+1-separation)*3000 end
            end
            for _, laser in ipairs(lasers) do
                local separation = laserClearance(laser, position, tick)
                local radius = (player.Size or 10) + math.min(28, math.max(4, laser.Size or 10)) + 12
                if separation < radius then score = score + (radius - separation + 1) * 9000 end
                score = score + math.max(0, radius + 28 - separation) * 15
            end
            for _, offset in ipairs(scoringOffsets) do
                if room:GetGridPath(room:GetGridIndex(position + offset)) >= 1000 then score = score + 4000 end
            end
            for _, enemy in ipairs(contacts) do
                local future = projectedPosition(enemy,math.min(tick,6)*2)
                local separation = position:Distance(future)
                if bouncePaths[enemy] then separation=math.min(separation,position:Distance(bouncePaths[enemy][math.min(tick,6)])) end
                local radius = (player.Size or 10) + math.min(40, enemy.Size or 12) + 8
                if separation < radius then score = score + (radius - separation + 1) * 1500 end
                score = score + math.max(0, safeDistance - separation) * 5
                if reactiveChargers[enemy] then
                    -- The real charge changed direction while the routed
                    -- firing lane was close. Reserve reaction space around
                    -- both the observed body and its linear forecast.
                    score = score + math.max(0, 185 - math.min(separation,
                        position:Distance(enemy.Position))) * 20
                end
            end
            for _, projectile in ipairs(tick*4>=bulletImmunity and projectiles or {}) do
                local separation = position:Distance(projectedPosition(projectile,tick*2))
                local radius = (player.Size or 10) + (projectile.Size or 5) + 6
                if separation < radius then score = score + (radius - separation + 1) * 2500 end
                score = score + math.max(0, 44 - separation) * 9
            end
        end
        local position = forecast[6]
        local attackScore = #enemies > 0 and math.huge or (move - action.move):Length() * 40
        for _, enemy in ipairs(attackTargets) do
            local delta = projectedPosition(enemy,8) - position
            local distance = delta:Length()
            local alignment = math.min(math.abs(delta.X), math.abs(delta.Y))
            local value = math.max(0, alignment - 8) * 2.5
                + math.max(0, distance - range) * 0.8 + math.max(0, safeDistance - distance) * 1.2
            if finishGlobins[enemy] then value=value-250 end
            if not clearTearLine(room, position, enemy.Position) then value = value + 500 end
            if value < attackScore then attackScore = value end
        end
        score = score + attackScore
        if routeMove and routeMove:Length() > 0.5 then score = score + (move - routeMove):Length() * 220 end
        if move:Length() > 0.5 then score = score + 1.5 end
        score = score + (move - lastResolvedMove):Length() * 0.8
        if score < bestScore then bestMove, bestScore = move, score end
    end
    local bestAim, aimScore, aimTarget = Vector(0, 0), math.huge, -1
    local aimFrame = game.GetFrameCount and game:GetFrameCount() or 0
    for _, enemy in ipairs(attackTargets) do
        local distance = enemy.Position:Distance(player.Position)
        local aimProfile=mod and mod.weaponControl and mod.weaponControl:profile(player,weaponKind(player)) or {lead=10}
        local lead = math.min(aimProfile.lead, distance / math.max(4, (player.ShotSpeed or 1) * 10))
        local delta = projectedPosition(enemy,lead) - player.Position
        local minor = math.min(math.abs(delta.X), math.abs(delta.Y))
        local score = minor * 7 + distance * 0.1
        if not clearTearLine(room, player.Position, enemy.Position) then score = score + 1000 end
        local npc = enemy.ToNPC and enemy:ToNPC() or nil
        local finishGlobin=finishGlobins[enemy]
        if finishGlobin then score=score-650
        elseif npc and not npc:IsVulnerableEnemy() then score = score + 2000 end
        if enemy.Index and enemy.Index==combatAimTargetId and aimFrame-combatAimLockFrame<60 then
            score=score-120
        end
        -- Shooting a closed Host extends its closed phase. Wait for the
        -- native vulnerable window rather than suppressing it indefinitely.
        local closedHost = (enemy.Type == 27 or enemy.Type == 204) and (enemy.Variant or 0) == 0
            and npc and not npc:IsVulnerableEnemy()
        if not closedHost and score < aimScore then
            aimScore = score
            aimTarget = enemy.Index or -1
            bestAim = math.abs(delta.X) >= math.abs(delta.Y)
                and Vector(delta.X >= 0 and 1 or -1, 0) or Vector(0, delta.Y >= 0 and 1 or -1)
        end
    end
    if aimTarget~=combatAimTargetId then combatAimLockFrame=aimFrame end
    combatAimTargetId=aimTarget
    if routeMove then
        local immediateThreat = false
        local forecast=movementForecast(player,routeMove,10,room,forecastCollision)
        for _,tick in ipairs({3,6,10}) do
            if pocketCost(forecast[tick])>0 then immediateThreat=true break end
        end
        if tntThreat then
            for tick=1,10 do
                if tntBlastGuard:clearance(player,forecast[tick])<0 then immediateThreat=true break end
            end
        end
        for _, beam in ipairs(telegraphs) do
            for tick=1,8 do
                local separation=beamSeparation(beam,forecast[tick])
                if separation<(beam.clearance or 42)+6 then immediateThreat=true break end
            end
            if immediateThreat then break end
        end
        for _, enemy in ipairs(contacts) do
            local contactDistance=deathBlasts[enemy] and 155 or explosive and safeDistance
                or ((player.Size or 10)+math.min(50,enemy.Size or 12)+26)
            if isMovingSpikeTrap(enemy) then
                -- Narrow trap corridors cannot retain the 110px enemy
                -- comfort gap. Swept prediction still reserves body space.
                contactDistance=(player.Size or 10)+math.min(50,enemy.Size or 12)+18
            elseif reactiveChargers[enemy] then
                contactDistance=math.max(contactDistance,185)
                for tick=1,8 do
                    if forecast[tick]:Distance(enemy.Position)<185 then immediateThreat=true break end
                end
            elseif fixedTurret(enemy) then
                -- A fixed Horf cannot chase into a corridor. Its actual tears
                -- still veto this route below; the mobile comfort radius
                -- must not permanently block the only reachable firing lane.
                contactDistance=(player.Size or 10)+math.min(50,enemy.Size or 12)+26
            elseif not (enemy.Type==27 or enemy.Type==204) then
                -- Routed approaches must leave room to react when a walking
                -- enemy changes direction. Hosts retain their proven short
                -- alcove route; floor, bullet and laser guards still apply.
                contactDistance=math.max(contactDistance,110)
            elseif (enemy.Variant or 0)==0 then
                -- A stationary Host can expose only one adjacent firing cell
                -- between pits and rocks. Preserve body clearance there.
                contactDistance=(player.Size or 10)+math.min(50,enemy.Size or 12)+8
            end
            if contactClearance(enemy,forecast,8)<contactDistance then immediateThreat=true end
            if immediateThreat then break end
        end
        for _, projectile in ipairs(projectiles) do
            local previous=projectile.Position-player.Position
            for tick=1,10 do
                local relative=projectedPosition(projectile,tick*2)-forecast[tick]
                local segment=relative-previous
                local vv=segment.X*segment.X+segment.Y*segment.Y
                local fraction=vv>0.01 and math.max(0,math.min(1,-(previous.X*segment.X+previous.Y*segment.Y)/vv)) or 0
                if tick*4>=bulletImmunity and (previous+segment*fraction):Length()<(player.Size or 10)+(projectile.Size or 5)+20 then
                    immediateThreat=true break
                end
                previous=relative
            end
            if immediateThreat then break end
        end
        for _, laser in ipairs(lasers) do
            for _, tick in ipairs({2, 5, 9}) do
                if laserClearance(laser, forecast[tick], tick)
                    < (player.Size or 10) + math.min(28, math.max(4, laser.Size or 10)) + 24 then
                    immediateThreat = true break
                end
            end
        end
        -- The route turns at its next cell centre. Extrapolating its current
        -- direction straight through that turn would falsely predict a wall.
        if not immediateThreat then bestMove = routeMove end
    end
    return bestMove, bestAim
end

local observedBombEscape=nil
local function escapeObservedBombs(player)
    local bombs={}
    for _,entity in ipairs(Isaac.GetRoomEntities()) do
        local threat=trackingBombInfo(entity,player)
        if threat then bombs[#bombs+1]=threat end
    end
    if #bombs==0 then observedBombEscape=nil return nil end
    local identities={}
    for index,bomb in ipairs(bombs) do identities[#identities+1]=tostring(bomb.id or index) end
    table.sort(identities)
    local key=(currentRoomKey and currentRoomKey() or "room")..":"..table.concat(identities,",")
    local frame=game and game.GetFrameCount and game:GetFrameCount() or 0
    if observedBombEscape and observedBombEscape.key~=key then observedBombEscape=nil end
    local bestMove,bestScore=Vector(0,0),-math.huge
    for _,move in ipairs({Vector(1,0),Vector(-1,0),Vector(0,1),Vector(0,-1),
        Vector(.7071,.7071),Vector(.7071,-.7071),Vector(-.7071,.7071),Vector(-.7071,-.7071)}) do
        -- Judge all explosives together: rejecting every step which approaches
        -- any one of two bombs can incorrectly leave Isaac standing between them.
        if safeMoveCandidate(player,move,false,true,nil,true) then
            local forecast=movementForecast(player,move,12)
            local worst,early=math.huge,math.huge
            for _,bomb in ipairs(bombs) do
                local position=Vector(bomb.pos.x,bomb.pos.y)
                local velocity=Vector(bomb.vel.x,bomb.vel.y)
                worst=math.min(worst,forecast[12]:Distance(position+velocity*24)-bomb.radius)
                early=math.min(early,forecast[5]:Distance(position+velocity*10)-bomb.radius)
            end
            local score=worst+early*.25
            if observedBombEscape and frame-observedBombEscape.frame<45 then
                -- A bomb spawning under Isaac can push him slightly each
                -- frame. Do not reverse escape for tiny position changes.
                local previous=observedBombEscape.move
                score=score+(move.X*previous.X+move.Y*previous.Y)*55
            end
            if score>bestScore then bestMove,bestScore=move,score end
        end
    end
    if bestMove and (not observedBombEscape or frame-observedBombEscape.frame>=45
        or bestMove.X~=observedBombEscape.move.X or bestMove.Y~=observedBombEscape.move.Y) then
        observedBombEscape={key=key,frame=frame,move=bestMove}
    end
    return bestMove
end

local function resolveSafeMove(player, navigationBlocked)
    combatLiveAim = nil
    gridRouteControlled = false
    gridEscapeActive = false
    local desired = action.move
    local room = game:GetRoom()
    local roomIndex = canonicalRoomIndex(game:GetLevel())
    -- Actual raised-floor contact owns escape even while a temporal route is
    -- waiting or invalid. Zero input still leaves native inertia moving.
    local gridEscape = escapeGridDanger(player)
    if gridEscape then gridEscapeActive = true return gridEscape end
    local liveProjectile, liveLaser = false, false
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if entity.Type == EntityType.ENTITY_PROJECTILE then liveProjectile = true end
        if hostileLaser(entity) then liveLaser = true end
    end
    timedSpikeNavigator.waiting=false
    if timedSpikeNavigator.active and timedSpikeNavigator.key==currentRoomKey() and not hasCombatEnemy()
        and not liveProjectile and not liveLaser
        and not bombStillLive() and not nearestTrackingBomb(player) and not tntBlastGuard:danger(player) then
        local temporal=followGridRoute(player,timedSpikeNavigator.target,8)
        if timedSpikeNavigator.active then return temporal or Vector(0,0) end
    end
    local stompEscape = escapeStomp(player)
    if stompEscape then return stompEscape end
    if bombStillLive() and bombPosition
        and player.Position:Distance(bombPosition) < 145 then
        -- Keep the preflighted escape direction. Re-deriving it from current
        -- velocity turned a slight drift toward the wall into a fatal U-turn.
        if safeMoveCandidate(player, bombRetreatDirection, false, true) then
            return bombRetreatDirection
        end
        for _, side in ipairs({ Vector(-bombRetreatDirection.Y, bombRetreatDirection.X),
                                Vector(bombRetreatDirection.Y, -bombRetreatDirection.X) }) do
            if (player.Position + side * 28):Distance(bombPosition)
                > player.Position:Distance(bombPosition) + 1
                and safeMoveCandidate(player, side, false, true) then return side end
        end
        return Vector(0, 0)
    end
    local trackingBomb = nearestTrackingBomb(player)
    if trackingBomb then
        return escapeObservedBombs(player) or Vector(0,0)
    end
    if utilityButtons[ButtonAction.ACTION_DROP] then return Vector(0, 0) end
    if (pyroHealPending or game:GetFrameCount() - lastPyroHealFrame < 100)
        and player:HasCollectible(CollectibleType.COLLECTIBLE_PYROMANIAC) then return Vector(0, 0) end
    if navigationBlocked or game:GetFrameCount()-lastActionFrame>45
        or (action.sourceRoomIndex >= 0 and action.sourceRoomIndex ~= roomIndex) then
        -- Reject stale/reverse door motion, but never freeze in front of a
        -- moving trap or projectile merely because the room is already clear.
        local liveThreat=hasCombatEnemy()
        for _,entity in ipairs(Isaac.GetRoomEntities()) do
            if hostileLaser(entity) or ((isMovingSpikeTrap(entity)
                or entity.Type==(EntityType.ENTITY_ETERNALFLY or 96)
                or entity.Type==EntityType.ENTITY_PROJECTILE)
                and entity.Position:Distance(player.Position)<220) then liveThreat=true end
        end
        if liveThreat then
            local move,aim=predictiveCombatMove(player,true)
            combatLiveAim=aim
            return move
        end
        return Vector(0,0)
    end
    local nearbyCombatEnemy = false
    if action.mode == "hazard" then
        for _, enemy in ipairs(Isaac.GetRoomEntities()) do
            if isCombatEnemy(enemy) and (enemy.Position:Distance(player.Position) < 95
                or (enemy.Position:Distance(player.Position) < 235 and clearTearLine(room, player.Position, enemy.Position))) then
                nearbyCombatEnemy = true
                break
            end
        end
    end
    local ordinaryTarget = action.mode == "item" or action.mode == "pickup" or action.mode == "navigate"
        or action.mode == "strategy_hold" or action.mode == "strategy_macro"
        or action.mode == "wait" or action.mode == "chest" or action.mode == "bomb_wall"
        or (action.mode == "bomb" and not string.match(action.id or "", "^bomb_boss_"))
    local movingContactThreat = false
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if hostileLaser(entity) then liveLaser = true end
        if (isMovingSpikeTrap(entity) or entity.Type == (EntityType.ENTITY_ETERNALFLY or 96))
            and player.Position:Distance(entity.Position)<200 then movingContactThreat=true end
    end
    if ((action.mode == "combat" or nearbyCombatEnemy or ordinaryTarget) and hasCombatEnemy()) or liveLaser or liveProjectile or movingContactThreat
        or (tntBlastGuard and tntBlastGuard:danger(player)) then
        local move, aim = predictiveCombatMove(player)
        -- Dodging an unshootable trap changes movement, but its empty combat
        -- aim must not suppress a valid grid-obstacle shot below.
        if (action.mode~="hazard" and action.mode~="tnt") or hasCombatEnemy() then combatLiveAim = aim end
        return move
    end
    if action.mode == "recovery" and action.waypoint then
        local delta = action.waypoint - player.Position
        if delta:Length() <= 12 then return Vector(0, 0) end
        local primary = math.abs(delta.X) >= math.abs(delta.Y)
            and Vector(delta.X >= 0 and 1 or -1, 0)
            or Vector(0, delta.Y >= 0 and 1 or -1)
        local secondary = math.abs(primary.X) > 0
            and Vector(0, delta.Y >= 0 and 1 or -1)
            or Vector(delta.X >= 0 and 1 or -1, 0)
        if safeMoveCandidate(player, primary, false) then return primary end
        if math.abs(primary.X) > 0 and math.abs(delta.Y) > 12
            and safeMoveCandidate(player, secondary, false) then return secondary end
        if math.abs(primary.Y) > 0 and math.abs(delta.X) > 12
            and safeMoveCandidate(player, secondary, false) then return secondary end
        return Vector(0, 0)
    end
    if action.mode == "strategy_macro" and action.waypoint then
        local index=room:GetGridIndex(action.waypoint)
        if not strategyControl:macroAllowed(index,player) then return Vector(0,0) end
        return followGridRoute(player,action.waypoint,4) or Vector(0,0)
    end
    local buttonId = tonumber(string.match(action.id or "", "^press_button_(%-?%d+)$"))
    if action.mode == "button" and buttonId then
        local buttonIndex = buttonId <= -100000 and (-100000 - buttonId) or buttonId
        local button = room:GetGridEntity(buttonIndex)
        local event = gridEvent(button, buttonIndex)
        if not event or event.kind ~= "button" or event.triggered then return Vector(0, 0) end
        local delta = button.Position - player.Position
        if delta:Length() <= 12 then return Vector(0, 0) end
        if delta:Length() > 25 then
            local routed = followGridRoute(player, button.Position, 10)
            if routed then return routed end
        end
        if action.move:Length() > 0.5 then return firstSafeMove(player, action.move, false) end
        return firstSafeMove(player, math.abs(delta.X) >= math.abs(delta.Y)
            and Vector(delta.X >= 0 and 1 or -1, 0)
            or Vector(0, delta.Y >= 0 and 1 or -1), false)
    end
    local tntId = tonumber(string.match(action.id or "", "^shoot_tnt_(%-?%d+)$"))
    if action.mode == "tnt" and tntId then
        local tntIndex = tntId <= -100000 and (-100000 - tntId) or tntId
        local tnt = room:GetGridEntity(tntIndex)
        local event = gridEvent(tnt, tntIndex)
        if not event or event.kind ~= "tnt" or not event.active then return Vector(0, 0) end
        if action.waypoint and player.Position:Distance(action.waypoint) > 10 then
            local route = followGridRoute(player, action.waypoint, 10)
            if route then gridRouteControlled = true; return route end
        end
        local distance = tnt.Position:Distance(player.Position)
        if distance < 135 then
            local away = player.Position - tnt.Position
            return firstSafeMove(player, math.abs(away.X) >= math.abs(away.Y)
                and Vector(away.X >= 0 and 1 or -1, 0)
                or Vector(0, away.Y >= 0 and 1 or -1), false)
        end
        return firstSafeMove(player, action.move, false)
    end
    local bossExitGrid = tonumber(string.match(action.id or "", "^enter_boss_exit_(%-?%d+)$"))
    local bossExitNavigation = action.mode == "boss_exit" and bossExitGrid ~= nil
    if bossExitNavigation then
        local trapdoor = room:GetGridEntity(bossExitGrid)
        local typeOk, trapdoorType = pcall(function() return trapdoor and trapdoor:GetType() or -1 end)
        if not typeOk then trapdoorType = -1 end
        if not trapdoor or trapdoorType ~= GRID_TRAPDOOR_TYPE then return Vector(0, 0) end
        local trapdoorPosition = trapdoor.Position
        local delta = trapdoorPosition - player.Position
        -- A newly spawned exit can stay closed while Isaac stands over it.
        -- Step off normally so the game can play its opening animation.
        local spriteOk, trapdoorSprite = pcall(function() return trapdoor:GetSprite() end)
        if spriteOk and trapdoorSprite and trapdoorSprite:GetAnimation() == "Open Animation" then
            return Vector(0, 0)
        end
        local closed = spriteOk and trapdoorSprite and trapdoorSprite:GetAnimation() == "Closed"
        if closed then
            if delta:Length() >= 85 then return Vector(0, 0) end
            local away = player.Position - trapdoorPosition
            if math.abs(away.X) > math.abs(away.Y) then
                desired = Vector(away.X >= 0 and 1 or -1, 0)
            else
                desired = Vector(0, away.Y >= 0 and 1 or -1)
            end
            return firstSafeMove(player, desired, false)
        end
        -- The native fall trigger is smaller than a 24px approach radius.
        -- Continue the ordinary input until the body reaches the exit centre.
        if delta:Length() <= 8 then return Vector(0, 0) end
        if delta:Length() > 60 then
            local routed = followGridRoute(player, trapdoorPosition, 10)
            if routed then return routed end
        end
        if math.abs(delta.X) >= math.abs(delta.Y) then
            desired = Vector(delta.X >= 0 and 1 or -1, 0)
        else
            desired = Vector(0, delta.Y >= 0 and 1 or -1)
        end
        return firstSafeMove(player, desired, false)
    end
    -- Use the engine's door position for navigation. Room grid indices around
    -- doors can be rotated by room shapes, which previously sent the player
    -- away from a right-hand exit.
    local doorSlot = tonumber(string.match(action.id or "", "^enter_door_(%d+)$"))
    local navigationDoor = action.mode == "navigate" and doorSlot ~= nil
    if action.mode == "navigate" and doorSlot then
        -- Use the stable slot side, but first align the perpendicular axis
        -- with the actual door center. Pressing only toward a right/left door
        -- while Isaac is above or below its center traps him against the wall.
        local doorPosition = actualDoorPosition(room, doorSlot)
        local doorSide = doorSlotDirection(doorSlot)
        local delta = doorPosition - player.Position
        if delta:Length() > 75 then
            local routed = followGridRoute(player, doorPosition, 10)
            if routed then return routed end
        end
        -- A remote/grid instruction can arrive several frames after Isaac
        -- reaches the narrow horizontal door lane. Use live coordinates to
        -- start crossing immediately instead of overshooting and oscillating.
        if math.abs(doorSide.X) > 0.5 and math.abs(delta.X) > 70
            and math.abs(delta.Y) <= 42 and safeMoveCandidate(player, doorSide, false) then
            desired = doorSide
        elseif delta:Length() > 90 and action.move:Length() > 0.5 then
            desired = action.move
        elseif math.abs(doorSide.X) > 0.5 and math.abs(delta.Y) > 12 then
            desired = Vector(0, delta.Y >= 0 and 1 or -1)
        elseif math.abs(doorSide.Y) > 0.5 and math.abs(delta.X) > 12 then
            desired = Vector(delta.X >= 0 and 1 or -1, 0)
        else
            desired = doorSide
        end
    end
    if navigationDoor then
        if hasCombatEnemy() then return Vector(0, 0) end
        local doorDistance = player.Position:Distance(actualDoorPosition(room, doorSlot))
        local entering = doorDistance <= 70 and desired.X == doorSlotDirection(doorSlot).X and desired.Y == doorSlotDirection(doorSlot).Y
        -- During door alignment a fallback side-step can push Isaac into the
        -- threshold wall while the requested perpendicular move is ignored.
        -- Let the controller choose a new approach instead of claiming that
        -- the door itself is permanently unreachable.
        if not entering then
            return safeMoveCandidate(player, desired, false) and desired or Vector(0, 0)
        end
        return firstSafeMove(player, desired, true)
    end
    local projectileMove = nil
    local projectileDistance = nil
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if entity.Type == EntityType.ENTITY_PROJECTILE then
            local delta = player.Position - entity.Position
            local distance = delta:Length()
            local velocity = entity.Velocity
            local closing = delta.X * velocity.X + delta.Y * velocity.Y > 0.25
            if distance <= 120 and (closing or distance <= 70) and (not projectileDistance or distance < projectileDistance) then
                projectileDistance = distance
                if math.abs(velocity.X) >= math.abs(velocity.Y) and math.abs(velocity.X) > 0.1 then
                    projectileMove = Vector(0, velocity.X >= 0 and 1 or -1)
                elseif math.abs(velocity.Y) > 0.1 then
                    projectileMove = Vector(velocity.Y >= 0 and -1 or 1, 0)
                else
                    projectileMove = Vector(delta.X >= 0 and 1 or -1, 0)
                end
            end
        end
    end
    if not projectileMove then
        for _, entity in ipairs(Isaac.GetRoomEntities()) do
            if isCombatEnemy(entity) then
                local velocity = entity.Velocity
                local speed = velocity:Length()
                local toPlayer = player.Position - entity.Position
                local approaching = toPlayer.X * velocity.X + toPlayer.Y * velocity.Y > 0
                local projected = entity.Position + velocity * 10
                if speed >= 3.5 and approaching and toPlayer:Length() < 190
                    and projected:Distance(player.Position) < 80 then
                    local side = Vector(-velocity.Y, velocity.X)
                    if side:Length() > 0 then
                        side = math.abs(side.X) >= math.abs(side.Y)
                            and Vector(side.X >= 0 and 1 or -1, 0)
                            or Vector(0, side.Y >= 0 and 1 or -1)
                        local opposite = Vector(-side.X, -side.Y)
                        local first = player.Position + side * 40
                        local second = player.Position + opposite * 40
                        if first:Distance(projected) < second:Distance(projected) then side = opposite end
                        projectileMove = firstSafeMove(player, side, false)
                    end
                    break
                end
            end
        end
    end
    local pickupId = tonumber(string.match(action.id or "", "^take_[a-z]+_(%-?%d+)$"))
    if not pickupId then pickupId = tonumber(string.match(action.id or "", "^open_chest_(%-?%d+)$")) end
    if (action.mode == "item" or action.mode == "shop" or action.mode == "pickup" or action.mode == "chest") and pickupId then
        local target = nil
        for _, entity in ipairs(Isaac.GetRoomEntities()) do
            if entity.Type == EntityType.ENTITY_PICKUP and entity.Index == pickupId then
                target = entity
                break
            end
        end
        if target then
            local delta = target.Position - player.Position
            if delta:Length() > 65 then
                local routed = followGridRoute(player, target.Position, 10)
                if routed then return routed end
            end
            local direct = delta:Length() <= 100
            if direct and delta:Length() > 0 then
                local direction = delta / delta:Length()
                for step = 8, delta:Length(), 8 do
                    if room:GetGridPath(room:GetGridIndex(player.Position + direction * step)) >= 1000 then direct = false break end
                end
            end
            -- Python's move_towards uses the room grid to route around rocks
            -- and other blockers. Do not overwrite that first path step with
            -- a direct line toward the pickup; doing so makes reachable items
            -- look stuck and causes the controller to abandon them.
            if direct then
                desired = delta:Length() <= 10 and Vector(0, 0)
                    or (math.abs(delta.X) >= math.abs(delta.Y)
                        and Vector(delta.X >= 0 and 1 or -1, 0) or Vector(0, delta.Y >= 0 and 1 or -1))
            elseif action.move:Length() > 0.5 then
                desired = action.move
            elseif math.abs(delta.X) > 16 or math.abs(delta.Y) > 16 then
                if math.abs(delta.X) >= math.abs(delta.Y) then
                    desired = Vector(delta.X >= 0 and 1 or -1, 0)
                else
                    desired = Vector(0, delta.Y >= 0 and 1 or -1)
                end
            else
                desired = Vector(0, 0)
            end
        else
            -- The pickup was collected or despawned; wait for the next state
            -- rather than following a stale grid direction into an obstacle.
            desired = Vector(0, 0)
        end
    end
    local hazardId = tonumber(string.match(action.id or "", "^clear_hazard_(%-?%d+)$"))
    local hazardTarget = nil
    if action.mode == "hazard" and hazardId then
        for _, entity in ipairs(Isaac.GetRoomEntities()) do
            if entity.Index == hazardId and liveHazardKind(entity) then
                hazardTarget = entity
                break
            end
        end
        if not hazardTarget and hazardId <= -100000 then
            local gridIndex = -100000 - hazardId
            local grid = room:GetGridEntity(gridIndex)
            if liveGridHazardKind(grid) then hazardTarget = grid end
        end
        -- Python may request a small lateral correction to line up a
        -- cardinal tear. It must never become a direct contact move.
        desired = action.move
    end
    local bombId = tonumber(string.match(action.id or "", "^bomb_hazard_(%-?%d+)$"))
    local bombTarget = nil
    if action.mode == "bomb_wall" then
        if not action.bombSite then return Vector(0, 0) end
        local delta = action.bombSite - player.Position
        if delta:Length() <= 14 then return Vector(0, 0) end
        if action.move:Length() > 0.5 then return firstSafeMove(player, action.move, false) end
        return firstSafeMove(player, math.abs(delta.X) >= math.abs(delta.Y)
            and Vector(delta.X >= 0 and 1 or -1, 0)
            or Vector(0, delta.Y >= 0 and 1 or -1), false)
    end
    if action.mode == "bomb" and bombId then
        for index = 0, room:GetGridSize() - 1 do
            if -100000 - index == bombId then
                local grid = room:GetGridEntity(index)
                local kind=liveGridHazardKind(grid)
                if kind=="xrock" or kind=="passage_rock" or bombOnlyFireKind(kind) then bombTarget=grid end
                break
            end
        end
        if not bombTarget then
            for _,entity in ipairs(Isaac.GetRoomEntities()) do
                if entity.Index==bombId and bombOnlyFireKind(liveHazardKind(entity)) then bombTarget=entity break end
            end
        end
        if not bombTarget then return Vector(0, 0) end
        if not action.bombSite then return Vector(0, 0) end
        local delta = action.bombSite - player.Position
        if delta:Length() <= 14 then return Vector(0, 0) end
        if action.move:Length() > 0.5 then return firstSafeMove(player, action.move, false) end
        return firstSafeMove(player, math.abs(delta.X) >= math.abs(delta.Y)
            and Vector(delta.X >= 0 and 1 or -1, 0)
            or Vector(0, delta.Y >= 0 and 1 or -1), false)
    end
    local nearest, distance = nil, nil
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if isCombatEnemy(entity) then
            local currentDistance = entity.Position:Distance(player.Position)
            if not distance or currentDistance < distance then nearest, distance = entity, currentDistance end
        end
    end
    if nearest and distance < 95 then
        local away = player.Position - nearest.Position
        if math.abs(away.X) >= math.abs(away.Y) then desired = Vector(away.X >= 0 and 1 or -1, 0)
        else desired = Vector(0, away.Y >= 0 and 1 or -1) end
    end
    if action.mode ~= "hazard" and projectileMove then desired = projectileMove end
    -- If the previous resolved direction produced no displacement, rotate it
    -- before applying the enemy-avoidance result again. This closes the loop
    -- at the game-input layer instead of repeatedly pushing into one wall.
    if action.mode ~= "hazard" and not projectileMove and lastMovementBlocked and lastResolvedMove:Length() > 0.5 then
        desired = Vector(-lastResolvedMove.Y, lastResolvedMove.X)
    end
    if action.mode == "hazard" then
        if not hazardTarget then
            hazardLaneAxis = ""
            return Vector(0, 0)
        end
        if nearest and distance < 95 then
            hazardLaneAxis = ""
            return firstSafeMove(player, desired, false)
        end
        if action.waypoint then
            if player.Position:Distance(action.waypoint) <= 14 then return Vector(0,0) end
            local routed = followGridRoute(player, action.waypoint, 12)
            if routed then return routed end
        end
        local correction = hazardLaneCorrection(player, hazardTarget, hazardId)
        if correction then return correction end
    else
        hazardLaneAxis = ""
    end
    -- The Python route already ends at a safe firing lane. Contact checks in
    -- safeMoveCandidate are the sole proximity guard; a second 90px retreat
    -- rule used to reverse the approach step before the lane was reached.
    if desired:Length() < 0.5 then return Vector(0, 0) end
    return firstSafeMove(player, desired, false)
end

local function actionHazardStillPresent()
    if action.mode ~= "hazard" and action.mode ~= "bomb" then return true end
    local hazardId = tonumber(string.match(action.id or "", "^clear_hazard_(%-?%d+)$"))
    if action.mode == "bomb" then
        hazardId = tonumber(string.match(action.id or "", "^bomb_hazard_(%-?%d+)$"))
        local bossId = tonumber(string.match(action.id or "", "^bomb_boss_(%-?%d+)$"))
        if bossId then
            for _, entity in ipairs(Isaac.GetRoomEntities()) do
                if entity.Index == bossId and isCombatEnemy(entity) then return true end
            end
            return false
        end
    end
    if not hazardId then return false end
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if entity.Index == hazardId then
            local kind = liveHazardKind(entity)
            -- A stale pre-v13 clear action must not make blue fire a tear
            -- target after the Mod is reloaded.
            if bombOnlyFireKind(kind) and action.mode == "hazard" then return false end
            if kind then return true end
        end
    end
    if hazardId <= -100000 then
        local gridIndex = -100000 - hazardId
        local kind = liveGridHazardKind(game:GetRoom():GetGridEntity(gridIndex))
        return kind ~= nil and (kind ~= "xrock" or game:GetPlayer(0):GetNumBombs() > 0 or bombPlaced)
    end
    return false
end

local function actionPickupStillPresent()
    if action.mode ~= "item" and action.mode ~= "shop" and action.mode ~= "pickup" and action.mode ~= "chest" then return true end
    local pickupId = tonumber(string.match(action.id or "", "^take_[a-z]+_(%-?%d+)$"))
    if not pickupId then pickupId = tonumber(string.match(action.id or "", "^open_chest_(%-?%d+)$")) end
    if not pickupId or ignoredPickup(pickupId) then return false end
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if entity.Type == EntityType.ENTITY_PICKUP and entity.Index == pickupId then return true end
    end
    return false
end

local function bombEscapeDirection(player, preferred, avoidEnemies)
    local room = game:GetRoom()
    local directions = { Vector(1, 0), Vector(-1, 0), Vector(0, 1), Vector(0, -1) }
    table.sort(directions, function(a, b)
        return a.X * preferred.X + a.Y * preferred.Y > b.X * preferred.X + b.Y * preferred.Y
    end)
    for _, direction in ipairs(directions) do
        if (not avoidEnemies or direction.X * preferred.X + direction.Y * preferred.Y >= 0)
            and safeMoveCandidate(player, direction, false) then
            local corridorClear = true
            for distance = 40, 160, 20 do
                local point = player.Position + direction * distance
                if not room:IsPositionInRoom(point, 12) then corridorClear = false; break end
                local index = room:GetGridIndex(point)
                local grid = room:GetGridEntity(index)
                local event = gridEvent(grid, index)
                if room:GetGridPath(index) >= 1000 or redPoopGrid(grid)
                    or liveGridHazardKind(grid) == "fire"
                    or bombOnlyFireKind(liveGridHazardKind(grid))
                    or (event and event.active and (event.kind == "spike" or event.kind == "tnt")) then
                    corridorClear = false; break
                end
                if avoidEnemies then
                    for _, entity in ipairs(Isaac.GetRoomEntities()) do
                        if (isCombatEnemy(entity) or isMovingSpikeTrap(entity)
                            or entity.Type == (EntityType.ENTITY_ETERNALFLY or 96)
                            or dangerousCreep(entity) or liveHazardKind(entity) == "fire"
                            or bombOnlyFireKind(liveHazardKind(entity)))
                            and point:Distance(entity.Position)
                                < (tonumber(entity.Size) or 20) + (tonumber(player.Size) or 10) + 15 then
                            corridorClear = false; break
                        end
                    end
                    if not corridorClear then break end
                end
            end
            if corridorClear then return direction end
        end
    end
    return nil
end

function mod:observeBombInput(player)
    local pending=self.pendingBombInput
    if not pending then return end
    if not automatic or pending.room~=currentRoomKey()
        or game:GetFrameCount()-pending.frame>12 then
        self.pendingBombInput=nil
        utilityButtons[ButtonAction.ACTION_BOMB]=nil
        bombError="native bomb input expired or context changed"
        return
    end
    for _,entity in ipairs(Isaac.GetRoomEntities()) do
        if entity.Type==(EntityType.ENTITY_BOMB or 4) and not pending.seen[entity.Index] then
            local owner=entity.SpawnerEntity
            if (owner and owner.Index==player.Index and owner.Type==(EntityType.ENTITY_PLAYER or 1))
                or entity.SpawnerType==(EntityType.ENTITY_PLAYER or 1) then
                bombTargetId=pending.target
                bombPlaced,bombPlacedFrame=true,game:GetFrameCount()
                bombPosition=Vector(entity.Position.X,entity.Position.Y)
                bombEntity,bombPlacementDistance=entity,pending.distance
                bombRetreatDirection,bombRoomKey=pending.escape,pending.room
                if pending.wallSlot then bombedWallKeys[pending.room..":"..tostring(pending.wallSlot)]=true end
                self.pendingBombInput=nil
                utilityButtons[ButtonAction.ACTION_BOMB]=nil
                bombError=nil
                return
            end
        end
    end
end

local function tryDropBomb(player)
    if mod.pendingBombInput then return end
    if (action.mode ~= "bomb" and action.mode ~= "bomb_wall") or not automatic then return end
    if action.sourceRoomIndex >= 0 and action.sourceRoomIndex ~= canonicalRoomIndex(game:GetLevel()) then return end
    if action.mode == "bomb_wall" and hasCombatEnemy() then return end
    local bombId = tonumber(string.match(action.id or "", "^bomb_hazard_(%-?%d+)$"))
    local bossId = tonumber(string.match(action.id or "", "^bomb_boss_(%-?%d+)$"))
    local wallSlot = tonumber(string.match(action.id or "", "^bomb_secret_(%d+)$"))
        or tonumber(string.match(action.id or "", "^bomb_super_secret_(%d+)$"))
    if not bombId and not bossId and not wallSlot then return end
    if bombPlaced and bombRoomKey == currentRoomKey() and game:GetFrameCount() - bombPlacedFrame < 120 then return end
    if player:GetNumBombs() <= 0 and not player:HasGoldenBomb() then return end
    local room = game:GetRoom()
    local targetPosition = nil
    if bombId then
        for index = 0, room:GetGridSize() - 1 do
            if -100000 - index == bombId then
                local grid = room:GetGridEntity(index)
                local kind = liveGridHazardKind(grid)
                if kind == "xrock" or kind == "passage_rock" or bombOnlyFireKind(kind) then
                    if kind=="passage_rock" and (not room:IsClear() or hasCombatEnemy()) then return end
                    if bombOnlyFireKind(kind) and player:GetNumBombs() <= 4 then
                        bombError = "special fire requires more than four bombs"
                        return
                    end
                    targetPosition = grid.Position
                end
                break
            end
        end
        -- Entity hazards use their positive Entity.Index. Blue fire is a
        -- bomb-only entity target; it must never fall through to tear aiming.
        if not targetPosition then
            for _, entity in ipairs(Isaac.GetRoomEntities()) do
                if entity.Index == bombId and bombOnlyFireKind(liveHazardKind(entity)) then
                    if player:GetNumBombs() <= 4 then
                        bombError = "special fire requires more than four bombs"
                        return
                    end
                    targetPosition = entity.Position
                    break
                end
            end
        end
    elseif bossId then
        local descriptor = game:GetLevel():GetCurrentRoomDesc()
        if not descriptor or not descriptor.Data or descriptor.Data.Type ~= RoomType.ROOM_BOSS then return end
        for _, entity in ipairs(Isaac.GetRoomEntities()) do
            local npc = entity:ToNPC()
            if entity.Index == bossId and isCombatEnemy(entity) and npc then
                local bossOk, isBoss = pcall(function() return npc:IsBoss() end)
                if bossOk and isBoss then
                    targetPosition = entity.Position
                    break
                end
            end
        end
        if not targetPosition then return end
    elseif wallSlot and room:IsDoorSlotAllowed(wallSlot) then
        local door = room:GetDoor(wallSlot)
        if door and door:IsOpen() then return end
        targetPosition = actualDoorPosition(room, wallSlot)
    end
    if not targetPosition then return end
    if not bossId and (not action.bombSite or player.Position:Distance(action.bombSite) > 14) then return end
    local distance = targetPosition:Distance(player.Position)
    if bombId and (distance < 24 or distance > 70) then return end
    if bossId and (distance < 55 or distance > 110) then return end
    if wallSlot and (distance < 32 or distance > 90) then return end
    local preferred = wallSlot and (room:GetCenterPos() - player.Position) or (player.Position - targetPosition)
    local escape = bombEscapeDirection(player, preferred, bossId ~= nil)
    if not escape then bombError = "no clear bomb escape corridor"; return end
    -- Native input retains ordinary placement/collision and inventory rules.
    -- Let real friction stop an optional plant instead of creating a bomb
    -- under a moving body and then relying on a forbidden velocity reset.
    if player.Velocity and player.Velocity:Length()>.25 then
        if not bossId then resolvedMove=Vector(0,0) end
        bombError="waiting stationary before native bomb input"
        return
    end
    local seen={}
    for _,entity in ipairs(Isaac.GetRoomEntities()) do
        if entity.Type==(EntityType.ENTITY_BOMB or 4) then seen[entity.Index]=true end
    end
    mod.pendingBombInput={frame=game:GetFrameCount(),room=currentRoomKey(),seen=seen,
        inventory=player:GetNumBombs(),target=bombId or bossId or (-200000-wallSlot),
        wallSlot=wallSlot,distance=distance,escape=escape}
    utilityButtons[ButtonAction.ACTION_BOMB]=true
    resolvedMove=Vector(0,0)
    bombError="native bomb input pending"
end

local function tryEnterSelectedDoor(player)
    transitionGate = "checking"
    transitionDoorDistance = -1
    if action.mode == "boss_exit" then
        if hasCombatEnemy() then transitionGate = "combat_present"; return true end
        transitionGate = "boss_exit_navigation"
        transitionPhase = "native_trapdoor_only"
        return false
    end
    if action.mode ~= "navigate" then transitionGate = "not_navigation"; return false end
    if hasCombatEnemy() then transitionGate = "combat_present"; return false end
    if game:GetFrameCount() - lastActionFrame > 45 then
        transitionPhase = "waiting_for_fresh_action"
        transitionGate = "stale_action"
        return true
    end
    local doorSlot = tonumber(string.match(action.id or "", "^enter_door_(%d+)$"))
    if not doorSlot then
        -- The Python stall breaker keeps the previous mode for diagnostics,
        -- but its lateral reposition is not a door command. Let the generic
        -- collision-safe resolver execute that escape move.
        transitionGate = "navigation_override"
        return false
    end
    local level, room = game:GetLevel(), game:GetRoom()
    local roomIndex = canonicalRoomIndex(level)
    if action.sourceRoomIndex >= 0 and action.sourceRoomIndex ~= roomIndex then transitionGate = "source_room_mismatch"; return true end
    if doorAttemptRoomIndex ~= roomIndex or doorAttemptSlot ~= doorSlot then
        doorAttemptRoomIndex = roomIndex
        doorAttemptSlot = doorSlot
        transitionPhase = "native_door_only"
        transitionError = nil
    end
    local door = room:GetDoor(doorSlot)
    if not door then transitionGate = "door_missing"; return true end
    local openOk, open = pcall(function() return door:IsOpen() end)
    local lockOk, locked = pcall(function() return door:IsLocked() end)
    local targetDesc = door.TargetRoomIndex and door.TargetRoomIndex >= 0
        and level:GetRoomByIdx(door.TargetRoomIndex, currentDimension(level)) or nil
    local targetType = targetDesc and targetDesc.Data and targetDesc.Data.Type or door.TargetRoomType
    local sheolRoute = RUN_TARGET == "satan" and level:GetStage() >= 2 and level:GetStage() <= 8
        and targetType == RoomType.ROOM_DEVIL and openOk and open == true
        and lockOk and locked == false
    if not door.TargetRoomIndex or (door.TargetRoomIndex < 0 and not sheolRoute) then
        transitionGate = "door_target_missing"; return true
    end
    local hiddenTarget = targetType == RoomType.ROOM_SECRET or targetType == RoomType.ROOM_SUPERSECRET
    local keyDoor = targetType == RoomType.ROOM_TREASURE or targetType == RoomType.ROOM_SHOP
        or targetType == RoomType.ROOM_LIBRARY or targetType == RoomType.ROOM_PLANETARIUM
    local canUnlock = lockOk and locked == true and keyDoor and player:GetNumKeys() > 0
    if openOk and type(open) == "boolean" and not open and not canUnlock then
        transitionGate = "door_closed"
        return true
    end
    if hiddenTarget then
        if locked or ((not lockOk or type(locked) ~= "boolean") and not (openOk and open)) then
            transitionPhase = "hidden_door_blocked"
            transitionGate = "hidden_door_locked"
            transitionError = "hidden room is locked or lock state is unknown"
            return true
        end
    end
    if action.targetRoomIndex >= 0 and canonicalRoomIndex(level, door.TargetRoomIndex) ~= action.targetRoomIndex then
        transitionError = "door target mismatch: planned " .. tostring(action.targetRoomIndex) .. " actual " .. tostring(door.TargetRoomIndex)
        transitionPhase = "target_mismatch"
        transitionGate = "target_mismatch"
        return true
    end
    -- A late JEV response can arrive after a successful transition and ask
    -- for the door we just used in reverse. When another real door exists,
    -- hold the old command briefly so Python can publish the new floor-plan
    -- decision instead of bouncing between two rooms through the API.
    if roomIndex == lastTransitionTargetRoomIndex
        and canonicalRoomIndex(level, door.TargetRoomIndex) == lastTransitionSourceRoomIndex
        and game:GetFrameCount() - roomEntryFrame < backtrackGuardFrames
    then
        local alternative = false
        for slot = 0, 7 do
            local candidate = room:GetDoor(slot)
            if candidate and candidate.TargetRoomIndex and candidate.TargetRoomIndex >= 0
                and canonicalRoomIndex(level, candidate.TargetRoomIndex) ~= lastTransitionSourceRoomIndex
            then
                local openOk, open = pcall(function() return candidate:IsOpen() end)
                if openOk and open == true then
                    alternative = true
                    break
                end
            end
        end
        if alternative then
            transitionError = "reverse door blocked after entry: " .. tostring(door.TargetRoomIndex)
            transitionPhase = "backtrack_blocked"
            transitionGate = "reverse_guard"
            return false
        end
    end
    local actualPosition = actualDoorPosition(room, doorSlot)
    local fallbackPosition = room:GetDoorSlotPosition(doorSlot)
    local actualDistance = player.Position:Distance(actualPosition)
    local fallbackDistance = player.Position:Distance(fallbackPosition)
    local distance = math.min(actualDistance, fallbackDistance)
    transitionDoorDistance = distance
    if distance > 120 then
        transitionPhase = "native_door_only"
        transitionGate = "too_far"
        return false
    end
    -- Room changes must come from Isaac's ordinary door input. Never call a
    -- room-transition API here: a stale or mismatched action could otherwise
    -- send Isaac through the wrong door and leave him inside a wall.
    transitionPhase = "native_door_only"
    transitionGate = lastMovementBlocked and "native_input_blocked" or "native_input"
    return false
end

local function syncRoomTransitionState()
    local roomIndex = canonicalRoomIndex(game:GetLevel())
    if roomIndex ~= lastObservedRoomIndex then
        combatAimTargetId,combatAimLockFrame=-1,-10000
        local previousRoomIndex = lastObservedRoomIndex
        lastObservedRoomIndex = roomIndex
        roomEntryFrame = game:GetFrameCount()
        roomEnteredFrame = roomEntryFrame
        roomVisitSequence = roomVisitSequence + 1
        roomClearedFrame = -1
        lastEnemyCount = 0
        if previousRoomIndex >= 0 and previousRoomIndex ~= roomIndex then
            lastTransitionSourceRoomIndex = previousRoomIndex
            lastTransitionTargetRoomIndex = roomIndex
        end
        transitionPhase = "entered"
        transitionError = nil
        doorAttemptRoomIndex = -1
        doorAttemptSlot = -1
        bombTargetId, bombPlaced, bombPosition, bombRoomKey = -1, false, nil, ""
        bombEntity = nil
        bombPlacementDistance = -1
        bombPlacedFrame = -1
        bombRetreatActive = false
        nativeSeenTears = {}
        nativeTearFrame, nativeFireStartFrame = -10000, -1
        nativeChargeStartFrame,nativeChargePhase=-1,"idle"
        if mod.weaponControl then mod.weaponControl:reset() end
        lastTrinketSwapTarget = -1
        trinketSwapResult = "idle"
        action = { id = "", move = Vector(0, 0), shoot = Vector(0, 0), mode = "combat", target = "", reason = "", sourceRoomIndex = -1 }
    end
end

local function ensureClient()
    if not socketOk or not Json then return false end
    if client then return true end
    local created, createErr = socket.tcp()
    if not created then
        Isaac.DebugString("[IsaacJev] socket create failed: " .. tostring(createErr))
        return false
    end
    created:settimeout(0)
    local connected, connectErr = created:connect(HOST, PORT)
    if not connected and connectErr ~= "timeout" and connectErr ~= "Operation already in progress" then
        created:close()
        bridgeStatus = "connect error: " .. tostring(connectErr)
        return false
    end
    client = created
    bridgeStatus = connected and "connected" or "connecting"
    return true
end

local function closeClient()
    if client then client:close() end
    client = nil
    pendingState = nil
    pendingStateRequiresReply = false
    pendingActionPartial = ""
    stateAwaitingReply = false
    controllerEnabled = false
    bridgeStatus = "disconnected"
end

local function readActions()
    if not client or not Json then return end
    while true do
        local line, err, partial = client:receive("*l")
        if not line then
            pendingActionPartial = pendingActionPartial .. (partial or "")
            if #pendingActionPartial > 524288 then closeClient(); return end
            if err == "closed" then closeClient() end
            return
        end
        line = pendingActionPartial .. line
        pendingActionPartial = ""
        local ok, message = pcall(Json.decode, line)
        if ok and type(message) == "table" and message.type == "action" then
            stateAwaitingReply = false
            bridgeStatus = "connected"
            controllerEnabled = message.enabled == true
            lastControlMessageAt = Isaac.GetTime()
            automatic = controllerEnabled and not manualOverride
            if strategyControl then strategyControl:accept(message.strategy,Isaac.GetPlayer(0)) end
            local previousActionId = action.id
            local previousActionSequence = currentActionSequence
            local move = message.move or {}
            local shoot = message.shoot or {}
            action.id = message.id or ""
            action.move = Vector(tonumber(move.x) or 0, tonumber(move.y) or 0)
            action.shoot = Vector(tonumber(shoot.x) or 0, tonumber(shoot.y) or 0)
            local bombSite = message.bomb_site
            action.bombSite = type(bombSite) == "table"
                and Vector(tonumber(bombSite.x) or 0, tonumber(bombSite.y) or 0) or nil
            local waypoint = message.waypoint
            action.waypoint = type(waypoint) == "table"
                and Vector(tonumber(waypoint.x) or 0, tonumber(waypoint.y) or 0) or nil
            action.mode = message.mode or "combat"
            action.target = message.target or ""
            action.reason = message.reason or ""
            action.sourceRoomIndex = tonumber(message.source_room_index) or -1
            action.targetRoomIndex = tonumber(message.target_room_index) or -1
            action.ignoredHazardIds = message.ignored_hazard_ids or {}
            action.ignoredPickupIds = message.ignored_pickup_ids or {}
            currentActionSequence = tonumber(message.action_sequence) or 0
            -- Keep placement state across model waits and action revisions.
            -- The room transition or a new run clears it instead.
            if transitionPhase == "backtrack_blocked"
                and (action.id ~= previousActionId or currentActionSequence ~= previousActionSequence)
            then
                -- A new planner response supersedes the old blocked reverse
                -- door. Do not carry the stale zero-movement state forever.
                transitionPhase = "entered"
                transitionError = nil
            end
            lastActionFrame = game:GetFrameCount()
        end
    end
end

local function flushPendingState()
    if not client or not pendingState then return end
    local sent, err, partial = client:send(pendingState)
    if sent then
        pendingState = nil
        stateAwaitingReply = stateAwaitingReply or pendingStateRequiresReply
        pendingStateRequiresReply = false
        sentStateCount = sentStateCount + 1
        bridgeStatus = "connected tx=" .. tostring(sentStateCount)
        return
    end
    if partial and partial > 0 then
        pendingState = string.sub(pendingState, partial + 1)
    end
    if err ~= "timeout" then
        bridgeStatus = "send error: " .. tostring(err)
        closeClient()
    end
end

local function sendState()
    if not ensureClient() then return end
    readActions() -- Drain old responses before emitting the next observation.
    flushPendingState()
    -- A full JSON state can be larger than one nonblocking TCP write. Do not
    -- generate another observation until the current line (including newline)
    -- has been completely delivered, otherwise Python will wait forever for it.
    if not pendingState and not stateAwaitingReply and game:GetFrameCount() - lastStateFrame >= 3 then
        local state = collectState()
        local player = Isaac.GetPlayer(0)
        if player then
            local checks = {}
            for _, option in ipairs({ { "up", Vector(0, -1) }, { "down", Vector(0, 1) },
                { "left", Vector(-1, 0) }, { "right", Vector(1, 0) } }) do
                local _, reason = safeMoveCandidate(player, option[2], false)
                checks[option[1]] = reason
            end
            state.safe_move_directions = checks
        end
        pendingState = Json.encode(state) .. "\n"
        pendingStateRequiresReply = true
        lastStateFrame = game:GetFrameCount()
        flushPendingState()
    end
end

local lastBridgeStateErrorAt = -10000
local function safeSendState()
    local ok, error = pcall(sendState)
    if not ok then
        bridgeStatus = "state error: " .. tostring(error)
        if game:GetFrameCount() - lastBridgeStateErrorAt >= 90 then
            lastBridgeStateErrorAt = game:GetFrameCount()
            Isaac.DebugString("[IsaacJev] STATE_ERROR frame=" .. tostring(game:GetFrameCount())
                .. " room=" .. tostring(canonicalRoomIndex(game:GetLevel())) .. " " .. tostring(error))
        end
    end
end

local function wants(vector, button)
    if button == ButtonAction.ACTION_LEFT then return vector.X < -0.5 end
    if button == ButtonAction.ACTION_RIGHT then return vector.X > 0.5 end
    if button == ButtonAction.ACTION_UP then return vector.Y < -0.5 end
    if button == ButtonAction.ACTION_DOWN then return vector.Y > 0.5 end
    if button == ButtonAction.ACTION_SHOOTLEFT then return vector.X < -0.5 end
    if button == ButtonAction.ACTION_SHOOTRIGHT then return vector.X > 0.5 end
    if button == ButtonAction.ACTION_SHOOTUP then return vector.Y < -0.5 end
    if button == ButtonAction.ACTION_SHOOTDOWN then return vector.Y > 0.5 end
    return false
end

local function isShootButton(button)
    return button == ButtonAction.ACTION_SHOOTLEFT
        or button == ButtonAction.ACTION_SHOOTRIGHT
        or button == ButtonAction.ACTION_SHOOTUP
        or button == ButtonAction.ACTION_SHOOTDOWN
end

local function clearTearLane(player, targetPosition, minimumDistance)
    local delta = targetPosition - player.Position
    local distance = delta:Length()
    if distance < minimumDistance or distance > math.max(0, player.TearRange - 15) then
        return Vector(0, 0)
    end
    local direction = Vector(0, 0)
    if math.abs(delta.Y) <= 18 then direction = Vector(delta.X >= 0 and 1 or -1, 0)
    elseif math.abs(delta.X) <= 18 then direction = Vector(0, delta.Y >= 0 and 1 or -1) end
    if direction:Length() < 0.5 then return direction end
    local room = game:GetRoom()
    if not clearTearLine(room, player.Position, targetPosition) then return Vector(0,0) end
    return direction
end

local function healingRoomSafe(room, player)
    -- Clear rooms may still contain spikes, firing traps or live bullets.
    -- Never commit to standing over a healing bomb in those rooms.
    for index=0,room:GetGridSize()-1 do
        local grid=room:GetGridEntity(index)
        local event=gridEvent(grid,index)
        if redPoopGrid(grid) or (event and event.active
            and (event.kind=="spike" or event.kind=="tnt")) then return false end
    end
    for _,entity in ipairs(Isaac.GetRoomEntities()) do
        if entity.Type==EntityType.ENTITY_PROJECTILE or hostileLaser(entity)
            or isMovingSpikeTrap(entity) or entity.Type==42 or entity.Type==201
            or entity.Type==202 or entity.Type==203 or entity.Type==235 or entity.Type==236
            or dangerousCreep(entity) or liveHazardKind(entity)=="fire" then return false end
    end
    return true
end

function mod:planHeldActive(player)
    if player:GetActiveItem(0)~=(CollectibleType.COLLECTIBLE_SPIN_TO_WIN or 655) then
        self.spinHolding=false
        return false
    end
    local charge=player:GetActiveCharge(0)
    local danger=false
    for _,entity in ipairs(Isaac.GetRoomEntities()) do
        local delta=entity.Position-player.Position
        if isCombatEnemy(entity) and delta:Length()<180 then danger=true break end
        if entity.Type==EntityType.ENTITY_PROJECTILE and delta:Length()<180 then
            local velocity=entity.Velocity or Vector(0,0)
            if delta.X*velocity.X+delta.Y*velocity.Y<0 then danger=true break end
        end
    end
    -- Hold items must be planned every update, ahead of the one-shot utility
    -- cooldown. Wait for a useful reserve after depletion instead of tapping
    -- each newly recharged frame. Ordinary engine input consumes the charge.
    self.spinHolding=danger and charge>0 and (self.spinHolding or charge>=20)
    if not self.spinHolding then utilityResult="native_spin_to_win_released"; return false end
    utilityButtons[ButtonAction.ACTION_ITEM]=true
    utilityResult="native_spin_to_win_hold"
    return true
end

local function planUtilityButtons(player)
    utilityButtons = {}
    pyroHealPending = false
    local frame = game:GetFrameCount()
    if bombStillLive() then return end
    local room = game:GetRoom()
    local count, boss = 0, false
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if isCombatEnemy(entity) then
            count = count + 1
            if entity:IsBoss() then boss = true end
        end
    end
    local unsafeTrinket = false
    for slot = 0, math.max(1, player:GetMaxTrinkets()) - 1 do
        if player:GetTrinket(slot) % 32768 == (TrinketType.TRINKET_MOMS_TOENAIL or 16) then unsafeTrinket = true end
    end
    if unsafeTrinket and count == 0 and room:IsClear() then
        -- The engine requires a held drop button. Keep holding until the
        -- trinket actually leaves inventory; never delete or remove it.
        utilityButtons[ButtonAction.ACTION_DROP] = true
        utilityResult = "native_drop_unsafe_trinket"
        return
    end
    if player:GetActiveItem(0)==(CollectibleType.COLLECTIBLE_SPIN_TO_WIN or 655)
        then mod:planHeldActive(player) end
    if frame - lastUtilityFrame < 45 then return end
    local missing = player:GetMaxHearts() - player:GetHearts()
    if RUN_TARGET=="satan" and player:GetCard(0)==(Card.CARD_JOKER or 31)
        and count==0 and room:IsClear() and game:GetLevel():GetStage()==8
        and room:GetType()==RoomType.ROOM_BOSS then
        utilityButtons[ButtonAction.ACTION_PILLCARD]=true
        utilityResult,lastUtilityFrame="native_joker_after_heart",frame
        return
    end
    if count == 0 and room:IsClear() and missing >= 1 and player:GetNumBombs() > 1
        and player:HasCollectible(CollectibleType.COLLECTIBLE_PYROMANIAC)
        and healingRoomSafe(room,player)
        and frame - lastPyroHealFrame >= 120 then
        pyroHealPending = true
        -- Rocket in a Jar launches a rocket while moving. Let native friction
        -- stop Isaac before planting the ordinary bomb used for healing.
        if player.Velocity and player.Velocity:Length() > 0.25 then
            utilityResult = "pyromaniac_wait_stationary"
            return
        end
        -- Use only an actually owned item's ordinary explosion healing.
        -- The engine creates and consumes the bomb through native input.
        utilityButtons[ButtonAction.ACTION_BOMB] = true
        utilityResult, lastUtilityFrame, lastPyroHealFrame = "native_pyromaniac_heal", frame, frame
        return
    end
    local card = player:GetCard(0)
    if card==(Card.CARD_HEARTS_2 or 26) and count>0 and missing>=2
        and player:GetHearts()>=2 and player:GetHearts()*2<=player:GetMaxHearts() then
        -- A doubling heal can prevent death before the room becomes clear.
        utilityButtons[ButtonAction.ACTION_PILLCARD]=true
        utilityResult,lastUtilityFrame="native_emergency_hearts_2",frame
        return
    end
    local active = player:GetActiveItem(0)
    if active==(CollectibleType.COLLECTIBLE_MAGIC_FINGERS or 295) and player:GetNumCoins()>0
        and (boss or count>=3 or (count>0 and missing>=4)) then
        local vulnerable=false
        for _,entity in ipairs(Isaac.GetRoomEntities()) do
            local npc=entity.ToNPC and entity:ToNPC() or nil
            if isCombatEnemy(entity) and npc and npc:IsVulnerableEnemy() then vulnerable=true break end
        end
        if vulnerable then
            -- This active consumes coins; MaxCharges is correctly zero.
            utilityButtons[ButtonAction.ACTION_ITEM]=true
            utilityResult,lastUtilityFrame="native_magic_fingers_coin",frame
            return
        end
    end
    local config = active ~= 0 and Isaac.GetItemConfig():GetCollectible(active) or nil
    local charged = config and config.MaxCharges > 0 and player:GetActiveCharge(0) >= config.MaxCharges
    if charged and active==(CollectibleType.COLLECTIBLE_SHARP_STRAW or 507) and count>0 then
        for _,entity in ipairs(Isaac.GetRoomEntities()) do
            local npc=entity.ToNPC and entity:ToNPC() or nil
            if isCombatEnemy(entity) and npc and npc:IsVulnerableEnemy() then
                utilityButtons[ButtonAction.ACTION_ITEM]=true
                utilityResult,lastUtilityFrame="native_sharp_straw",frame
                return
            end
        end
    end
    if charged and active==(CollectibleType.COLLECTIBLE_BIBLE or 33)
        and game:GetLevel():GetStage()<=8 and room:GetType()==RoomType.ROOM_BOSS then
        -- Use the actually owned Bible through normal input for its native
        -- Mom/Heart effect. Never put it in generic boss combat utilities:
        -- using it against Satan kills the player.
        for _,entity in ipairs(Isaac.GetRoomEntities()) do
            if entity.Type==(EntityType.ENTITY_MOM or 45)
                or entity.Type==(EntityType.ENTITY_MOMS_HEART or 78) then
                utilityButtons[ButtonAction.ACTION_ITEM]=true
                utilityResult,lastUtilityFrame="native_bible_mom_or_heart",frame
                return
            end
        end
    end
    if charged and active==(CollectibleType.COLLECTIBLE_GLASS_CANNON or 352) and count>0
        and fireDirection:Length()>.5
        and safeMoveCandidate(player,Vector(-fireDirection.X,-fireDirection.Y),false) then
        -- A cannon already carried by this run cannot be dropped without an
        -- ordinary active swap. Use its native shot only with a real aim and
        -- room for recoil; pickup admission prevents acquiring it next run.
        for _,entity in ipairs(Isaac.GetRoomEntities()) do
            local npc=entity.ToNPC and entity:ToNPC() or nil
            if isCombatEnemy(entity) and npc and npc:IsVulnerableEnemy() then
                local dx,dy=entity.Position.X-player.Position.X,entity.Position.Y-player.Position.Y
                local along=dx*fireDirection.X+dy*fireDirection.Y
                local across=math.abs(dx*fireDirection.Y-dy*fireDirection.X)
                if along>=100 and along<=500 and across<=20 then
                    utilityButtons[ButtonAction.ACTION_ITEM]=true
                    utilityResult,lastUtilityFrame="native_aimed_glass_cannon",frame
                    return
                end
            end
        end
    end
    local activeWanted = charged and (
        (RUN_TARGET=="satan" and active==(CollectibleType.COLLECTIBLE_WE_NEED_TO_GO_DEEPER or 84)
            and count==0 and room:IsClear() and game:GetLevel():GetStage()==8
            and room:GetType()==RoomType.ROOM_BOSS and not bossExitInfo(room))
        or
        (active == CollectibleType.COLLECTIBLE_YUM_HEART and missing >= 2)
        or ((active == CollectibleType.COLLECTIBLE_BOOK_OF_REVELATIONS
            or active == CollectibleType.COLLECTIBLE_SATANIC_BIBLE
            or active == CollectibleType.COLLECTIBLE_THE_NAIL
            or active == CollectibleType.COLLECTIBLE_CRYSTAL_BALL) and player:GetSoulHearts() < 20)
        or (active == CollectibleType.COLLECTIBLE_BOOK_OF_SIN and count == 0 and room:IsClear())
        or (active == CollectibleType.COLLECTIBLE_PRAYER_CARD and player:GetEternalHearts() == 0)
        or ((boss or count >= 3 or (count>0 and player:GetHearts()+player:GetSoulHearts()<=4))
            and (active == CollectibleType.COLLECTIBLE_BOOK_OF_BELIAL
            or active == CollectibleType.COLLECTIBLE_BOOK_OF_SHADOWS
            or active == CollectibleType.COLLECTIBLE_NECRONOMICON
            or active == CollectibleType.COLLECTIBLE_SHOOP_DA_WHOOP
            or active == CollectibleType.COLLECTIBLE_TAMMYS_HEAD
            or active == CollectibleType.COLLECTIBLE_HEAD_OF_KRAMPUS
            or active == CollectibleType.COLLECTIBLE_MONSTER_MANUAL
            or active == CollectibleType.COLLECTIBLE_HOURGLASS
            or active == CollectibleType.COLLECTIBLE_CRACK_THE_SKY)))
    if activeWanted then
        utilityButtons[ButtonAction.ACTION_ITEM] = true
        utilityResult, lastUtilityFrame = "native_active:" .. tostring(active), frame
        return
    end
    local color = player:GetPill(0)
    if color and color ~= 0 then
        local pool = game:GetItemPool()
        if not pool:IsPillIdentified(color) then pillUseResult = "kept_unidentified" return end
        local effect = pool:GetPillEffect(color, player)
        local beneficial = effect == PillEffect.PILLEFFECT_BALLS_OF_STEEL
            or effect == PillEffect.PILLEFFECT_HEALTH_UP or effect == PillEffect.PILLEFFECT_TEARS_UP
            or effect == PillEffect.PILLEFFECT_RANGE_UP or effect == PillEffect.PILLEFFECT_SPEED_UP
            or effect == PillEffect.PILLEFFECT_LUCK_UP or effect == PillEffect.PILLEFFECT_PRETTY_FLY
            or (effect == PillEffect.PILLEFFECT_FULL_HEALTH and missing >= 2)
        if beneficial and (count == 0 or missing >= 2) then
            utilityButtons[ButtonAction.ACTION_PILLCARD] = true
            pillUseResult, lastUtilityFrame = "native_use:" .. tostring(effect), frame
        end
        return
    end
    local cardWanted = (card == Card.CARD_HIEROPHANT and player:GetSoulHearts() < 20)
        or (card == Card.CARD_JUSTICE and count == 0 and room:IsClear())
        or (card == Card.CARD_WORLD and count == 0 and room:IsClear())
        or ((boss or count >= 3 or (count > 0 and player:GetHearts()+player:GetSoulHearts() <= 2))
            and (card == Card.CARD_MAGICIAN or card == Card.CARD_CHARIOT or card == Card.CARD_ERA_WALK
                or card == (Card.CARD_EMERGENCY_CONTACT or 50)))
        or (card == Card.CARD_LOVERS and missing > 0 and count == 0)
        or (card == Card.CARD_SUN and (missing >= 2 or boss))
        or (count == 0 and room:IsClear() and (
            (card == Card.CARD_DIAMONDS_2 and player:GetNumCoins() >= 10)
            or (card == Card.CARD_CLUBS_2 and player:GetNumBombs() >= 2)
            or (card == Card.CARD_SPADES_2 and player:GetNumKeys() >= 2)
            or (card == Card.CARD_HEARTS_2 and missing >= 2 and player:GetHearts() >= 2)))
        or ((boss or count >= 4) and (card == Card.CARD_EMPRESS or card == Card.CARD_DEVIL
            or card == Card.CARD_STRENGTH or card == Card.CARD_DEATH))
    if cardWanted then
        utilityButtons[ButtonAction.ACTION_PILLCARD] = true
        utilityResult, lastUtilityFrame = "native_card:" .. tostring(card), frame
    end
end

function mod:onUpdate()
    self.runtimeProfile:begin()
    syncRoomTransitionState()
    local player = Isaac.GetPlayer(0)
    mod:observeBombInput(player)
    timedSpikeNavigator:observe(game:GetRoom(),game:GetFrameCount(),currentRoomKey(),gridEvent)
    tntBlastGuard:observe(game:GetRoom(),Isaac.GetRoomEntities(),game:GetFrameCount(),currentRoomKey(),gridEvent,clearTearLine)
    self.runtimeProfile:mark("observation_guards")
    local dead = handleDeathAndRestart(player)
    if lastPlayerPosition then
        lastMovementProgress = player.Position:Distance(lastPlayerPosition)
        lastMovementBlocked = lastResolvedMove:Length() > 0.5 and lastMovementProgress < 0.5
    else
        lastMovementProgress = 0
        lastMovementBlocked = false
    end
    lastPlayerPosition = Vector(player.Position.X, player.Position.Y)
    safeSendState()
    self.runtimeProfile:mark("state_exchange")
    if dead then
        -- The bridge may reply with an enabled action while the death screen
        -- is visible; never pass that stale action into the input callbacks.
        automatic = false
        resolvedMove = Vector(0, 0)
        self.runtimeProfile:finish()
        return
    end
    if automatic then planUtilityButtons(player) else utilityButtons = {} end
    strategyControl:filterButtons(player,utilityButtons)
    self.runtimeProfile:mark("utility_guards")
    local wantedTrinketId = tonumber(string.match(action.id or "", "^take_pickup_(%d+)$"))
    if automatic and wantedTrinketId and wantedTrinketId ~= lastTrinketSwapTarget then
        for _, entity in ipairs(Isaac.GetRoomEntities()) do
            if entity.Type == EntityType.ENTITY_PICKUP and entity.Index == wantedTrinketId
                and entity.Variant == PickupVariant.PICKUP_TRINKET
                and entity.Position:Distance(player.Position) < 60 then
                local capacity = math.max(1, player:GetMaxTrinkets())
                local occupied = 0
                for slot = 0, capacity - 1 do
                    if player:GetTrinket(slot) ~= 0 then occupied = occupied + 1 end
                end
                if occupied >= capacity then
                    lastTrinketSwapTarget = wantedTrinketId
                    local delta = entity.Position - player.Position
                    local offset = math.abs(delta.X) >= math.abs(delta.Y)
                        and Vector(delta.X >= 0 and -80 or 80, 0)
                        or Vector(0, delta.Y >= 0 and -80 or 80)
                    local ok, err = pcall(function() player:DropTrinket(player.Position + offset, true) end)
                    trinketSwapResult = ok and ("dropped_for:" .. tostring(wantedTrinketId)) or ("error:" .. tostring(err))
                end
                break
            end
        end
    end
    -- A response can arrive one state packet after the tear destroyed its
    -- target. Do not reuse the old aim vector for even one extra frame.
    if automatic and (action.mode == "hazard" or action.mode == "bomb") and not actionHazardStillPresent() then
        action = { id = "hazard_target_gone", move = Vector(0, 0), shoot = Vector(0, 0), mode = "wait", target = "", reason = "hazard disappeared; waiting for fresh state", sourceRoomIndex = -1 }
        lastActionFrame = -10000
    end
    if automatic and not actionPickupStillPresent() then
        action = { id = "pickup_target_gone", move = Vector(0, 0), shoot = Vector(0, 0), mode = "wait", target = "", reason = "pickup marked unreachable or disappeared; waiting for fresh state", sourceRoomIndex = -1 }
        lastActionFrame = -10000
    end
    local bombNeedsRetreat = bombStillLive() and bombPosition
        and player.Position:Distance(bombPosition) < 145
    bombRetreatActive = bombNeedsRetreat and automatic
    local trackingBombNearby = automatic and nearestTrackingBomb(player) ~= nil
    ghostBombRetreatActive = trackingBombNearby
    local doorInputBlocked = automatic and not bombNeedsRetreat and not trackingBombNearby and tryEnterSelectedDoor(player)
    local blockedReverseDoor = automatic
        and not bombNeedsRetreat and not trackingBombNearby
        and action.mode == "navigate"
        and transitionPhase == "backtrack_blocked"
        and game:GetFrameCount() - roomEntryFrame < backtrackGuardFrames
    resolvedMove = automatic and resolveSafeMove(player,doorInputBlocked or blockedReverseDoor) or Vector(0, 0)
    self.runtimeProfile:mark("movement_safety")
    local surpriseEnemy = automatic and not bombNeedsRetreat and not trackingBombNearby and hasCombatEnemy()
        and action.mode ~= "combat" and action.mode ~= "hazard"
        and action.mode ~= "bomb" and action.mode ~= "tnt"
        and action.mode ~= "wait" and action.mode ~= "evade"
    if not trackingBombNearby and game:GetFrameCount() - lastPyroHealFrame >= 100 then tryDropBomb(player) end
    lastRequestedMove = Vector(action.move.X, action.move.Y)
    lastResolvedMove = Vector(resolvedMove.X, resolvedMove.Y)
    if ROUTE_DIAGNOSTICS and action.mode == "combat" then
        routeDebugTrail[#routeDebugTrail+1] = {frame=game:GetFrameCount(),
            x=player.Position.X,y=player.Position.Y,vx=player.Velocity.X,vy=player.Velocity.Y,
            mx=resolvedMove.X,my=resolvedMove.Y,speed=player.MoveSpeed,
            waypoint=routeDebug.waypoint,cursor=routeDebug.cursor}
        if #routeDebugTrail > 64 then table.remove(routeDebugTrail,1) end
    end
    if not automatic then
        lastMoveResolutionReason = "manual"
    elseif timedSpikeNavigator.waiting then
        lastMoveResolutionReason = "timed_spike_wait"
    elseif gridEscapeActive then
        lastMoveResolutionReason = "grid_danger_escape"
    elseif trackingBombNearby then
        lastMoveResolutionReason = "ghost_bomb_retreat"
    elseif (doorInputBlocked or blockedReverseDoor) and lastResolvedMove:Length()>.5 then
        lastMoveResolutionReason = "door_guard_evade"
    elseif doorInputBlocked then
        lastMoveResolutionReason = "door_input_guard"
    elseif blockedReverseDoor then
        lastMoveResolutionReason = "reverse_door_guard"
    elseif gridRouteControlled then
        lastMoveResolutionReason = "grid_route_control"
    elseif action.mode == "hazard" and hazardLaneAxis ~= "" then
        lastMoveResolutionReason = "hazard_lane_control"
    elseif action.mode == "recovery" and action.waypoint
        and player.Position:Distance(action.waypoint) <= 12 then
        lastMoveResolutionReason = "recovery_waypoint_reached"
    elseif lastResolvedMove:Length() < 0.5 and lastRequestedMove:Length() > 0.5 then
        lastMoveResolutionReason = "no_walkable_direction"
    elseif math.abs(lastRequestedMove.X - lastResolvedMove.X) > 0.1 or math.abs(lastRequestedMove.Y - lastResolvedMove.Y) > 0.1 then
        lastMoveResolutionReason = "lua_safety_rewrite"
    else
        lastMoveResolutionReason = "requested"
    end
    fireDirection = action.shoot
    fireBlockReason = "idle"
    if combatLiveAim or surpriseEnemy or action.mode == "combat" then
        if combatLiveAim then
            fireDirection = combatLiveAim
        elseif action.mode == "combat" and not surpriseEnemy and action.shoot:Length() <= 0.5 then
            -- Movement-only combat recovery deliberately holds fire. Do not
            -- replace it with the old local aim fallback.
            fireDirection = Vector(0, 0)
            fireBlockReason = "movement_only_action"
        else
            local liveAim = localFireDirection(player)
            fireDirection = liveAim
            if liveAim:Length() <= 0.5 then fireBlockReason = "no_combat_target" end
        end
    elseif action.mode == "hazard" then
        local hazardId = tonumber(string.match(action.id or "", "^clear_hazard_(%-?%d+)$"))
        local target = nil
        if hazardId then
            for _, entity in ipairs(Isaac.GetRoomEntities()) do
                if entity.Index == hazardId and liveHazardKind(entity) then
                    target = entity
                    break
                end
            end
            if not target and hazardId <= -100000 then
                local grid = game:GetRoom():GetGridEntity(-100000 - hazardId)
                if liveGridHazardKind(grid) then
                    target = grid
                end
            end
        end
        -- The model/controller chooses the hazard target. At game-frame rate,
        -- shoot as soon as the *current* position has a clear cardinal lane;
        -- waiting for the next 3-frame Python decision misses that short window.
        if target and bombOnlyFireKind(liveHazardKind(target)) then
            fireDirection = Vector(0, 0)
            fireBlockReason = "special_fire_bomb_only"
        else
            fireDirection = target and clearTearLane(player, target.Position, 65) or Vector(0, 0)
        end
        if not target then fireBlockReason = "target_missing"
        elseif target and bombOnlyFireKind(liveHazardKind(target)) then fireBlockReason = "special_fire_bomb_only"
        elseif fireDirection:Length() <= 0.5 then
            fireBlockReason = action.shoot:Length() > 0.5 and "range_or_wall" or "approaching_lane"
        end
    elseif action.mode == "tnt" then
        local tntId = tonumber(string.match(action.id or "", "^shoot_tnt_(%-?%d+)$"))
        local tntIndex = tntId and (tntId <= -100000 and (-100000 - tntId) or tntId) or -1
        local tnt = tntIndex >= 0 and game:GetRoom():GetGridEntity(tntIndex) or nil
        local event = gridEvent(tnt, tntIndex)
        fireDirection = Vector(0, 0)
        if event and event.kind == "tnt" and event.active then
            if action.shoot:Length() > 0.5 and (player.Velocity or Vector(0,0)):Length()<=.5 then
                fireDirection = clearTearLane(player, tnt.Position, 155)
            end
        end
        if not event or not event.active then fireBlockReason = "target_missing"
        elseif action.shoot:Length() <= 0.5 then fireBlockReason = "approaching_lane"
        elseif fireDirection:Length() <= 0.5 then fireBlockReason = "range_or_wall" end
    else
        fireDirection = Vector(0, 0)
    end
    if automatic and nearestTrackingBomb(player) then
        fireDirection = Vector(0, 0)
        fireBlockReason = "ghost_bomb_retreat"
    end
    local currentWeapon = weaponKind(player)
    fireDirection = chargedShootDirection(player,fireDirection,currentWeapon)
    if fireDirection:Length()>.5 and not bobsBrainShotSafe(player) then
        fireDirection=Vector(0,0)
        fireBlockReason="bobs_brain_near_enemy"
    end
    if fireDirection:Length() > 0.5 then
        if nativeFireStartFrame < 0 then nativeFireStartFrame = game:GetFrameCount() end
    else
        nativeFireStartFrame = -1
    end
    for _, entity in ipairs(Isaac.GetRoomEntities()) do
        if entity.Type == EntityType.ENTITY_TEAR then
            local ok, owner = pcall(function() return entity.SpawnerEntity end)
            local tearIdentity = entity.InitSeed or entity.Index
            if ok and owner and owner.Index == player.Index and not nativeSeenTears[tearIdentity] then
                nativeSeenTears[tearIdentity] = true
                nativeTearFrame = game:GetFrameCount()
            end
        end
    end
    self.runtimeProfile:mark("aim_and_input_guards")
    self.runtimeProfile:finish()
    local needsTearFallback = currentWeapon == "tear" and not chargeReleaseFrames(player,currentWeapon)
        and nativeFireStartFrame >= 0
        and game:GetFrameCount() - nativeFireStartFrame >= 20
        and game:GetFrameCount() - nativeTearFrame >= 20
    if automatic and game:GetFrameCount() - lastActionFrame <= 45 and needsTearFallback
        and fireDirection:Length() > 0.5 and player.FireDelay <= 0 then
        local velocity = fireDirection * math.max(1, player.ShotSpeed * 10)
        local ok, err = pcall(function()
            local tear = player:FireTear(player.Position + player.TearsOffset, velocity, false, false, false)
            if tear then nativeSeenTears[tear.InitSeed or tear.Index] = true end
            player.FireDelay = player.MaxFireDelay
        end)
        if ok then
            firedTearCount = firedTearCount + 1
            fireError = nil
        else
            fireError = tostring(err)
        end
    end
end

function mod:onInput(entity, inputHook, button)
    if strategyControl then
        local pauseValue = strategyControl:pauseInput(inputHook,button)
        if pauseValue ~= nil then return pauseValue end
    end
    local emergencyEscape = gridEscapeActive and Isaac.GetTime() - lastControlMessageAt < 5000
    -- This aim/move was computed from live entities in the current update.
    -- A short bridge delay may suspend old routes, never this bounded local
    -- combat escape. Manual stop/disconnect and the five-second lease still win.
    local liveCombat = controllerEnabled and combatLiveAim ~= nil
        and Isaac.GetTime() - lastControlMessageAt < 5000
    if not automatic or (game:GetFrameCount() - lastActionFrame > 45
        and not bombRetreatActive and not ghostBombRetreatActive and not emergencyEscape and not liveCombat) then return nil end
    local inputPlayer=entity and entity:ToPlayer() or nil
    if not inputPlayer then return nil end
    if button == ButtonAction.ACTION_ITEM or button == ButtonAction.ACTION_PILLCARD
        or button == ButtonAction.ACTION_DROP or button == ButtonAction.ACTION_BOMB then
        local pressed = game:GetFrameCount()-lastActionFrame<=45 and utilityButtons[button] == true
        if pressed and strategyControl and (button==ButtonAction.ACTION_ITEM or button==ButtonAction.ACTION_PILLCARD) then
            pressed=strategyControl:utilityAllowed(inputPlayer,button)
        end
        if pressed and button==ButtonAction.ACTION_BOMB and mod.pendingBombInput then
            local pending=mod.pendingBombInput
            if inputPlayer:GetNumBombs()<pending.inventory then pressed=false end
            if pressed then
                for _,other in ipairs(Isaac.GetRoomEntities()) do
                    if other.Type==(EntityType.ENTITY_BOMB or 4) and not pending.seen[other.Index] then
                        pressed=false break
                    end
                end
            end
        end
        -- The engine can query this same pulse again after spending its charge.
        -- Sharp Plug then turns a formerly safe activation into health payment.
        -- Re-read live charge at the input boundary, not only in the planner.
        if pressed and button==ButtonAction.ACTION_ITEM
            and inputPlayer:HasCollectible(CollectibleType.COLLECTIBLE_SHARP_PLUG or 205) then
            local active=inputPlayer:GetActiveItem(0)
            local config=active~=0 and Isaac.GetItemConfig():GetCollectible(active) or nil
            if config and config.MaxCharges>0 and inputPlayer:GetActiveCharge(0)<config.MaxCharges then
                pressed=false
            end
        end
        if inputHook == InputHook.GET_ACTION_VALUE then return pressed and 1.0 or 0.0 end
        return pressed
    end
    if isShootButton(button) and (bombRetreatActive or ghostBombRetreatActive or emergencyEscape
        or (game:GetFrameCount() - lastActionFrame > 45 and not liveCombat)) then return nil end
    local vector = isShootButton(button) and fireDirection or resolvedMove
    local pressed = wants(vector, button)
    if pressed and inputHook==InputHook.GET_ACTION_VALUE then
        if isShootButton(button) then self.lastAcceptedShootFrame=game:GetFrameCount()
        else self.lastAcceptedMoveFrame=game:GetFrameCount() end
    end
    if inputHook == InputHook.GET_ACTION_VALUE then return pressed and 1.0 or 0.0 end
    return pressed
end

function mod:onEntityTakeDamage(entity, amount, flags, source, countdown)
    strategyControl:onDamage(entity,flags)
    appendDamageEvent(entity, amount, flags, source)
end

local function flushGameEvent()
    if not pendingGameEvent or not ensureClient() then return end
    flushPendingState()
    if pendingState then return end
    pendingState, pendingGameEvent = pendingGameEvent, nil
    pendingStateRequiresReply = false
    flushPendingState()
end

function mod:onGameStarted()
    -- A normal ending can start a new living player without passing through
    -- the death/restart branch. Every frame-based cache belongs to one run.
    closeClient()
    self.pendingBombInput=nil
    resetRunObservations()
    lastStateFrame,lastActionFrame,lastUtilityFrame,lastPyroHealFrame=-10000,-10000,-10000,-10000
    lastObservedRoomIndex,lastLayoutRoom=-99999,-99999
    lastLayout,lastPlayerPosition,pendingState,pendingGameEvent=nil,nil,nil,nil
    lastTransitionSourceRoomIndex,lastTransitionTargetRoomIndex=-1,-1
    doorAttemptRoomIndex,doorAttemptSlot=-1,-1
    transitionPhase,transitionError,transitionGate="idle",nil,"idle"
    roomEntryFrame,deathDetectedFrame,deathDetectedAt=-10000,-1,-1
    deathWaitTicks,restartAttempted,restartPhase=0,false,"alive"
    restartError=nil
    action={id="",move=Vector(0,0),shoot=Vector(0,0),mode="wait",target="",sourceRoomIndex=-1}
    resolvedMove,fireDirection,lastResolvedMove,lastRequestedMove=Vector(0,0),Vector(0,0),Vector(0,0),Vector(0,0)
    utilityButtons,lastUsedPill={},{}
    lastTrinketSwapTarget=-1
    pillUseResult,trinketSwapResult,utilityResult="idle","idle","idle"
    lastMovementBlocked,lastMovementProgress=false,0
    combatLiveAim=nil
    pyroHealPending=false
    nativeChargeStartFrame,nativeChargePhase=-1,"idle"
    if mod.weaponControl then mod.weaponControl:reset() end
    combatAimTargetId,combatAimLockFrame=-1,-10000
    liveGridRoute,observedBombEscape=nil,nil
    gridEscapeActive,gridRouteControlled=false,false
    automatic=false
end

function mod:onGameEnd(isGameOver)
    local event = {
        type = "game_event", callback = "MC_POST_GAME_END", is_game_over = isGameOver,
        bridge_generation = strategyControl.generation, restart_count = restartCount,
        start_seed = game:GetSeeds():GetStartSeed(), stage = game:GetLevel():GetStage(),
        stage_type = game:GetLevel():GetStageType(),
        room_index = canonicalRoomIndex(game:GetLevel()), frame = game:GetFrameCount(),
        mod_version = MOD_VERSION,
    }
    Isaac.DebugString("[IsaacJev] NATIVE_GAME_END " .. Json.encode(event))
    pendingGameEvent = Json.encode(event) .. "\n"
    if not isGameOver then
        automatic, controllerEnabled, manualOverride = false, false, true
        resolvedMove, fireDirection = Vector(0, 0), Vector(0, 0)
    end
    flushGameEvent()
end

function mod:onRender()
    readActions() -- A buffered reply must renew its lease before the watchdog.
    strategyControl.manualOverride=manualOverride
    if strategyControl:render() then lastStateFrame=-10000;safeSendState() end
    flushGameEvent()
    -- A fixed local reload marker allows development without focus or console
    -- typing. The only supported operation is reloading this Mod's own code.
    if io and os and Isaac.GetTime() - lastReloadPollAt >= 1000 then
        lastReloadPollAt = Isaac.GetTime()
        local request = io.open("mods/IsaacJev/reload.request", "r")
        if request then
            local command = request:read("*a")
            request:close()
            os.remove("mods/IsaacJev/reload.request")
            if command == "reload" then
                automatic = false
                closeClient()
                Isaac.ExecuteCommand("luamod IsaacJev")
                return
            end
        end
    end
    if Input.IsButtonTriggered(Keyboard.KEY_F8, 0) then
        manualOverride = not manualOverride
        automatic = false
        Isaac.DebugString("[IsaacJev] manual override=" .. (manualOverride and "ON" or "OFF"))
    end
    local player = Isaac.GetPlayer(0)
    if player and playerIsDead(player) then
        -- Simulation frames freeze here, so send a heartbeat on real time.
        if Isaac.GetTime() - lastDeathStateAt >= 100 then
            lastDeathStateAt = Isaac.GetTime()
            lastStateFrame = -10000
            safeSendState()
        end
        handleDeathAndRestart(player)
        automatic = false
        resolvedMove = Vector(0, 0)
    end
    local label = "LOCAL WAITING (bridge)"
    if manualOverride then
        label = "LOCAL MANUAL (F8: auto)"
    elseif automatic then
        label = "LOCAL AUTO (F8: manual)"
    end
    Isaac.RenderText(label, 18, 14, automatic and 0.2 or 1, automatic and 1 or 0.8, 0.2, 1)
    Isaac.RenderText(action.mode .. ": " .. action.target, 18, 27, 0.8, 0.9, 1, 1)
    Isaac.RenderText("bridge: " .. bridgeStatus, 18, 40, 0.7, 0.7, 0.7, 1)
    Isaac.RenderText("tears: " .. tostring(firedTearCount), 18, 53, 0.7, 0.7, 0.7, 1)
    if transitionError then Isaac.RenderText("door error: " .. transitionError, 18, 66, 1, 0.4, 0.4, 1) end
end

mod:AddCallback(ModCallbacks.MC_POST_UPDATE, mod.onUpdate)
mod:AddCallback(ModCallbacks.MC_INPUT_ACTION, mod.onInput)
mod:AddCallback(ModCallbacks.MC_ENTITY_TAKE_DMG, mod.onEntityTakeDamage)
mod:AddCallback(ModCallbacks.MC_POST_RENDER, mod.onRender)
if ModCallbacks.MC_PRE_PICKUP_COLLISION then
    mod:AddCallback(ModCallbacks.MC_PRE_PICKUP_COLLISION,function(_,pickup,collider)
        return strategyControl:pickupCollision(pickup,collider)
    end)
end
mod:AddCallback(ModCallbacks.MC_POST_GAME_END, mod.onGameEnd)
mod:AddCallback(ModCallbacks.MC_POST_GAME_STARTED, mod.onGameStarted)
