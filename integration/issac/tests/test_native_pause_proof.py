"""Engine transitions cannot masquerade as a confirmed ordinary pause."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from integration.issac.common import AdmissionError
from integration.issac.native_game import NativeGame,ordinary_pause_proved,OBSERVE
from integration.issac.readiness import verified_drink_pause


def proof():
    return {'paused':True,'frame':4779,'pause_hold':True,
            'pause_ack':{'id':'actual-input','paused':True,'frame':4779,
                         'ordinary_pause_input_issued':True,'input_issued_at':100}}


class OrdinaryPauseProof(unittest.TestCase):
    def fixture(self,root):
        native=object.__new__(NativeGame)
        native.root=Path(root);native.lock=threading.RLock()
        native.process=Mock(pid=123,is_running=Mock(return_value=True),status=Mock(return_value='running'))
        native.session_id='current-native';native.created_at=10;native.audit=Mock();native.menu_key=Mock()
        native.observe=Mock(return_value={'players':1,'dead':False,'paused':True,'frame':4779,
                                         'controller_installed':True})
        return native

    def test_engine_pause_and_stable_frames_alone_are_insufficient(self):
        for changes in ({'pause_hold':False},{'pause_ack':None},{'frame':4780},
                        {'pause_ack':{'id':'old','paused':True,'frame':4779}},
                        {'paused':False}):
            self.assertFalse(ordinary_pause_proved({**proof(),**changes}),changes)
        self.assertTrue(ordinary_pause_proved(proof()))

    def test_intro_wait_never_sends_a_blind_escape_or_creates_a_pause_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            native=self.fixture(root)
            status={'paused':True,'frame':4779,'pause_hold':True,'pause_ack':None}
            native.rpc=Mock(side_effect=lambda _method,source,**_kw:
                            'requested' if 'requestPause(' in source else json.dumps(status))
            with patch('integration.issac.native_game.time.sleep'),patch(
                    'integration.issac.native_game.time.monotonic',side_effect=range(100)):
                with self.assertRaisesRegex(AdmissionError,'NORMAL_PAUSE_INPUT_ACK_PENDING'):native.pause()
            native.menu_key.assert_not_called()
            self.assertFalse((Path(root)/'state/isaac-strategy/pause-receipt.json').exists())

    def test_only_matching_input_ack_and_two_stable_native_samples_create_a_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            native=self.fixture(root);native.rpc=Mock(return_value=json.dumps(proof()))
            with patch('integration.issac.native_game.time.sleep'):receipt=native.pause()
            self.assertTrue(receipt['normal_game_pause_acknowledged'])
            self.assertEqual(receipt['pause_input_ack']['id'],'actual-input')
            self.assertTrue(receipt['pause_hold']);native.menu_key.assert_not_called()

    def test_actual_death_is_an_ended_run_and_never_a_pause_menu(self):
        with tempfile.TemporaryDirectory() as root:
            native=self.fixture(root);native.observe.return_value['dead']=True;native.rpc=Mock()
            self.assertTrue(native.pause()['no_active_run']);native.rpc.assert_not_called()


class CanonicalNativeRoom(unittest.TestCase):
    def observed(self,entrance,canonical):
        from lupa.lua53 import LuaRuntime
        lua=LuaRuntime(unpack_returned_tuples=True)
        descriptor='nil' if canonical is None else '{SafeGridIndex='+str(canonical)+'}'
        lua.execute('''local descriptor='''+descriptor+'''
            local level={GetStage=function() return 3 end,
                GetCurrentRoomIndex=function() return '''+str(entrance)+''' end,
                GetCurrentRoomDesc=function() return descriptor end}
            local player={IsDead=function() return false end,
                GetHearts=function() return 10 end,GetSoulHearts=function() return 6 end}
            local game={GetNumPlayers=function() return 1 end,GetLevel=function() return level end,
                IsPaused=function() return true end,GetFrameCount=function() return 900 end,
                GetSeeds=function() return {GetStartSeed=function() return 123 end} end}
            Game=function() return game end;Isaac={GetPlayer=function() return player end}
            __NativeIsaacController={}
        ''')
        return json.loads(lua.execute(OBSERVE))

    def test_actual_observe_lua_canonicalizes_large_room_aliases_and_preserves_special_rooms(self):
        for entrance,canonical,wanted in [(110,97,97),(97,97,97),(-1,97,-1),(110,None,110)]:
            with self.subTest(entrance=entrance,canonical=canonical):
                result=self.observed(entrance,canonical)
                self.assertEqual(result['room'],wanted)
                self.assertEqual(result['frame'],900);self.assertTrue(result['paused'])

    def test_large_room_pause_uses_same_identity_without_relaxing_readiness_checks(self):
        identity={'controller':'current','seed':123,'room':97,'stage':3,'bridge':'current','visit':2}
        sample={'state':{'connected':True,'age_ms':50,'identity':identity,
                    'data':{'frame':900,'room':{'paused':True,'clear':True,'dead':False}}},
            'game':{'armed':False,'control_revision':8},'studio':{'ready':True,'natural_action':{
                'kind':'drink','control_revision':8,'identity':dict(identity),'created_unix':1000,'expires_unix':1060,
                'native_receipt':{'normal_game_pause_acknowledged':True,'stable_frame':900,
                    'native':self.observed(110,97)}}}}
        self.assertTrue(verified_drink_pause(sample,1001))
        sample['studio']['natural_action']['native_receipt']['native']['room']=110
        self.assertFalse(verified_drink_pause(sample,1001))


if __name__=='__main__':unittest.main()
