"""Latest user policy: character events and service faults cannot pause a game."""
import json
from pathlib import Path


def uninterrupted(root):
    if not isinstance(root,(str,Path)):
        return False
    path=Path(root)/'configs/issac/game-continuity.json'
    return path.is_file() and json.loads(path.read_text('utf-8-sig')).get('uninterrupted_gameplay') is True


NO_AUTOMATIC_PAUSE_GUARD='''local m=_G.__NativeIsaacController
assert(m and m.strategyControl,"current trusted controller required")
local c=m.strategyControl
assert(not c.manualOverride,"preserve actual F8 takeover")
assert(not Game():IsPaused(),"living unpaused game required")
_G.ISAAC_ALLOW_AUTOMATIC_GAME_PAUSE=false
c.pauseRequest=nil;c.pauseHold=false;c.pauseAck=nil
if not c.uninterruptedGuard then
 local original=c.requestPause
 c.requestPause=function(self,id,explicit)
  if explicit~=true then return "automatic_pause_forbidden" end
  return original(self,id,true)
 end
 c.uninterruptedGuard=true
end
return "automatic pause forbidden"'''
