"""Exercise real LuaSocket framing, backpressure and the live-input lease."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class NativeStreamTests(unittest.TestCase):
    def setUp(self):
        self.source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')

    def reader(self):
        helpers='local function closeClient()'+self.source.split('local function closeClient()',1)[1].split('local function flushPendingState()',1)[0]
        return LuaRuntime(unpack_returned_tuples=True).execute('''
            local reply=nil
            local client={receive=function()
                if not reply then return nil,'timeout','' end
                local value=reply;reply=nil
                return value.line,value.err,value.partial
            end,close=function() end}
            Vector=function(x,y) return {X=x,Y=y} end
            local Json={decode=function(text)
                if text~='enabled-action' and text~='disabled-action' then error('incomplete response') end
                return {type='action',id='verified',enabled=text=='enabled-action'}
            end}
            local game={GetFrameCount=function() return 100 end}
            Isaac={GetTime=function() return 2000 end}
            local pendingState,pendingActionPartial,stateAwaitingReply,pendingStateRequiresReply=nil,'',true,false
            local automatic,controllerEnabled,manualOverride=false,false,false
            local action={}
            local lastActionFrame=-10000
        '''+helpers+'''
            return function(text,complete)
                reply=complete and {line=text} or {err='timeout',partial=text}
                readActions()
                return automatic,lastActionFrame,pendingActionPartial,stateAwaitingReply
            end
        ''')

    def test_split_response_and_empty_timeout_are_reassembled(self):
        api=self.reader()
        self.assertEqual(api('enabled-',False),(False,-10000,'enabled-',True))
        self.assertEqual(api('',False),(False,-10000,'enabled-',True))
        self.assertEqual(api('action',True),(True,100,'',False))

    def test_a_split_stop_message_still_disables_control(self):
        api=self.reader()
        api('enabled-action',True)
        api('disabled-',False)
        self.assertEqual(api('action',True)[:2],(False,100))

    def test_only_one_state_is_sent_until_its_response_arrives(self):
        helper='local function flushPendingState()'+self.source.split('local function flushPendingState()',1)[1].split('local lastBridgeStateErrorAt',1)[0]
        api=LuaRuntime(unpack_returned_tuples=True).execute('''
            Vector=function(x,y) return {X=x,Y=y} end
            local frame,sent=0,0
            local pendingState,stateAwaitingReply,lastStateFrame,pendingStateRequiresReply=nil,false,-10000,false
            local sentStateCount=0
            local client={send=function(_,text) sent=sent+1;return #text end}
            local Json={encode=function() return 'state' end}
            local game={GetFrameCount=function() return frame end}
            Isaac={GetPlayer=function() return nil end}
            local function ensureClient() return true end
            local function readActions() end
            local function collectState() return {} end
        '''+helper+'''
            return function(tick,acknowledged)
                frame=tick
                if acknowledged then stateAwaitingReply=false end
                sendState()
                return sent,stateAwaitingReply
            end
        ''')
        self.assertEqual(api(0,False),(1,True))
        self.assertEqual(api(3,False),(1,True))
        self.assertEqual(api(6,False),(1,True))
        self.assertEqual(api(9,True),(2,True))

    def test_game_end_event_neither_waits_for_a_reply_nor_acknowledges_an_old_state(self):
        sender='local function flushPendingState()'+self.source.split('local function flushPendingState()',1)[1].split('local lastBridgeStateErrorAt',1)[0]
        event='local function flushGameEvent()'+self.source.split('local function flushGameEvent()',1)[1].split('function mod:onGameStarted()',1)[0]
        api=LuaRuntime(unpack_returned_tuples=True).execute('''
            Vector=function(x,y) return {X=x,Y=y} end
            local sent=0
            local pendingState,pendingGameEvent,stateAwaitingReply,pendingStateRequiresReply=nil,nil,false,false
            local lastStateFrame,sentStateCount=-10000,0
            local client={send=function(_,text) sent=sent+1;return #text end}
            local Json={encode=function() return 'state' end}
            local game={GetFrameCount=function() return 100 end}
            Isaac={GetPlayer=function() return nil end}
            local function ensureClient() return true end
            local function readActions() end
            local function collectState() return {} end
        '''+sender+event+'''
            return function(previousStatePending)
                sent,stateAwaitingReply=0,previousStatePending
                lastStateFrame=-10000
                pendingGameEvent='game_event'
                flushGameEvent()
                local waitingAfterEvent=stateAwaitingReply
                sendState()
                return waitingAfterEvent,sent,stateAwaitingReply
            end
        ''')
        self.assertEqual(api(False),(False,2,True))
        self.assertEqual(api(True),(True,1,True))

    def test_a_new_run_discards_the_previous_runs_pending_reply(self):
        close='local function closeClient()'+self.source.split('local function closeClient()',1)[1].split('local function readActions()',1)[0]
        start='function mod:onGameStarted()'+self.source.split('function mod:onGameStarted()',1)[1].split('function mod:onGameEnd',1)[0]
        result=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mod={}
            Vector=function(x,y) return {X=x,Y=y} end
            local closed=0
            local client={close=function() closed=closed+1 end}
            local pendingState,pendingActionPartial,stateAwaitingReply,pendingStateRequiresReply='old','half-old',true,true
            local function resetRunObservations() end
        '''+close+start+'''
            mod:onGameStarted()
            return closed,stateAwaitingReply,pendingState==nil,pendingActionPartial,pendingStateRequiresReply
        ''')
        self.assertEqual(result,(1,False,True,'',False))

    def test_stale_macro_allows_only_bounded_fresh_combat_input(self):
        helper='function mod:onInput('+self.source.split('function mod:onInput(',1)[1].split('function mod:onEntityTakeDamage',1)[0]
        api=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mod={}
            InputHook={GET_ACTION_VALUE=1}
            ButtonAction={ACTION_ITEM=10,ACTION_PILLCARD=11,ACTION_DROP=12,ACTION_BOMB=13}
            local automatic,controllerEnabled=true,true
            local gridEscapeActive,bombRetreatActive,ghostBombRetreatActive=false,false,false
            local lastControlMessageAt,lastActionFrame,combatLiveAim=0,0,{}
            local age,frame=2000,60
            local game={GetFrameCount=function() return frame end}
            Isaac={GetTime=function() return age end}
            local utilityButtons={[10]=true}
            local fireDirection,resolvedMove={},{}
            local function isShootButton(button) return button==2 end
            local function wants() return true end
        '''+helper+'''
            return function(ms,enabled,live,button)
                age,automatic,controllerEnabled=ms,enabled,enabled
                combatLiveAim=live and {} or nil
                return mod:onInput({ToPlayer=function() return {} end},1,button)
            end
        ''')
        self.assertEqual(api(2000,True,True,1),1)
        self.assertEqual(api(2000,True,True,2),1)
        self.assertEqual(api(2000,True,True,10),0)
        self.assertIsNone(api(2000,True,False,1))
        self.assertIsNone(api(5001,True,True,1))
        self.assertIsNone(api(2000,False,True,1))


if __name__=='__main__': unittest.main()
