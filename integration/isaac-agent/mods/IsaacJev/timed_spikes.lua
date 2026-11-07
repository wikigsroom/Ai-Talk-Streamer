-- Observe native spike cycles and plan ordinary movement through safe windows.
-- No grid state, player state or room state is modified.
local Navigator={}
Navigator.__index=Navigator

function Navigator.new()
    return setmetatable({key="",history={},active=false},Navigator)
end

function Navigator:finish(goal)
    self.active,self.completed,self.plan,self.waiting=false,tostring(goal),nil,false
    self.reason="arrived"
end

function Navigator:observe(room,frame,key,eventFor)
    if self.key~=key then
        self.key,self.history,self.plan,self.completed,self.active=key,{},nil,nil,false
        self.observedFrame,self.retryAt,self.retryGoal=nil,nil,nil
    end
    if self.observedFrame==frame then return end
    local interrupted=self.observedFrame and frame-self.observedFrame>1
    if interrupted then
        -- A bomb escape/combat interruption can hide a phase transition.
        -- Its first later observation cannot measure a complete ON/OFF
        -- duration; never extend the learned safe window by that blind gap.
        self.plan,self.completed,self.retryAt,self.retryGoal=nil,nil,nil,nil
        for _,history in pairs(self.history) do
            history.durations,history.knownStart={},false
            history.since=frame
        end
    end
    self.observedFrame=frame
    for index=0,room:GetGridSize()-1 do
        local event=eventFor(room:GetGridEntity(index),index)
        if event and event.kind=="spike" and event.timed then
            local history=self.history[index]
            if not history then
                self.history[index]={active=event.active,since=frame,knownStart=false,
                    position=room:GetGridPosition(index),durations={}}
            elseif interrupted then
                -- A different state across a blind gap is not an observed
                -- transition. Its partial first phase cannot define a cycle.
                history.active=event.active
            elseif history.active~=event.active then
                if history.knownStart then history.durations[history.active and 1 or 0]=frame-history.since end
                history.active,history.since,history.knownStart=event.active,frame,true
            elseif history.durations[history.active and 1 or 0]
                and frame-history.since>history.durations[history.active and 1 or 0]+2 then
                -- A pressure plate can latch a running wave down. Continuous
                -- native observations have now contradicted the old period;
                -- do not keep forecasting rises which never occur. Discard
                -- that model and its path, then use the existing 120-frame
                -- stable-OFF observation rule. An extended ON stays unsafe.
                history.durations,history.knownStart={},false
                self.plan,self.completed,self.retryAt,self.retryGoal=nil,nil,nil,nil
            end
        end
    end
end

function Navigator:ready(frame)
    for _,history in pairs(self.history) do
        if not (history.durations[0] and history.durations[1])
            and not (not history.active and frame-history.since>=120) then return false end
    end
    return true
end

function Navigator:safe(index,frame)
    local history=self.history[index]
    if not history then return true end
    local off,on=history.durations[0],history.durations[1]
    if not (off and on) then return not history.active and frame-history.since>=120 end
    local phase=(frame-history.since)%(off+on)
    if history.active then return phase>=on+2 and phase<off+on-2 end
    return phase>=2 and phase<off-2
end

function Navigator:exposure(position,frame)
    local cost=0
    for index,history in pairs(self.history) do
        local dx,dy=math.abs(position.X-history.position.X),math.abs(position.Y-history.position.Y)
        if dx<32 and dy<32 and not self:safe(index,frame) then
            cost=math.max(cost,33-math.max(dx,dy))
        end
    end
    return cost
end

function Navigator:motionSafe(player,move,frame)
    if player.CanFly then return true end
    local position,velocity=player.Position,player.Velocity or Vector(0,0)
    for tick=1,6 do
        local following=velocity*.7+move*(1.14*(player.MoveSpeed or 1))
        position,velocity=position+velocity+following,following
        for index,history in pairs(self.history) do
            local dx,dy=math.abs(position.X-history.position.X),math.abs(position.Y-history.position.Y)
            if dx<32 and dy<32 and not self:safe(index,frame+tick) then
                local initial=player.Position-history.position
                -- Once already overlapping, allow a genuine escape rather
                -- than forcing zero input while the spikes rise underneath.
                if math.abs(initial.X)>=32 or math.abs(initial.Y)>=32
                    or position:Distance(history.position)<=initial:Length()+.01 then return false end
            end
        end
    end
    return true
end

function Navigator:find(room,player,goal,frame,walkable)
    local width,size=room:GetGridWidth(),room:GetGridSize()
    local start=room:GetGridIndex(player.Position)
    -- Include the measured braking overhead once per cell. Ten extra frames
    -- falsely made five-cell crossings impossible inside observed 60-frame
    -- windows; the live six-step inertia guard still vetoes unsafe movement.
    local duration=math.ceil(40/math.max(2,7.6*(player.MoveSpeed or 1)))+5
    -- Include the ordinary approach and the walk from the last spike to the
    -- plate/exit. A fixed six-second horizon falsely rejects longer rooms.
    local distances,queue={[start]=0},{start}
    local head=1
    while head<=#queue do
        local index=queue[head];head=head+1
        if index==goal then break end
        for _,nextIndex in ipairs({index-1,index+1,index-width,index+width}) do
            if nextIndex>=0 and nextIndex<size and distances[nextIndex]==nil and walkable(nextIndex)
                and math.abs(index%width-nextIndex%width)
                    +math.abs(math.floor(index/width)-math.floor(nextIndex/width))==1 then
                distances[nextIndex]=distances[index]+1;queue[#queue+1]=nextIndex
            end
        end
    end
    if not distances[goal] then return nil end
    local cycle=0
    for _,history in pairs(self.history) do
        cycle=math.max(cycle,(history.durations[0] or 0)+(history.durations[1] or 0))
    end
    local horizon=math.max(360,distances[goal]*duration+cycle*2+60)
    local layers,parents={[0]={start}},{}
    local function code(index,tick) return tick*size+index end
    parents[code(start,0)]=-1
    local finish
    for elapsed=0,horizon do
        for _,index in ipairs(layers[elapsed] or {}) do
            local here=code(index,elapsed)
            if index==goal then finish=here break end
            local function add(nextIndex,cost)
                local arrival=elapsed+cost
                if arrival>horizon or not walkable(nextIndex) then return end
                local identity=code(nextIndex,arrival)
                if parents[identity]~=nil then return end
                for step=0,cost do
                    if not self:safe(index,frame+elapsed+step)
                        or not self:safe(nextIndex,frame+elapsed+step) then return end
                end
                parents[identity]=here
                if not layers[arrival] then layers[arrival]={} end
                layers[arrival][#layers[arrival]+1]=nextIndex
            end
            add(index,1)
            for _,nextIndex in ipairs({index-1,index+1,index-width,index+width}) do
                if nextIndex>=0 and nextIndex<size and math.abs(index%width-nextIndex%width)
                    +math.abs(math.floor(index/width)-math.floor(nextIndex/width))==1 then add(nextIndex,duration) end
            end
        end
        if finish then break end
    end
    if not finish then return nil end
    local reverse={}
    while finish~=-1 do
        reverse[#reverse+1]={index=finish%size,at=frame+math.floor(finish/size)}
        finish=parents[finish]
    end
    local points={}
    for i=#reverse,1,-1 do
        local item=reverse[i]
        local previous=points[#points]
        if previous and previous.index==item.index then previous.depart=item.at
        else points[#points+1]={index=item.index,arrival=item.at,depart=item.at} end
    end
    return {points=points,cursor=1,duration=duration,frame=frame}
end

function Navigator:drive(room,player,target,frame,walkable)
    local velocity=player.Velocity or Vector(0,0)
    local function steering(position,speed)
        local error=target-position-speed*(1.7/.3)
        if math.abs(error.X)<=3 and math.abs(error.Y)<=3 then return Vector(0,0) end
        return math.abs(error.X)>=math.abs(error.Y) and Vector(error.X>0 and 1 or -1,0)
            or Vector(0,error.Y>0 and 1 or -1)
    end
    local desired=steering(player.Position,velocity)
    local best,score=nil,math.huge
    for _,move in ipairs({desired,Vector(0,0),Vector(1,0),Vector(-1,0),Vector(0,1),Vector(0,-1)}) do
        local position=Vector(player.Position.X,player.Position.Y)
        local speed=velocity
        local safe=true
        for tick=1,6 do
            local input=tick==1 and move or steering(position,speed)
            local following=speed*.7+input*(1.14*(player.MoveSpeed or 1))
            position=position+speed+following
            speed=following
            if not walkable(room:GetGridIndex(position)) then safe=false break end
            for index,history in pairs(self.history) do
                if math.abs(position.X-history.position.X)<32 and math.abs(position.Y-history.position.Y)<32
                    and not self:safe(index,frame+tick) then safe=false break end
            end
            if not safe then break end
        end
        if safe then
            local value=position:Distance(target)+speed:Length()*.4+(move-desired):Length()*100
            if value<score then best,score=move,value end
        end
    end
    return best
end

function Navigator:move(room,player,target,goal,frame,walkable)
    local identity=tostring(goal)
    if self.completed==identity then return nil,false end
    self.active,self.target,self.goal,self.walkable=true,target,goal,walkable
    if not self:ready(frame) then self.reason="observe_cycle" return Vector(0,0),true end
    if not self.plan or self.plan.goal~=goal then
        if self.retryGoal==goal and self.retryAt and frame<self.retryAt then
            self.reason="no_safe_window" return Vector(0,0),true
        end
        self.plan=self:find(room,player,goal,frame,walkable)
        if self.plan then self.plan.goal=goal end
        self.retryGoal,self.retryAt=goal,self.plan and nil or frame+15
    end
    if not self.plan then self.reason="no_safe_window" return Vector(0,0),true end
    local plan=self.plan
    local point=plan.points[plan.cursor]
    local center=room:GetGridPosition(point.index)
    if player.Position:Distance(center)<=7 and (player.Velocity or Vector(0,0)):Length()<=1.4 then
        if plan.cursor==#plan.points then
            self:finish(goal)
            return nil,false
        end
        if frame>=point.depart then
            plan.cursor=plan.cursor+1
            point=plan.points[plan.cursor]
            center=room:GetGridPosition(point.index)
        end
    end
    if frame>point.arrival+plan.duration+6 then
        self.plan=nil;self.reason="replan_late"
        return Vector(0,0),true
    end
    local move=self:drive(room,player,center,frame,walkable)
    if not move then self.plan=nil;self.reason="replan_forecast" return Vector(0,0),true end
    self.reason="follow_window"
    return move,move:Length()<.5
end

return Navigator
