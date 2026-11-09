-- Behavioral baseline from issac commit 52ccc9869d60; used only by equivalence tests.
local function movementForecast(player, move, horizon, room)
    -- Native samples: velocity retention ~0.707, displacement ~2 * average
    -- velocity per game update. A released direction still has momentum.
    local position=Vector(player.Position.X,player.Position.Y)
    local velocity=player.Velocity or Vector(0,0)
    local acceleration=1.14*math.max(0.3,player.MoveSpeed or 1)
    local positions={[0]=position}
    local radius=math.max(6,math.min(12,player.Size or 10)-1)
    local function clearBody(point,from)
        for _,offset in ipairs({Vector(0,0),Vector(radius,0),Vector(-radius,0),Vector(0,radius),Vector(0,-radius),
            Vector(radius*.707,radius*.707),Vector(-radius*.707,radius*.707),
            Vector(radius*.707,-radius*.707),Vector(-radius*.707,-radius*.707)}) do
            local index=room:GetGridIndex(point+offset)
            if room.GetGridSize and (index<0 or index>=room:GetGridSize()) then return false end
            if room:GetGridPath(index)>=1000 then
                -- A native body may already overlap a closed door/wall edge.
                -- Rejecting every partially overlapping forecast freezes all
                -- escape predictions at that position. Permit leaving only
                -- this already touched cell, with strictly less penetration;
                -- a new blocked cell still stops normal collision movement.
                local oldIndex=room:GetGridIndex(from+offset)
                local center=room.GetGridPosition and room:GetGridPosition(index)
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
    return positions
end

