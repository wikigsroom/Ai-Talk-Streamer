-- Input-only weapon scheduling. This module never creates attacks or changes stats.
local M = {}
local Controller = {}
Controller.__index = Controller

local function direction(value)
    return {x=value and (value.x or value.X) or 0,y=value and (value.y or value.Y) or 0}
end
local function nonzero(v) return math.abs(v.x)+math.abs(v.y)>.5 end
local function equal(a,b) return a.x==b.x and a.y==b.y end
local function zero() return {x=0,y=0} end

function M.new()
    return setmetatable({phase="idle",start=-1,last=zero(),shots=0,releases=0,
        failures=0,extra=0,seen={},lastShot=-10000,confirmations=0},Controller)
end

function Controller:reset()
    self.phase,self.start,self.last="idle",-1,zero()
    self.seen,self.lastShot={},-10000
    self.shots,self.releases,self.failures,self.extra=0,0,0,0
    self.confirmations,self.confirmed,self.releaseFrame=0,false,nil
    self.signature=nil
    self.hazardId,self.knifeWasFlying,self.tapUntil,self.tapAgain=nil,false,nil,nil
end

function Controller:configure(profile)
    if self.signature~=profile.signature then
        self:reset();self.signature=profile.signature
    end
end

function Controller:profile(player,weapon)
    local function owns(id) return player.HasCollectible and player:HasCollectible(id) end
    local delay=math.max(1,(tonumber(player.MaxFireDelay) or 9)+1)
    local p={kind=weapon,mode="continuous",lead=10,width=5,pierces=false}
    p.engagementRange=math.max(0,math.min(235,(tonumber(player.TearRange) or 260)-25))
    p.engagementRangeSource="native_engagement_ceiling"
    if weapon=="tear" and owns(261) then
        -- Proptosis can keep nominal TearRange while distant shots do no
        -- useful damage. This is conservative positioning, not a stat edit
        -- or a claim about the engine's maximum physical travel distance.
        p.engagementRange=math.min(p.engagementRange,160*math.max(0,tonumber(player.ShotSpeed) or 1))
        p.engagementRangeSource="proptosis_conservative_spacing"
    end
    if weapon=="brimstone" then p.mode,p.lead,p.width,p.pierces="release",1,10,true
    elseif weapon=="tech_x" then p.mode,p.lead,p.width,p.pierces="release",6,22,true
    elseif weapon=="knife" then p.mode,p.lead,p.width,p.pierces="release",4,9,true
    elseif weapon=="monstros_lungs" then p.mode,p.lead,p.width="release",8,18
    elseif weapon=="laser" then p.lead,p.width,p.pierces=1,6,true
    elseif weapon=="fetus" then p.lead,p.width,p.pierces=2,30,true
    elseif weapon=="bombs" then p.lead,p.width=8,12
    elseif weapon=="bone" or weapon=="spirit_sword" then
        -- Close targets get repeatable taps; distant targets use charged throws/spins.
        p.mode,p.lead,p.width="melee",2,22
    elseif weapon=="rockets" or weapon=="ludovico" then p.mode="unsupported" end
    if owns(69) and weapon~="knife" and weapon~="bone" and weapon~="spirit_sword"
        and weapon~="fetus" and p.mode~="unsupported" then p.mode,p.kind="release","chocolate_milk"
    elseif owns(316) and p.mode=="continuous" then p.mode,p.kind="release","cursed_eye" end
    -- MaxFireDelay already includes the weapon's fire-rate penalty. Do not
    -- multiply it again by the same blanket factor used for all old profiles.
    p.charge=math.ceil(delay)+2
    if p.kind=="cursed_eye" then p.charge=math.ceil(delay*4)+2 end
    if p.mode=="melee" then p.charge=math.ceil(delay*(weapon=="spirit_sword" and 4 or 2))+2 end
    p.lockAim=weapon=="spirit_sword"
    -- Milk auto-fire has exceptions: Mom's Knife still requires release;
    -- the sword and bone retain their tap/hold/release controls.
    if (owns(330) or owns(561) or owns(394)) and weapon~="knife"
        and p.mode~="melee" and p.mode~="unsupported" then p.mode="continuous" end
    p.signature=p.kind..":"..p.mode..":"..p.charge
    return p
end

function Controller:step(frame,profile,wanted,context)
    local c=context or {}
    wanted=direction(wanted)
    self:configure(profile)
    if c.shot then
        self.shots=self.shots+1;self.lastShot=frame
        if not self.confirmed and self.releaseFrame and (self.phase=="release" or self.phase=="await_shot") then
            self.confirmations=self.confirmations+1
        end
    end
    if not c.hard_stop and (profile.mode=="release" or profile.mode=="melee")
        and (c.active_beam or c.knife_flying) then
        self.releaseFrame=self.releaseFrame or frame
        self.confirmed,self.start,self.phase=true,-1,"beam"
        return zero()
    end
    if c.hard_stop or not c.engaged then
        self.phase,self.start,self.last="idle",-1,zero()
        return zero()
    end
    if profile.mode=="unsupported" then self.phase="unsupported";return zero() end
    if profile.mode=="continuous" then self.phase="continuous";return wanted end
    if profile.mode=="melee" and c.distance and c.distance<=65 then
        -- Leaving a ranged charge unlocks the next close-range swing. Keeping
        -- its start frame would lock all later taps to an obsolete direction.
        self.start=-1
        self.phase="melee_tap"
        if frame<(self.tapUntil or -1) then return self.last end
        if frame<(self.tapAgain or -1) then return zero() end
        if not c.ready or not nonzero(wanted) then return zero() end
        self.last=wanted;self.tapUntil=frame+1;self.tapAgain=frame+3
        return wanted
    end
    -- A released beam must finish before pressing shoot again; an airborne
    -- knife must return. Actual entities, rather than a guessed fixed gap,
    -- determine when another charge may start.
    if self.phase=="release" or self.phase=="await_shot" or self.phase=="beam" then
        if c.shot then self.confirmed=true end
        if c.active_beam or c.knife_flying then self.phase="beam";return zero() end
        if frame-self.releaseFrame<2 then self.phase="await_shot";return zero() end
        if not self.confirmed and frame-self.releaseFrame<5 then
            self.phase="await_shot";return zero()
        end
        if not self.confirmed then
            self.failures=self.failures+1
            self.extra=math.min(90,self.extra+math.max(2,math.ceil(profile.charge*.2)))
        end
        self.start=-1;self.phase="idle"
    end
    if self.start<0 then
        if not nonzero(wanted) then return zero() end
        self.start=frame
    end
    if not nonzero(wanted) then wanted=self.last end
    if not nonzero(wanted) then self.phase="idle";self.start=-1;return zero() end
    if profile.lockAim and nonzero(self.last) then wanted=self.last end
    local alignedPreviously=equal(self.last,wanted)
    self.last=wanted
    local ready=frame-self.start>=profile.charge+self.extra
    if profile.kind=="knife" and c.knife_charge and c.knife_charge>0 then
        ready=ready and c.knife_charge>=.95
    end
    -- Sword aim is mechanically locked until release. A fully charged
    -- defensive spin also breaks a stale direction and deflects bullets.
    local defensiveSpin=profile.lockAim and frame-self.start>=profile.charge+self.extra+30
    if ready and (c.ready or defensiveSpin) and alignedPreviously then
        self.releaseFrame,self.confirmed=frame,false
        self.releases=self.releases+1
        self.phase="release"
        return zero()
    end
    self.phase=ready and (c.ready and "aim_commit" or "hold_charge") or "charge"
    return wanted
end

function Controller:diagnostics(frame)
    return {phase=self.phase,elapsed=self.start>=0 and frame-self.start or 0,
        charge_frames=self.required,extra_frames=self.extra,release_count=self.releases,
        shot_count=self.shots,failed_releases=self.failures,last_shot_age=frame-self.lastShot,
        confirmed_releases=self.confirmations,
        target_id=self.targetId,target_ready=self.targetReady,profile=self.profileKind}
end
return M
