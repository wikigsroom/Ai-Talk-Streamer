-- Track grid and movable TNT, including the native delayed explosion phase.
local Guard={}
Guard.__index=Guard
function Guard.new() return setmetatable({key='',armed={},known={}},Guard) end

function Guard:observe(room,entities,frame,key,eventFor,lineClear)
    if key~=self.key then self.key,self.armed,self.known=key,{},{} end
    local barrels,positions,observed,queue={},{},{},{}
    for index=0,room:GetGridSize()-1 do
        local event=eventFor(room:GetGridEntity(index),index)
        if event and event.kind=='tnt' then
            positions[index]=room:GetGridPosition(index)
            observed[index]={active=event.active,position=positions[index]}
            if event.active then barrels[index]=positions[index] end
        end
    end
    for _,entity in ipairs(entities) do
        if entity.Type==(EntityType.ENTITY_MOVABLE_TNT or 292) then
            local index=-1000000-(entity.InitSeed or entity.Index or 0)
            local ok,animation=pcall(function() return string.lower(entity:GetSprite():GetAnimation()) end)
            local primed=ok and string.find(animation,'explod',1,true)~=nil
            positions[index]=entity.Position
            observed[index]={active=true,position=entity.Position}
            barrels[index]=entity.Position
            if primed then queue[#queue+1]=index end
        end
    end
    for index,previous in pairs(self.known) do
        if previous.active and not (observed[index] and observed[index].active) then
            -- Native state changes to inactive before the delayed explosion.
            -- Enemy attacks can trigger this transition without a friendly tear.
            positions[index]=positions[index] or previous.position
            queue[#queue+1]=index
        end
    end
    self.known=observed
    for index,entry in pairs(self.armed) do
        if frame>entry.untilFrame then self.armed[index]=nil end
        if positions[index] then entry.position=positions[index] end
    end
    for _,tear in ipairs(entities) do
        if tear.Type==(EntityType.ENTITY_TEAR or 2) then
            local velocity=tear.Velocity or Vector(0,0)
            local length=velocity.X*velocity.X+velocity.Y*velocity.Y
            if length>.1 then
                for index,position in pairs(barrels) do
                    local delta=position-tear.Position
                    local arrival=(delta.X*velocity.X+delta.Y*velocity.Y)/length
                    if arrival>=0 and arrival<=60 and (delta-velocity*arrival):Length()<25
                        and lineClear(room,tear.Position,position) then queue[#queue+1]=index end
                end
            end
        end
    end
    local seen,head={},1
    while head<=#queue do
        local index=queue[head];head=head+1
        if not seen[index] then
            seen[index]=true
            self.armed[index]={position=positions[index],untilFrame=frame+90}
            for nextIndex,position in pairs(barrels) do
                if not seen[nextIndex] and position:Distance(positions[index])<=120 then queue[#queue+1]=nextIndex end
            end
        end
    end
end

function Guard:clearance(player,position)
    if player.HasCollectible and player:HasCollectible(223) then return math.huge end
    local margin=math.huge
    for _,entry in pairs(self.armed) do margin=math.min(margin,position:Distance(entry.position)-150) end
    return margin
end

function Guard:danger(player) return self:clearance(player,player.Position)<45 end

function Guard:safe(player,position)
    if player.HasCollectible and player:HasCollectible(223) then return true end
    for _,entry in pairs(self.armed) do
        if position:Distance(entry.position)<150
            and position:Distance(entry.position)<player.Position:Distance(entry.position)-.1 then return false end
    end
    return true
end

return Guard
