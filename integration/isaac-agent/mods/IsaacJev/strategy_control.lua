-- Observation and bounded native input only. No item use, damage, teleport or save mutation API.
local M = {}
local function pos(v) return v and {x=v.X,y=v.Y} or nil end
local function call(object, name, fallback, ...)
    local args={...}
    local ok,value=pcall(function() return object[name](object,table.unpack(args)) end)
    if ok and value~=nil then return value end
    return fallback
end
function M.new(game)
    local self={game=game,owned=false,hold=false,leaseUntil=0,seen={},inventory={},catalog={},
        inventoryKnown=false,inventoryRevision='',lastInventory=-10000,generation=tostring(Isaac.GetTime()),
        sacrificeCounts={},sacrificeKnown={},pendingDamage=nil,ack=nil,lastRenderAt=0}

    function self:key()
        local level=self.game:GetLevel()
        return tostring(self.game:GetSeeds():GetStartSeed())..':'..tostring(level:GetStage())..':'
            ..tostring(level:GetStageType())..':'..tostring(level:GetCurrentRoomIndex())
    end
    function self:refreshInventory(player,force)
        local frame=self.game:GetFrameCount()
        if not force and frame-self.lastInventory<15 and frame>=self.lastInventory then return end
        self.lastInventory=frame
        local config=Isaac.GetItemConfig()
        local list=config:GetCollectibles()
        local inventory,catalog,revision,temporary={},{},{},{}
        local effects=call(player,'GetEffects',nil)
        local size=list and list.Size or 733
        for id=1,size-1 do
            local effectCount=effects and call(effects,'GetCollectibleEffectNum',0,id) or 0
            if effectCount>0 then temporary[#temporary+1]={id=id,count=effectCount} end
            local count=player:GetCollectibleNum(id)
            if count and count>0 then
                local item=config:GetCollectible(id)
                inventory[#inventory+1]={id=id,count=count,name=item and item.Name or tostring(id)}
                revision[#revision+1]=tostring(id)..'x'..tostring(count)
                if item then catalog[#catalog+1]={id=id,name=item.Name,description=item.Description,
                    quality=item.Quality,type=item.Type,max_charges=item.MaxCharges} end
            end
        end
        self.inventory,self.catalog,self.inventoryRevision=inventory,catalog,table.concat(revision,',')
        self.inventoryKnown=true
        self.effects={known=effects~=nil,collectibles=temporary,source='EntityPlayer.GetEffects.GetCollectibleEffectNum'}
    end
    function self:observe(player,state)
        self:refreshInventory(player,false)
        local game,level,room=self.game,self.game:GetLevel(),self.game:GetRoom()
        local key=self:key()
        if self.sacrificeKnown[key]==nil then
            -- Rejoining a room mid-run cannot recover its sacrifice count.
            local desc=level:GetCurrentRoomDesc()
            self.sacrificeKnown[key]=room:GetType()==(RoomType.ROOM_SACRIFICE or 13)
                and room:GetFrameCount()<=10 and (desc.VisitedCount or 0)<=1
            self.sacrificeCounts[key]=0
        end
        local health={units='half_hearts',exact=true,character_type=player:GetPlayerType(),
            red_hearts=player:GetHearts(),max_hearts=player:GetMaxHearts(),soul_hearts=player:GetSoulHearts(),
            black_hearts_bitmask=player:GetBlackHearts(),bone_hearts=player:GetBoneHearts(),
            eternal_hearts=player:GetEternalHearts(),rotten_hearts=call(player,'GetRottenHearts',0),
            broken_hearts=call(player,'GetBrokenHearts',0),golden_hearts=call(player,'GetGoldenHearts',0),
            flying=player.CanFly}
        if self.pendingDamage and self.pendingDamage.key==key and self.pendingDamage.frame<game:GetFrameCount() then
            if health.red_hearts+health.soul_hearts<self.pendingDamage.hp then
                self.sacrificeCounts[key]=(self.sacrificeCounts[key] or 0)+1
            end
            self.pendingDamage=nil
        end
        local actives={}
        for slot=0,3 do
            local id=player:GetActiveItem(slot)
            if id and id~=0 then
                local config=Isaac.GetItemConfig():GetCollectible(id)
                local charge=player:GetActiveCharge(slot)
                local battery=call(player,'GetBatteryCharge',0,slot)
                local maximum=config and config.MaxCharges or 0
                local ready=maximum>0 and charge+battery>=maximum
                if id==295 then ready=player:GetNumCoins()>0 end
                if id==133 or id==347 then ready=true end
                actives[#actives+1]={slot=slot,id=id,charge=charge,battery=battery,max_charges=maximum,
                    ready=ready,name=config and config.Name or tostring(id)}
            end
        end
        local pockets={}
        local pool=game:GetItemPool()
        local supported={}
        for _,name in ipairs({'PILLEFFECT_SPEED_UP','PILLEFFECT_TEARS_UP','PILLEFFECT_RANGE_UP',
            'PILLEFFECT_LUCK_UP','PILLEFFECT_FULL_HEALTH','PILLEFFECT_BALLS_OF_STEEL',
            'PILLEFFECT_HEALTH_UP','PILLEFFECT_PRETTY_FLY','PILLEFFECT_BAD_GAS'}) do
            if PillEffect and PillEffect[name] then supported[PillEffect[name]]=true end
        end
        for slot=0,3 do
            local card,pill=player:GetCard(slot),player:GetPill(slot)
            if card and card~=0 then pockets[#pockets+1]={slot=slot,kind='card',id=card} end
            if pill and pill~=0 then
                local identified=call(pool,'IsPillIdentified',false,pill)
                local effect=identified and call(pool,'GetPillEffect',nil,pill,player) or nil
                local effectName=nil
                if identified and PillEffect then for name,value in pairs(PillEffect) do if value==effect then effectName=name break end end end
                pockets[#pockets+1]={slot=slot,kind='pill',id=pill,identified=identified,effect=effect,
                    effect_name=effectName,effect_supported=identified and supported[effect]==true or false}
            end
        end
        local pickups,catalog={},{table.unpack(self.catalog)}
        local dice=nil
        for _,entity in ipairs(Isaac.GetRoomEntities()) do
            local pickup=entity:ToPickup()
            if entity.Type==EntityType.ENTITY_PICKUP and pickup then
                local config=entity.Variant==100 and Isaac.GetItemConfig():GetCollectible(entity.SubType) or nil
                local eligible=false
                for _,known in ipairs(state.pickups or {}) do if known.id==entity.Index then eligible=true break end end
                pickups[#pickups+1]={id=entity.Index,spawn_seed=entity.InitSeed,type=entity.Type,variant=entity.Variant,
                    subtype=entity.SubType,pos=pos(entity.Position),grid_index=room:GetGridIndex(entity.Position),
                    price=pickup.Price,options_index=pickup.OptionsPickupIndex or 0,
                    shop_item_id=pickup.ShopItemId,is_shop=call(pickup,'IsShopItem',false),
                    name=config and config.Name or tostring(entity.SubType),quality=config and config.Quality or nil,
                    locally_eligible=eligible,hard_rejection=not eligible and 'local_control_capability_or_pickup_rule' or nil}
                if config then catalog[#catalog+1]={id=entity.SubType,name=config.Name,description=config.Description,
                    quality=config.Quality,type=config.Type,max_charges=config.MaxCharges} end
            end
            if room:GetType()==(RoomType.ROOM_DICE or 20) and entity.Type==EntityType.ENTITY_EFFECT
                and EffectVariant and entity.Variant==EffectVariant.DICE_FLOOR then
                dice={face=entity.SubType+1,entity_id=entity.Index,spawn_seed=entity.InitSeed,
                    grid_index=room:GetGridIndex(entity.Position),pos=pos(entity.Position)}
            end
        end
        local map={}
        local rooms=level:GetRooms()
        for index=0,rooms.Size-1 do
            local desc=rooms:Get(index)
            if (desc.DisplayFlags or 0)>0 or (desc.VisitedCount or 0)>0 then
                map[#map+1]={index=desc.SafeGridIndex or desc.GridIndex,list_index=desc.ListIndex,
                    type=desc.Data and desc.Data.Type or nil,visited=desc.VisitedCount,clear=desc.Clear,
                    display_flags=desc.DisplayFlags}
            end
        end
        local sac={count=self.sacrificeKnown[key] and self.sacrificeCounts[key] or nil,known=self.sacrificeKnown[key]==true}
        if room:GetType()==(RoomType.ROOM_SACRIFICE or 13) then
            local center=room:GetGridIndex(room:GetCenterPos())
            local grid=room:GetGridEntity(center)
            if grid and grid:GetType()==(GridEntityType.GRID_SPIKES or 8) then
                sac.spike_index=center;sac.pos=pos(room:GetGridPosition(center))
            end
        end
        local names={[(RoomType.ROOM_SACRIFICE or 13)]='sacrifice',[(RoomType.ROOM_DICE or 20)]='dice',
            [(RoomType.ROOM_PLANETARIUM or 24)]='planetarium'}
        return {bridge_generation=self.generation,inventory=self.inventory,inventory_known=self.inventoryKnown,
            inventory_revision=self.inventoryRevision,catalog=catalog,effects=self.effects,health=health,actives=actives,pockets=pockets,
            pickups=pickups,map=map,room_type=names[room:GetType()] or (state.layout and state.layout.room_type),
            sacrifice=sac,dice=dice,paused=game:IsPaused(),pause_ack=self.pauseAck,
            command_ack=self.ack,manual_override=self.manualOverride==true}
    end
    function self:accept(control,player)
        if type(control)~='table' then return end
        self.owned=control.owned==true
        self.hold=control.hold==true
        self.leaseUntil=Isaac.GetTime()+math.min(1500,tonumber(control.lease_ms) or 0)
        local command=control.command
        self.target=type(command)=='table' and command.target or nil
        if type(command)~='table' or not self.owned then return end
        if command.plan_id==nil or self.seen[command.plan_id] then return end
        self.seen[command.plan_id]=true
        self.ack={plan_id=command.plan_id,status='accepted',frame=game:GetFrameCount()}
        if command.op=='use_active' or command.op=='use_pocket' then
            self.pending=command;self.pending.frame=game:GetFrameCount();self.pending.key=self:key()
            self.pending.coinsBefore=player:GetNumCoins();self.pending.maxBefore=player:GetMaxHearts()
        elseif command.op=='sacrifice_once' or command.op=='trigger_dice' then
            self.macro=command;self.macro.key=self:key();self.macro.deadline=Isaac.GetTime()+12000
        end
    end
    function self:filterButtons(player,buttons)
        if not self.owned then return end
        buttons[ButtonAction.ACTION_ITEM]=false
        buttons[ButtonAction.ACTION_PILLCARD]=false
        buttons[ButtonAction.ACTION_DROP]=false
        if self.hold then buttons[ButtonAction.ACTION_BOMB]=false end
        local c=self.pending
        if not c then return end
        local frame=game:GetFrameCount()
        if frame~=c.frame or self:key()~=c.key or Isaac.GetTime()>self.leaseUntil then self.pending=nil;return end
        local valid,reason=true,''
        local button
        if c.op=='use_active' then
            button=ButtonAction.ACTION_ITEM
            local id=player:GetActiveItem(0)
            local cfg=id>0 and Isaac.GetItemConfig():GetCollectible(id) or nil
            local charge=player:GetActiveCharge(0)+call(player,'GetBatteryCharge',0,0)
            valid=c.slot==0 and id==c.id and cfg~=nil
            if valid and id==295 then valid=player:GetNumCoins()>0
            elseif valid and id==133 then valid=player:GetPlayerType()==0 and player:GetMaxHearts()>=4
                and player:GetHearts()+player:GetSoulHearts()>=6
            elseif valid and id==347 then valid=true
            elseif valid then valid=cfg.MaxCharges>0 and charge>=cfg.MaxCharges end
            if valid and id==33 then
                for _,enemy in ipairs(Isaac.GetRoomEntities()) do
                    if enemy.Type==84 and enemy:ToNPC() then valid=false;reason='Bible against Satan' break end
                end
            end
            if valid and c.combat_required then valid=not game:GetRoom():IsClear() end
        else
            button=ButtonAction.ACTION_PILLCARD
            valid=c.slot==0 and (c.kind=='card' and player:GetCard(0)==c.id or c.kind=='pill' and player:GetPill(0)==c.id)
            if valid and c.kind=='pill' then valid=call(game:GetItemPool(),'IsPillIdentified',false,c.id) end
            if valid and c.combat_required then valid=not game:GetRoom():IsClear() end
        end
        if valid then buttons[button]=true;self.ack.status='pulsed'
        else self.ack.status='rejected';self.ack.reason=reason~='' and reason or 'live inventory/charge guard' end
    end
    function self:utilityAllowed(player,button)
        if not self.owned then return true end
        local c=self.pending
        if not c or c.frame~=game:GetFrameCount() or self:key()~=c.key or Isaac.GetTime()>self.leaseUntil then return false end
        if c.combat_required and game:GetRoom():IsClear() then return false end
        if button==ButtonAction.ACTION_ITEM then
            if c.op~='use_active' or player:GetActiveItem(0)~=c.id then return false end
            local cfg=Isaac.GetItemConfig():GetCollectible(c.id)
            if c.id==295 then return player:GetNumCoins()>0 and c.coinsBefore==player:GetNumCoins() end
            if c.id==133 then return c.maxBefore==player:GetMaxHearts() end
            if c.id==347 then return true end
            return cfg and cfg.MaxCharges>0 and player:GetActiveCharge(0)+call(player,'GetBatteryCharge',0,0)>=cfg.MaxCharges
        end
        return c.op=='use_pocket' and (c.kind=='card' and player:GetCard(0)==c.id or c.kind=='pill' and player:GetPill(0)==c.id)
    end
    function self:onDamage(entity,flags)
        if entity.Type~=EntityType.ENTITY_PLAYER or self.game:GetRoom():GetType()~=(RoomType.ROOM_SACRIFICE or 13) then return end
        local player=entity:ToPlayer();if not player then return end
        local room=self.game:GetRoom()
        if (flags & (DamageFlag.DAMAGE_SPIKES or 32))~=0 and room:GetGridIndex(player.Position)==room:GetGridIndex(room:GetCenterPos()) then
            self.pendingDamage={key=self:key(),frame=game:GetFrameCount(),hp=player:GetHearts()+player:GetSoulHearts()}
        end
    end
    function self:macroAllowed(index,player)
        local c=self.macro
        if not self.owned or not c or c.grid_index~=index or c.key~=self:key() or Isaac.GetTime()>self.leaseUntil
            or Isaac.GetTime()>c.deadline then return false end
        if c.op=='sacrifice_once' then
            local count=c.guard and c.guard.count
            return player:GetPlayerType()==0 and self.sacrificeKnown[c.key] and self.sacrificeCounts[c.key]==count
                and player:GetBoneHearts()==0 and player:GetHearts()+player:GetSoulHearts()>=6
        end
        if c.op~='trigger_dice' or self.game:GetRoom():GetType()~=(RoomType.ROOM_DICE or 20) then return false end
        local expected=c.guard and c.guard.dice
        if not expected then return false end
        for _,entity in ipairs(Isaac.GetRoomEntities()) do
            if entity.Index==expected.entity_id and entity.InitSeed==expected.spawn_seed
                and entity.Type==EntityType.ENTITY_EFFECT and EffectVariant and entity.Variant==EffectVariant.DICE_FLOOR
                and entity.SubType+1==expected.face and self.game:GetRoom():GetGridIndex(entity.Position)==index then return true end
        end
        return false
    end
    function self:effectObstacle(entity,player)
        if self.manualOverride or not EffectVariant or entity.Type~=EntityType.ENTITY_EFFECT
            or entity.Variant~=EffectVariant.DICE_FLOOR then return nil end
        local room=self.game:GetRoom()
        if room:GetType()~=(RoomType.ROOM_DICE or 20) then return nil end
        if self:macroAllowed(room:GetGridIndex(entity.Position),player) then return nil end
        -- A visible dice floor is an irreversible interaction, not free terrain.
        return math.max(72,(entity.Size or 40)+(player.Size or 10)+16)
    end
    function self:requestPause(id,explicit)
        if _G.ISAAC_ALLOW_AUTOMATIC_GAME_PAUSE==false and explicit~=true then
            return "automatic_pause_forbidden"
        end
        self.pauseHold=true
        self.pauseHoldId=id
        self.pauseAck=nil
        self.pauseRequest={id=id,requested=Isaac.GetTime()};return true
    end
    function self:resumePauseHold()
        -- Only the host's guarded, explicit ordinary resume releases this latch.
        self.pauseHold=false;self.pauseHoldId=nil;self.pauseRequest=nil;self.pauseAck=nil
    end
    function self:pickupCollision(pickup,collider)
        if not self.owned or self.manualOverride or not collider:ToPlayer() then return nil end
        if self.pauseHold or self.hold or Isaac.GetTime()>self.leaseUntil then return true end
        local target=self.target
        if not target then return true end
        if pickup.Index~=target.id then return true end
        -- The game invokes the collision hook again on the consumed, empty
        -- collectible pedestal. Block it, but preserve the prior command ack;
        -- only the host's actual inventory delta can prove acquisition.
        if pickup.InitSeed==target.spawn_seed and pickup.Type==target.type and pickup.Variant==target.variant
            and target.type==5 and target.variant==100 and target.subtype>0 and pickup.SubType==0 then return true end
        if pickup.InitSeed~=target.spawn_seed or pickup.Type~=target.type or pickup.Variant~=target.variant
            or pickup.SubType~=target.subtype or pickup.Price~=target.price then
            self.ack={plan_id=self.ack and self.ack.plan_id,status='rejected',reason='pickup changed at native collision'}
            return true
        end
        return nil
    end
    function self:pauseInput(inputHook,button)
        if self.pauseHold and not self.game:IsPaused() then
            for _,name in ipairs({'ACTION_LEFT','ACTION_RIGHT','ACTION_UP','ACTION_DOWN',
                'ACTION_SHOOTLEFT','ACTION_SHOOTRIGHT','ACTION_SHOOTUP','ACTION_SHOOTDOWN',
                'ACTION_ITEM','ACTION_PILLCARD','ACTION_DROP','ACTION_BOMB'}) do
                if ButtonAction[name] and button==ButtonAction[name] then
                    if inputHook==InputHook.GET_ACTION_VALUE then return 0.0 end
                    return false
                end
            end
        end
        local request=self.pauseRequest
        if not request or self.game:IsPaused() then return nil end
        if Isaac.GetTime()-request.requested>1500 then return nil end
        if ButtonAction.ACTION_PAUSE and button==ButtonAction.ACTION_PAUSE then
            request.input_issued_at=Isaac.GetTime()
            if inputHook==InputHook.GET_ACTION_VALUE then return 1.0 end
            return true
        end
        return nil
    end
    function self:render()
        -- Utility authorization expires after 1.5 s. Allow the real-time
        -- combat owner its existing five-second disconnect window, including
        -- an occasional slow room-clear update, before requesting a pause.
        local now=Isaac.GetTime()
        local paused,key=self.game:IsPaused(),self:key()
        local controlsOk,controls=pcall(function() return Isaac.GetPlayer(0).ControlsEnabled end)
        local engineHeld=paused or (controlsOk and controls==false)
        -- A real engine pause/identity transition may finish after Lua callbacks
        -- were suspended during loading. Give the first fresh observation/reply
        -- half a second to arrive. Never renew leaseUntil or replay an old item
        -- command, and never release an explicitly requested pause latch.
        local handoffStarted=(self.renderKey and self.renderKey~=key) or (self.engineHeld==true and not engineHeld)
        if handoffStarted then
            self.observationHandoffUntil=now+500
        end
        self.renderKey,self.engineHeld=key,engineHeld
        if self.owned and not self.manualOverride and now>self.leaseUntil+3500
            and not engineHeld and now>(self.observationHandoffUntil or 0) and not self.pauseHold then
            self:requestPause('controller-lease-expired')
        end
        if self.pauseHold and not self.game:IsPaused() and not self.pauseRequest then
            self.pauseAck=nil
            self.pauseRequest={id=self.pauseHoldId,requested=now}
        end
        if self.pauseRequest and not self.game:IsPaused() and now-self.pauseRequest.requested>1500 then
            self.pauseRequest.requested=now;self.pauseRequest.input_issued_at=nil
        end
        -- IsPaused also includes boss intros, transitions and big-book animations.
        -- A stable simulation frame alone cannot acknowledge a pause request.
        if self.pauseRequest and self.game:IsPaused() and self.pauseRequest.input_issued_at then
            self.pauseAck={id=self.pauseRequest.id,paused=true,frame=game:GetFrameCount(),observed_at=now,
                ordinary_pause_input_issued=true,input_issued_at=self.pauseRequest.input_issued_at}
            self.pauseRequest=nil
        end
        if handoffStarted or ((engineHeld or now<=(self.observationHandoffUntil or 0)) and now-self.lastRenderAt>400) then
            self.lastRenderAt=now;return true
        end
        return false
    end
    return self
end
return M
