-- Bounded read-only timings. Never changes decisions or update frequency.
local M = {}
function M.new()
    local self = {rows={}, detailRows={}, count=0, current=nil, last=nil, limit=120}
    function self:begin()
        self.current={};self.currentDetails={};self.last=Isaac.GetTime()
    end
    function self:detail(name,value)
        if self.currentDetails then self.currentDetails[name]=(self.currentDetails[name] or 0)+value end
    end
    function self:mark(name)
        if not self.current then return end
        local now=Isaac.GetTime()
        self.current[name]=now-self.last;self.last=now
    end
    function self:finish()
        if not self.current then return end
        self.count=self.count+1
        self.rows[#self.rows+1]=self.current
        self.detailRows[#self.detailRows+1]=self.currentDetails
        if #self.rows>self.limit then table.remove(self.rows,1);table.remove(self.detailRows,1) end
        self.current=nil;self.currentDetails=nil
    end
    function self:snapshot()
        local phases={};local totals={}
        for _,row in ipairs(self.rows) do
            local total=0
            for name,value in pairs(row) do
                phases[name]=phases[name] or {total_ms=0,max_ms=0}
                local phase=phases[name]
                phase.total_ms=phase.total_ms+value;phase.max_ms=math.max(phase.max_ms,value)
                total=total+value
            end
            totals[#totals+1]=total
        end
        table.sort(totals)
        local sum=0;for _,value in ipairs(totals) do sum=sum+value end
        for _,phase in pairs(phases) do phase.mean_ms=phase.total_ms/math.max(1,#self.rows) end
        local details={}
        for _,row in ipairs(self.detailRows) do
            for name,value in pairs(row) do
                local span=details[name] or {total_ms=0,max_ms=0};details[name]=span
                span.total_ms=span.total_ms+value;span.max_ms=math.max(span.max_ms,value)
            end
        end
        for _,span in pairs(details) do span.mean_ms=span.total_ms/math.max(1,#self.rows) end
        return {updates=self.count,window_updates=#self.rows,phases=phases,details=details,
            update_mean_ms=sum/math.max(1,#totals),update_max_ms=totals[#totals] or 0,
            update_p95_ms=totals[math.max(1,math.ceil(#totals*.95))] or 0}
    end
    return self
end
return M
