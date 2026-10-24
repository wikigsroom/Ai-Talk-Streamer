"""Exercise audio tails, stale requests, engine identity and full-reply buffering."""
from pathlib import Path
from enum import Enum
from io import BytesIO
from queue import Queue
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
import importlib.util
import json
import os
import tempfile
import unittest
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class State(Enum):
    RUNNING = 0
    PAUSE = 1


class Base:
    def __init__(self, opt, parent):
        self.opt, self.parent = opt, parent
        self.sample_rate, self.chunk = 16000, 320
        self.msgqueue, self.state = Queue(), State.RUNNING


def dependencies():
    base = ModuleType('tts.base_tts')
    base.BaseTTS, base.State = Base, State
    registry = ModuleType('registry')
    registry.register = lambda *args: lambda cls: cls
    logger = ModuleType('utils.logger')
    logger.logger = Mock()
    identity = ModuleType('server.character_identity')
    identity.conversation_prompt = lambda value: value
    return {'tts.base_tts': base, 'registry': registry,
            'utils.logger': logger, 'server.character_identity': identity}


class Parent:
    _studio_generation = 7

    def __init__(self):
        self.frames, self.events, self.messages = [], [], []

    def put_audio_frame(self, frame, info):
        self.frames.append((frame.copy(), info))

    def send_msg(self, event):
        self.events.append(json.loads(event))

    def put_msg_txt(self, text, info):
        self.messages.append((text, info))


class MossLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict('sys.modules', dependencies()):
            cls.adapter = load('tts.moss', 'integration/moss_tts.py')
            cls.llm = load('moss_llm_test', 'integration/llm_channel.py')
        cls.service = load('moss_service_test', 'integration/moss_service.py')

    def make_adapter(self):
        parent = Parent()
        instance = self.adapter.MossTTS(SimpleNamespace(TTS_SERVER='http://127.0.0.1:9880'), parent)
        return instance, parent

    def response(self, engine='MOSS-TTSD-v1.0'):
        # Resampling 481 samples to 16 kHz leaves a one-sample final frame.
        source = np.linspace(.1, .3, 481, dtype=np.float32)
        output = BytesIO()
        sf.write(output, source, 24000, format='WAV', subtype='FLOAT')
        response = Mock(content=output.getvalue(), headers={
            'X-TTS-Engine': engine, 'X-TTS-Voice': 'v04', 'Content-Type': 'audio/wav'})
        return response, source

    def test_final_partial_frame_is_retained_and_padded(self):
        adapter, parent = self.make_adapter()
        response, source = self.response()
        adapter.http = Mock()
        adapter.http.post.return_value = response
        adapter.txt_to_audio(('完整结尾。', {'generation': 7}))
        self.assertEqual(len(parent.frames), 3)  # two audio frames and one end marker
        actual = np.concatenate([frame for frame, _ in parent.frames[:-1]])
        expected = resample_poly(source, 2, 3)
        np.testing.assert_allclose(actual[:len(expected)], expected, atol=1e-6)
        np.testing.assert_array_equal(actual[len(expected):], 0)
        self.assertEqual(parent.frames[0][1]['status'], 'start')
        self.assertEqual(parent.frames[-1][1]['status'], 'end')

    def test_wrong_engine_is_rejected_and_next_request_recovers(self):
        adapter, parent = self.make_adapter()
        adapter.http = Mock()
        adapter.http.post.return_value = self.response('different-engine')[0]
        adapter.txt_to_audio(('第一条。', {'generation': 7}))
        self.assertFalse(parent.frames)
        self.assertEqual(parent.events[-1]['status'], 'error')
        adapter.http.post.return_value = self.response()[0]
        adapter.txt_to_audio(('第二条。', {'generation': 7}))
        self.assertTrue(parent.frames)

    def test_stale_generation_never_submits_or_plays(self):
        adapter, parent = self.make_adapter()
        adapter.http = Mock()
        adapter.txt_to_audio(('旧消息。', {'generation': 6}))
        adapter.http.post.assert_not_called()
        self.assertFalse(parent.frames)

    def test_interruption_while_waiting_discards_the_entire_result(self):
        adapter, parent = self.make_adapter()
        response, _ = self.response()
        def interrupted(*args, **kwargs):
            adapter.epoch += 1
            return response
        adapter.http = Mock()
        adapter.http.post.side_effect = interrupted
        adapter.txt_to_audio(('过期播报。', {'generation': 7}))
        self.assertFalse(parent.frames)
        self.assertIsNone(adapter.active_request)

    def test_cancel_before_queue_registration_does_not_touch_model(self):
        engine = self.service.MossEngine({'voice_id': 'v04', 'label': 'test'})
        engine.ready = True
        engine.cancel('already-interrupted')
        with self.assertRaises(self.service.Cancelled):
            engine.synthesize('不要播报。', 'already-interrupted')

    def test_long_text_partition_preserves_every_character(self):
        text = ('你好，今天想聊什么？ 这是有标点的一句话。\n' + '没有标点' * 40) * 2
        parts = self.service.split_text(text)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(len(part) <= 70 for part in parts))

    def test_moss_buffers_the_complete_cloud_reply(self):
        parent = Parent()
        parent.tts = SimpleNamespace(requires_complete_reply=True)
        chunks = ['你好，', '欢迎。', '我们慢慢', '聊。']
        client = Mock()
        client.chat.completions.create.return_value = iter([
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]) for text in chunks])
        module = ModuleType('openai')
        module.OpenAI = Mock(return_value=client)
        values = {'AVATAR_LLM_BASE_URL': 'http://127.0.0.1:9999', 'AVATAR_LLM_API_KEY': 'test-only',
                  'AVATAR_LLM_MODEL': 'test-model', 'AVATAR_LLM_PROTOCOL': 'chat_completions'}
        with patch.dict('sys.modules', {'openai': module}), patch.dict(os.environ, values):
            self.llm.llm_response('测试', parent, {'generation': 7})
        self.assertEqual(parent.messages, [(''.join(chunks), {'generation': 7})])
        client.close.assert_called_once()

    def test_stop_matches_registered_external_moss_interpreter_and_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runtime = ModuleType('runtime_environment')
            runtime.ROOT, runtime.environment = root, Mock()
            with patch.dict('sys.modules', {'runtime_environment': runtime}):
                launcher = load('moss_launch_test', 'scripts/launch.py')
            script = str(root / 'integration/moss_service.py')
            python = str(root.parent / 'shared-comfy-python/python.exe')
            command = [python, '-X', 'utf8', '-B', script]
            (root / '.setup').mkdir()
            (root / '.setup/services.json').write_text(json.dumps({
                'tts': {'pid': 1, 'command': command, 'started': 200}}), encoding='utf-8')
            def process(pid, args, started=200):
                item = Mock()
                item.info = {'pid': pid, 'exe': python, 'cmdline': args}
                item.create_time.return_value = started
                return item
            selected = process(1, command)
            unrelated = process(2, [python, 'main.py'])
            older = process(3, command, 100)
            psutil = ModuleType('psutil')
            psutil.process_iter = Mock(return_value=[selected, unrelated, older])
            psutil.wait_procs = Mock()
            psutil.NoSuchProcess = psutil.AccessDenied = RuntimeError
            with patch.dict('sys.modules', {'psutil': psutil}):
                launcher.stop_services('tts')
            selected.terminate.assert_called_once()
            unrelated.terminate.assert_not_called()
            older.terminate.assert_not_called()
            psutil.wait_procs.assert_called_once_with([selected], timeout=10)

    def test_startup_finishes_avatar_initialization_before_loading_moss(self):
        launch = ModuleType('launch')
        opened, calls = set(), []
        launch.port_open = lambda port: port in opened
        def start_service(name):
            calls.append(name)
            opened.add(8010 if name == 'avatar' else 9880)
        launch.start_service = start_service
        with patch.dict('sys.modules', {'launch': launch}):
            starter = load('moss_start_test', 'scripts/start_studio.py')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'configs').mkdir()
            (root / 'configs/livetalking.yaml').write_text(json.dumps({
                'tts': 'moss-ttsd', 'MOSS_VOICE_ID': 'v04'}), encoding='utf-8')
            starter.ROOT = root
            response = Mock()
            response.__enter__ = Mock(return_value=BytesIO(json.dumps({
                'ready': True, 'engine': 'MOSS-TTSD-v1.0', 'voice_id': 'v04'}).encode()))
            response.__exit__ = Mock(return_value=False)
            http = Mock()
            http.open.return_value = response
            with patch.object(starter.urllib.request, 'build_opener', return_value=http):
                starter.start()
            self.assertEqual(calls, ['avatar', 'tts'])
            calls.clear()
            opened.remove(8010)
            with self.assertRaisesRegex(RuntimeError, 'Stop both project services'):
                starter.start()
            self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
