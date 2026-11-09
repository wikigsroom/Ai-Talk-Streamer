"""Exercise the actual programme pump across body events and a media failure."""
import asyncio
from collections import Counter
from collections import deque
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import threading
import unittest
from unittest.mock import AsyncMock,patch

import numpy as np
from aiohttp import ClientSession,WSMsgType,web

from integration.issac.common import AdmissionError,Audit
from integration.issac.studio import IsaacStudio
from integration.naimei_media import CommandFence,SILENCE


class BodyFixture:
    def __init__(self,fail=False):
        self.event=None;self.frames=0;self.fail=fail

    def next(self,**_):
        if self.fail:raise AdmissionError('ACCEPTED_BODY_CLIP_CHANGED')
        self.frames+=1
        if self.frames in (1,3):
            self.event={'id':f'clip-{self.frames}','kind':'controller','mode':'M03','at_unix':123.0}
        return np.full((512,512,3),self.frames,np.uint8)

    def status(self):
        return {'mode':'M03','drinking':False,'clip_frame':self.frames,'last_event':self.event}


class EncoderFixture:
    def __init__(self):self.images=[]
    def encode(self,image,sequence,**_):
        self.images.append((sequence,int(image[0,0,0])))
        return b'encoded-frame',None


class ProfileFixture:
    def packet(self,encoded,*_):return encoded,{'stream_id':'fixture'}


class ProgrammePumpTests(unittest.IsolatedAsyncioTestCase):
    def studio(self,folder,*,fail=False):
        studio=object.__new__(IsaacStudio)
        studio.body=BodyFixture(fail);studio.source_queue=asyncio.Queue()
        studio.mapping=None;studio.speech_task=None;studio.pending_mode=None
        studio.last_body_event=None;studio.media_fault=False;studio.media_error=None
        studio.game_state={};studio.stats=Counter();studio.viewers={}
        studio.last_telemetry=time.monotonic()+3600;studio.audit=Audit(folder/'events.jsonl')
        studio.game_event_tasks=set();studio.stopping=False;studio.cleanup_started=False
        studio.emit=AsyncMock();studio.native_call=AsyncMock(return_value={'native_receipt':{'no_active_run':True}})
        studio.root=folder;studio.prepared=asyncio.Queue(maxsize=24);studio.prepared_ready=asyncio.Event()
        studio.prepare_sequence=studio.sequence=0;studio.published_body=studio.body.status()
        studio.mouth_lock=threading.Lock();studio.mode='M03';studio.media=ProfileFixture();studio.encoder=EncoderFixture()
        studio.web_revision='test-revision';studio.keyframe=True;studio.sent_at=None;studio.intervals=deque(maxlen=1500)
        studio.fence=CommandFence();studio.state='idle';studio.sample_mouth=None
        return studio

    async def test_action_kind_does_not_mask_log_kind_or_stop_real_frame_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);studio=self.studio(folder);seen=asyncio.Event()
            studio.emit=IsaacStudio.emit.__get__(studio)
            async def published(frame):
                await IsaacStudio.publish(studio,frame)
                if studio.sequence>=3:seen.set()
            studio.publish=published
            tasks=[asyncio.create_task(studio.pump()),asyncio.create_task(studio.playout())]
            try:await asyncio.wait_for(seen.wait(),2)
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
            rows=[json.loads(line) for line in (folder/'events.jsonl').read_text('utf8').splitlines()]
            self.assertEqual([row['kind'] for row in rows],['body_clip_started','body_clip_started'])
            self.assertEqual([row['body_event']['kind'] for row in rows],['controller','controller'])
            self.assertEqual([row['body_event']['id'] for row in rows],['clip-1','clip-3'])
            self.assertEqual(studio.stats['output_frames'],3)
            self.assertGreaterEqual(studio.body.frames,12)
            self.assertFalse(studio.media_fault);studio.native_call.assert_not_awaited()

    async def test_media_failure_stops_output_closes_viewers_and_requests_normal_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);studio=self.studio(folder,fail=True)
            viewer=type('Viewer',(),{'close':AsyncMock()})()
            studio.viewers={viewer:None}
            await asyncio.wait_for(studio.pump(),2)
            self.assertTrue(studio.media_fault)
            self.assertEqual(studio.media_error,'MEDIA_CONTINUITY_OR_MAPPING_REJECTED')
            self.assertEqual(studio.stage,'media_quality_or_protocol_fault')
            studio.emit.assert_not_awaited();viewer.close.assert_awaited_once()
            studio.native_call.assert_awaited_once_with({'action':'pause'})
            rows=[json.loads(line) for line in (folder/'events.jsonl').read_text('utf8').splitlines()]
            self.assertEqual([row['kind'] for row in rows],['media_frame_rejected','media_fault_normal_pause'])
            self.assertEqual(rows[0]['error_type'],'AdmissionError')
            self.assertEqual(rows[0]['reason'],'ACCEPTED_BODY_CLIP_CHANGED')

    async def test_normal_shutdown_releases_live_media_consumers_before_handler_drain(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=self.studio(Path(directory))
            studio.root=Path(directory);studio.web_revision='test-revision'
            studio.http=ClientSession();studio.cue_task=None
            studio.tasks=[asyncio.create_task(asyncio.Event().wait())]
            app=studio.application();app.on_startup.clear()
            runner=web.AppRunner(app,shutdown_timeout=2)
            await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            try:
                async with ClientSession() as observer:
                    socket=await observer.ws_connect(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/api/studio/stream?v=3&codec=h264&programme_revision=test-revision')
                    closed=asyncio.create_task(socket.receive())
                    await asyncio.wait_for(runner.cleanup(),1)
                    self.assertIn((await closed).type,{WSMsgType.CLOSE,WSMsgType.CLOSED})
                    self.assertFalse(studio.viewers);self.assertTrue(studio.http.closed)
            finally:await runner.cleanup()

    async def test_normal_shutdown_releases_actual_game_event_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=self.studio(Path(directory));studio.root=Path(directory)
            studio.http=ClientSession();studio.cue_task=None;studio.tasks=[]
            app=studio.application();app.on_startup.clear();runner=web.AppRunner(app,shutdown_timeout=4)
            await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            try:
                async with ClientSession() as observer:
                    response=await observer.get(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/api/dsh/game/events')
                    self.assertTrue((await response.content.readline()).startswith(b'event: state'))
                    self.assertEqual(len(studio.game_event_tasks),1)
                    await asyncio.wait_for(runner.cleanup(),1)
                    self.assertFalse(studio.game_event_tasks)
                    self.assertTrue(studio.http.closed);self.assertTrue(studio.stopping)
                    response.close()
            finally:await runner.cleanup()

    async def test_broken_speech_callback_and_consumer_do_not_skip_game_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);studio=self.studio(folder,fail=True)
            studio.mapping=SimpleNamespace(command={'request_id':'current-speech'})
            studio.fail=AsyncMock(side_effect=OSError('bridge disconnected'))
            viewer=type('Viewer',(),{'close':AsyncMock(side_effect=OSError('consumer disconnected'))})()
            studio.viewers={viewer:None}
            await asyncio.wait_for(studio.pump(),2)
            studio.native_call.assert_awaited_once_with({'action':'pause'})
            studio.emit.assert_not_awaited()
            rows=[json.loads(line) for line in (folder/'events.jsonl').read_text('utf8').splitlines()]
            self.assertEqual(rows[-1]['kind'],'media_fault_normal_pause')

    async def test_persisted_cancel_discards_old_frame_without_stopping_newer_speech(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=self.studio(Path(directory));studio.fence=CommandFence();studio.command_lock=asyncio.Lock();studio.command_tasks=set();studio.pending=[]
            old={'request_id':'old','utterance_id':'old-u','runtime_epoch':5,'generation':8,'text':'旧房间'}
            barrier={'barrier_id':'cancel-old','request_id':'old','runtime_epoch':5,'generation':8,'new_generation':9}
            receipt={'persisted':False,'cancelled':True,'barrier':barrier}
            studio.fence.speak(old);studio.cancel_source=AsyncMock();studio.broadcast_control=AsyncMock()
            await studio.discard_cancelled_frame(old,receipt)
            await asyncio.gather(*studio.command_tasks)
            studio.cancel_source.assert_awaited_once_with('old');studio.broadcast_control.assert_awaited_once_with(barrier)
            self.assertEqual(studio.fence.current,(5,9));self.assertFalse(studio.media_fault)
            newer={**old,'request_id':'new','utterance_id':'new-u','generation':10,'text':'当前房间'}
            studio.fence.speak(newer);studio.cancel_source.reset_mock();studio.broadcast_control.reset_mock()
            await studio.discard_cancelled_frame(old,receipt)
            studio.cancel_source.assert_not_awaited();studio.broadcast_control.assert_not_awaited()
            self.assertTrue(studio.fence.matches(newer));studio.native_call.assert_not_awaited()
            for change in ({'persisted':True},{'barrier':{**barrier,'request_id':'other'}},{'barrier':{**barrier,'new_generation':8}}):
                with self.assertRaises(AdmissionError):await studio.discard_cancelled_frame(old,{**receipt,**change})

    async def test_emit_cancel_response_never_encodes_or_publishes_stale_pcm(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=self.studio(Path(directory));studio.fence=CommandFence();studio.command_lock=asyncio.Lock();studio.command_tasks=set();studio.pending=[]
            old={'request_id':'old','utterance_id':'u','runtime_epoch':5,'generation':8,'text':'旧房间'}
            studio.fence.speak(old);studio.cancel_source=AsyncMock();studio.broadcast_control=AsyncMock()
            studio.api=AsyncMock(return_value={'persisted':False,'cancelled':True,'barrier':{
                'barrier_id':'cancel','request_id':'old','runtime_epoch':5,'generation':8,'new_generation':9}})
            # The invalid old mouth is never decoded; the next genuine moving
            # body frame survives cancellation at exactly the same sequence.
            original=studio.jpeg(np.full((512,512,3),37,np.uint8))
            await IsaacStudio.emit(studio,b'not an image',b'not publishable',old,original=original)
            await asyncio.gather(*studio.command_tasks)
            frame=studio.prepared.get_nowait()
            self.assertEqual(frame['sequence'],0);self.assertEqual(frame['jpeg'],original)
            self.assertEqual(frame['pcm'],SILENCE);self.assertIsNone(frame['metadata'])
            await studio.publish(frame)
            self.assertEqual(studio.encoder.images,[(0,37)])
            self.assertEqual(studio.stats['output_frames'],1)
            self.assertEqual(studio.stats['cancelled_frames_discarded'],1);self.assertFalse(studio.media_fault)

    async def test_buffered_frame_rechecks_cancel_and_mode_is_published_at_actual_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=self.studio(Path(directory))
            old={'request_id':'old','utterance_id':'u','runtime_epoch':5,'generation':8,'text':'旧房间','final':False}
            studio.fence.speak(old);studio.api=AsyncMock(return_value={'persisted':True,'map_revision':1})
            original=studio.jpeg(np.full((512,512,3),23,np.uint8))
            mouth=studio.jpeg(np.full((512,512,3),79,np.uint8))
            body={**studio.body.status(),'mode':'M01'}
            await IsaacStudio.emit(studio,mouth,bytes([9])*len(SILENCE),old,original=original,body_status=body,oral={'open':True})
            self.assertEqual(studio.mode,'M03');self.assertEqual(studio.stats['output_frames'],0)
            studio.fence.cancel({'runtime_epoch':5,'new_generation':9})
            queue=asyncio.Queue();studio.viewers={object():queue}
            with patch('integration.issac.studio.MediaProfile',ProfileFixture):
                await studio.publish(studio.prepared.get_nowait())
            envelope,packet=queue.get_nowait()
            self.assertEqual(studio.mode,'M01');self.assertEqual(studio.published_body,body)
            self.assertEqual(studio.encoder.images,[(0,23)]);self.assertIsNone(envelope['map'])
            self.assertEqual(packet[-len(SILENCE):],SILENCE)
            self.assertEqual(studio.stats['actual_audio_driven_mouth_frames'],0)
            self.assertEqual(studio.stats['buffered_cancelled_frames_discarded'],1)

    async def test_durable_mapping_delay_does_not_block_real_frame_playout(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=self.studio(Path(directory));done=asyncio.Event()
            command={'request_id':'current','utterance_id':'u','runtime_epoch':5,'generation':8,'text':'当前房间','final':False}
            studio.fence.speak(command)
            async def persisted(*_):
                if studio.prepare_sequence==18:await asyncio.sleep(.18)
                return {'persisted':True,'map_revision':1}
            studio.api=AsyncMock(side_effect=persisted)
            async def producer():
                due=time.perf_counter()
                for sequence in range(35):
                    await asyncio.sleep(max(0,due-time.perf_counter()));due+=.04
                    jpeg=studio.jpeg(np.full((512,512,3),sequence,np.uint8))
                    await IsaacStudio.emit(studio,jpeg,SILENCE,command,original=jpeg,oral={'open':True})
            async def published(frame):
                await IsaacStudio.publish(studio,frame)
                if studio.sequence==30:done.set()
            studio.publish=published
            tasks=[asyncio.create_task(producer()),asyncio.create_task(studio.playout())]
            try:await asyncio.wait_for(done.wait(),3)
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
            self.assertEqual(studio.encoder.images,[(i,i) for i in range(30)])
            self.assertGreater(studio.stats['media_map_max_us'],150000)
            self.assertLess(max(studio.intervals),.08)
            self.assertEqual(studio.stats['pump_stalls'],0);self.assertFalse(studio.media_fault)
            self.assertEqual(studio.stats['actual_audio_driven_mouth_frames'],30)

    async def test_exhausted_real_frame_queue_faults_instead_of_repeating_a_body_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=self.studio(Path(directory));studio.prepared_ready.set()
            await asyncio.wait_for(studio.playout(),1)
            self.assertEqual(studio.stats['output_frames'],0)
            self.assertEqual(studio.stats['pump_stalls'],1);self.assertTrue(studio.media_fault)
            studio.native_call.assert_awaited_once_with({'action':'pause'})

    async def test_drink_resume_waits_for_published_chain_end(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=self.studio(Path(directory));resumed=asyncio.Event()
            studio.changing_mode=False;studio.last_auto_drink=time.monotonic()
            studio.auto_drink={'started':True,'deadline':time.monotonic()+10,'identity':'same-room','control_revision':7}
            studio.published_body['drinking']=True
            studio.drink_sample=AsyncMock(return_value={'actual':'fresh pause proof'})
            async def control(value):resumed.set();return {}
            studio.native_call.side_effect=control
            task=asyncio.create_task(studio.natural_events())
            try:
                await asyncio.sleep(.05)
                studio.native_call.assert_not_awaited()
                studio.published_body['drinking']=False
                with patch('integration.issac.studio.verified_drink_pause',return_value=True):
                    await asyncio.wait_for(resumed.wait(),2)
                studio.native_call.assert_awaited_once_with({'action':'resume','expected_revision':7})
                self.assertIsNone(studio.auto_drink)
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)


if __name__=='__main__':unittest.main()
