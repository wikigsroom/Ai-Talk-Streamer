from copy import deepcopy
from pathlib import Path
import struct
import tempfile
import unittest

from integration.issac.common import AdmissionError,inside,local_url
from integration.issac.events import GameEvents
from integration.issac.game_policy import FairPolicy,RunGoal,decision_fence,health_for_wiki
from integration.issac.media_protocol import MediaProfile
from integration.issac.wiki import arguments


class GameBoundaries(unittest.TestCase):
    def test_hidden_information_is_removed_before_any_policy(self):
        raw={'start_seed':1,'restart_count':0,'layout':{'bomb_walls':[{'room':4}]},
            'strategy':{'bridge_generation':1,'map':[{'index':7,'display_flags':0,'visited':0},{'index':8,'visited':1}],
            'pockets':[{'kind':'pill','effect':42,'effect_name':'bad','identified':False}]}}
        original=deepcopy(raw);filtered=FairPolicy().filter(raw)
        self.assertEqual(raw,original);self.assertEqual(filtered['layout']['bomb_walls'],[])
        self.assertEqual([x['index'] for x in filtered['strategy']['map']],[8])
        self.assertNotIn('effect',filtered['strategy']['pockets'][0])
        self.assertEqual(filtered['run_goal']['unlocks'],'unknown')

    def test_cost_prerequisite_change_invalidates_even_after_room_returns(self):
        raw={'coins':15,'bombs':3,'keys':1,'strategy':{'inventory_revision':'same','health':{'red_hearts':6}}}
        first=decision_fence(raw);raw['coins']=0;second=decision_fence(raw)
        self.assertNotEqual(first,second);raw['coins']=15
        self.assertEqual(first,decision_fence(raw)) # Per-decision revision adds the ABA fence.
        with self.assertRaises(AdmissionError):RunGoal('satan').validate({'seed':1})

    def test_wiki_health_types_and_command_boundary(self):
        result=health_for_wiki({'red_hearts':5,'soul_hearts':3,'bone_hearts':2,'black_hearts_bitmask':5,'exact':True})
        self.assertEqual(result['red_hearts'],2.5);self.assertEqual(result['bone_hearts'],2)
        self.assertEqual(result['black_hearts_bitmask'],5)
        for query in [{'operation':'sql','query':'DROP TABLE items'}, {'operation':'item','query':'--edition=rep+'},
                      {'operation':'item','query':'D6','edition':'rep+'},{'operation':'show','query':'D6','path':'elsewhere'}]:
            with self.assertRaises(AdmissionError):arguments(query)

    def test_local_model_endpoint_and_private_path_boundaries(self):
        for url in ['https://127.0.0.1:1234/v1','http://localhost:1234/v1','http://example.com:1234/v1','http://127.0.0.1:1234/v1?redirect=x']:
            with self.assertRaises(AdmissionError):local_url(url)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(AdmissionError):inside(temp,'../private.wav')


class SpeechCausality(unittest.TestCase):
    def snapshot(self,room=1,bridge='current'):
        return {'identity':{'controller':'own','seed':123,'restart':0,'bridge':bridge,'room':room,'stage':1},
            'frame':1,'room':{'clear':False,'dead':False,'paused':False},'health':{}}

    def test_accepted_is_not_spoken_and_preview_is_not_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            events=GameEvents(temp);events.ingest(self.snapshot());reserved=events.reserve()
            events.accepted(reserved['nonce'],'request-1')
            self.assertEqual(events.read()['events'][0]['delivery'],'accepted')
            for authority in ['preview','admin']:
                with self.assertRaises(AdmissionError):events.playback_receipt('request-1',{'authority':authority,
                    'request_id':'request-1','actual_pcm_samples':16000,'completed':True})
            events.playback_receipt('request-1',{'authority':'official_source','request_id':'request-1',
                'actual_pcm_samples':16000,'completed':True})
            self.assertEqual(events.read()['events'][0]['delivery'],'spoken');events.close()

    def test_restart_never_replays_interrupted_or_old_room_events(self):
        with tempfile.TemporaryDirectory() as temp:
            events=GameEvents(temp);events.ingest(self.snapshot());reserved=events.reserve()
            events.accepted(reserved['nonce'],'request-2');events.close()
            events=GameEvents(temp);current=self.snapshot(room=2,bridge='new');current['frame']=121
            events.ingest(current);self.assertIsNone(events.reserve())
            self.assertEqual(events.read()['events'][0]['delivery'],'interrupted_unknown');events.close()

    def test_frame_watermark_is_coalesced_but_actual_health_facts_are_immediately_durable(self):
        import json,sqlite3
        now=[1000.0]
        with tempfile.TemporaryDirectory() as temp:
            events=GameEvents(temp,clock=lambda:now[0]);first=self.snapshot()
            first['health']={'exact':True,'red_hearts':6,'soul_hearts':0}
            events.ingest(first)
            for frame in range(2,12):
                now[0]+=.05;current=deepcopy(first);current['frame']=frame;events.ingest(current)
            current['health']['red_hearts']=4;events.ingest(current)
            with sqlite3.connect(events.path) as durable:
                watermark=json.loads(durable.execute("SELECT value FROM metadata WHERE key='last_observation'").fetchone()[0])
                facts=[json.loads(row[0]) for row in durable.execute('SELECT body FROM events')]
            self.assertEqual(watermark['frame'],1)
            health=next(row for row in facts if row['type']=='health_changed')
            self.assertEqual(health['facts']['after_half_hearts'],4)
            self.assertEqual(health['frame'],11)
            events.close()


class ActualAvc(unittest.TestCase):
    def test_profile_has_actual_parameter_sets_and_rejects_resize_without_idr(self):
        profile=MediaProfile();sps=b'\x67\x42\x00\x1f\xaa';pps=b'\x68\xce\x06';idr=b'\x65\x88'
        packet=b'AVC1'+struct.pack('<I',1)+b''.join(b'\0\0\0\1'+u for u in [sps,pps,idr])
        encoded,init=profile.packet(packet,512,512)
        self.assertEqual(init['codec'],'avc1.42001f');self.assertEqual(init['audio']['sample_rate'],16000)
        self.assertEqual(encoded[8:12],struct.pack('>I',len(sps)))
        with self.assertRaises(ValueError):profile.packet(b'AVC1'+struct.pack('<I',0)+b'\0\0\1\x41\x01',640,640)


if __name__=='__main__':unittest.main()
