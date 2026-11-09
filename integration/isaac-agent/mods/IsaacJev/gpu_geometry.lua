-- Optional arithmetic worker. Never reads game state or authorizes an action.
-- One bounded request per update; any error retains the original CPU guards.
local M = {}
function M.new(socket, config)
    config=config or {}
    local self={client=nil,sequence=0,retryAt=0,requests=0,successes=0,fallbacks=0,
        last_ms=0,max_ms=0,total_ms=0,last_error=nil,last_tracks=0}
    local enabled=config.enabled==true and socket and string.pack and string.unpack
    local budget=math.max(.001,math.min(.012,(config.deadline_ms or 8)/1000))
    function self:close()
        if self.client then pcall(function() self.client:close() end);self.client=nil end
    end
    function self:snapshot()
        return {enabled=enabled and true or false,requests=self.requests,successes=self.successes,
            fallbacks=self.fallbacks,last_ms=self.last_ms,max_ms=self.max_ms,
            mean_ms=self.total_ms/math.max(1,self.requests),last_error=self.last_error,last_tracks=self.last_tracks}
    end
    function self:available()
        return enabled and socket.gettime()>=self.retryAt
    end
    function self:distances(identity,forecasts,tracks)
        if not self:available() or #tracks==0 then return nil end
        if #tracks>256 then self.fallbacks=self.fallbacks+1;self.last_error='track_capacity';return nil end
        self.requests=self.requests+1;self.sequence=(self.sequence+1)%4294967295
        self.last_tracks=#tracks
        local started=socket.gettime()
        local ok,result=pcall(function()
            local fields={}
            local function coordinate(value)
                assert(type(value)=='number' and value==value and math.abs(value)<=8192,'coordinate_bounds')
                fields[#fields+1]=string.pack('<d',value)
            end
            assert(#forecasts==9,'directions')
            for _,path in ipairs(forecasts) do
                for tick=0,10 do coordinate(path[tick].X);coordinate(path[tick].Y) end
            end
            for _,track in ipairs(tracks) do
                for tick=0,10 do coordinate(track.path[tick].X);coordinate(track.path[tick].Y) end
                fields[#fields+1]=string.pack('<dd',track.first,track.initial and 1 or 0)
            end
            local header=string.pack('<c4I4I4I4i4I4I4I4','IGP1',self.sequence,identity.frame,
                identity.seed,identity.room,identity.stage,#tracks,10)
            local function remaining()
                local left=budget-(socket.gettime()-started)
                assert(left>0,'deadline');return left
            end
            if not self.client then
                self.client=assert(socket.tcp());self.client:settimeout(remaining())
                assert(self.client:connect('127.0.0.1',config.port or 9536))
                assert(self.client:setoption('tcp-nodelay',true))
            end
            self.client:settimeout(remaining())
            assert(self.client:send(header..table.concat(fields)))
            self.client:settimeout(remaining())
            local reply=assert(self.client:receive(32+9*#tracks*8))
            assert(reply:sub(1,4)=='IGR1' and reply:sub(5,32)==header:sub(5),'stale_identity')
            assert(socket.gettime()-started<=budget,'deadline')
            local values,offset={},33
            for move=1,9 do
                values[move]={}
                for index,track in ipairs(tracks) do
                    local value;value,offset=string.unpack('<d',reply,offset)
                    assert(value==value and value>=0 and
                        (value<math.huge or (track.first==11 and not track.initial)),'invalid_distance')
                    values[move][index]=value
                end
            end
            return values
        end)
        self.last_ms=(socket.gettime()-started)*1000
        self.max_ms=math.max(self.max_ms,self.last_ms);self.total_ms=self.total_ms+self.last_ms
        if ok then self.successes=self.successes+1;self.last_error=nil;return result end
        self.fallbacks=self.fallbacks+1;self.last_error=tostring(result):sub(1,120)
        self:close();self.retryAt=socket.gettime()+1
        return nil
    end
    return self
end
return M
