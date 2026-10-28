"""Contracts for approved identity, serial failover, cancellation and exact PCM tails."""
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
import importlib.util, json, sys, tempfile, threading, unittest, wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_moss_live import dependencies, Parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class Reply(BytesIO):
    def __init__(self,data,headers=None):
        super().__init__(data);self.headers=headers or {}


def audio():
    b=BytesIO()
    with wave.open(b,'wb')as f:
        f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(b'\x10\x01'*481)
    return b.getvalue()


class ResidentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service=load('resident_service_test','integration/resident_tts_service.py')
        cls.worker=load('resident_worker_test','integration/resident_tts_worker.py')
        with patch.dict(sys.modules,dependencies()):
            cls.adapter=load('tts.resident_local','integration/resident_tts.py')

    def broker(self):
        config={'release':'test','default_voice_id':'O07','automatic_fallback':True,
                'reference_sha256':'a'*64,'synthesis_timeout_seconds':90,
                'voices':{'O07':{'port':9881},'F07':{'port':9882}}}
        b=self.service.Broker(config,Path('test.json'));b.initializing=False
        b.poll=Mock(return_value={'ready':True});return b

    def response(self,voice):
        return Reply(audio(),{'X-TTS-Engine':self.service.ENGINES[voice],
             'X-TTS-Voice':voice,'X-TTS-Reference-SHA256':'a'*64,'X-TTS-Model-Seconds':'1.2'})

    def test_default_uses_approved_primary_without_fallback(self):
        b=self.broker();b.rpc=Mock(return_value=self.response('O07'))
        wav,m=b.synthesize('你好。','first')
        self.assertEqual((m['voice_id'],m['fallback']),('O07',False))
        self.assertEqual(wav,audio());self.assertEqual(b.rpc.call_count,1)

    def test_real_failure_selects_only_approved_backup(self):
        b=self.broker();b.rpc=Mock(side_effect=[OSError('offline'),self.response('F07')]);b.quiesce=Mock()
        _,m=b.synthesize('你好。','fallback')
        self.assertEqual((m['voice_id'],m['fallback']),('F07',True))
        self.assertEqual([x.args[0]for x in b.rpc.call_args_list],['O07','F07'])
        b.quiesce.assert_called_once_with('O07','fallback')

    def test_interrupted_primary_does_not_trigger_backup(self):
        b=self.broker()
        def interrupted(*args,**kwargs):
            b.cancelled['cancelled']=0
            return self.response('O07')
        b.rpc=Mock(side_effect=interrupted)
        with self.assertRaises(self.service.Cancelled):b.synthesize('不要播报。','cancelled')
        self.assertEqual(b.rpc.call_count,1)
        self.assertFalse(b.tasks);self.assertIsNone(b.active)

    def test_cancel_before_registration_never_touches_worker(self):
        b=self.broker();b.cancelled['old']=0;b.rpc=Mock()
        with self.assertRaises(self.service.Cancelled):b.synthesize('旧请求。','old')
        b.rpc.assert_not_called()

    def test_manual_backup_never_silently_retries_primary(self):
        b=self.broker();b.rpc=Mock(side_effect=OSError('offline'));b.quiesce=Mock()
        with self.assertRaises(RuntimeError):b.synthesize('备用。','manual','F07')
        self.assertEqual(b.rpc.call_count,1)

    def test_identity_mismatch_cannot_escape_when_failover_disabled(self):
        b=self.broker();wrong=self.response('O07');wrong.headers['X-TTS-Reference-SHA256']='bad'
        b.rpc=Mock(return_value=wrong);b.quiesce=Mock()
        with self.assertRaises(RuntimeError):b.synthesize('核验。','wrong',allow_fallback=False)

    def test_switch_is_rejected_while_request_is_queued(self):
        b=self.broker();b.tasks['queued']=0
        with self.assertRaises(RuntimeError):b.select('F07')
        self.assertEqual(b.selection,'O07')

    def test_timeout_must_stop_own_worker_before_backup(self):
        b=self.broker();child=Mock();child.poll.return_value=None;b.children['O07']=child
        b.poll=Mock(return_value={'busy':True,'ready':True});b.rpc=Mock(side_effect=OSError('timeout'))
        b.stop_child=Mock()
        b.quiesce('O07','slow')
        b.stop_child.assert_called_once_with('O07')

    def test_windows_venv_descendants_stop_before_launcher(self):
        b=self.broker();child=Mock();child.poll.return_value=None;b.children['O07']=child
        process=Mock();process.cmdline.return_value=[str(self.service.ROOT/'integration/resident_tts_worker.py')]
        process.exe.return_value=str(self.service.ROOT/'runtime/python/python.exe')
        fake=SimpleNamespace(Process=Mock(return_value=SimpleNamespace(children=Mock(return_value=[process]))),
            wait_procs=Mock(return_value=([process],[])),NoSuchProcess=ProcessLookupError)
        with patch.object(self.service.os,'name','nt'),patch.dict(sys.modules,{'psutil':fake}):
            b.stop_child('O07')
        process.terminate.assert_called_once();fake.wait_procs.assert_called_once()
        child.terminate.assert_called_once();child.wait.assert_called_once_with(timeout=10)

    def test_partition_preserves_text_punctuation_and_long_runs(self):
        text=('你好。 继续说！\n'+'长句'*120)*2
        parts=self.worker.partition(text)
        self.assertEqual(''.join(parts),text);self.assertTrue(all(len(x)<=140 for x in parts))

    def adapter_response(self,voice='O07',reference='a'*64):
        return Mock(content=audio(),headers={'Content-Type':'audio/wav','X-TTS-Engine':self.service.ENGINES[voice],
             'X-TTS-Voice':voice,'X-TTS-Reference-SHA256':reference,'X-TTS-Fallback':'true'if voice=='F07'else'false'})

    def test_adapter_reports_actual_backup_and_retains_partial_tail(self):
        p=Parent();a=self.adapter.ResidentTTS(SimpleNamespace(TTS_SERVER='http://127.0.0.1:9880',TTS_REFERENCE_SHA256='a'*64),p)
        a.http=Mock();a.http.post.return_value=self.adapter_response('F07');a.txt_to_audio(('测试。',{'generation':7}))
        frames=p.frames[:-1];self.assertEqual(sum(x[1]['valid_samples']for x in frames),321)
        self.assertTrue(all(x[1]['voice_id']=='F07'for x in p.frames))
        self.assertEqual(p.frames[-1][1]['status'],'end')
        self.assertTrue(any(x.get('status')=='tts_fallback'for x in p.events))

    def test_adapter_rejects_wrong_reference_and_stale_result(self):
        p=Parent();a=self.adapter.ResidentTTS(SimpleNamespace(TTS_SERVER='http://127.0.0.1:9880',TTS_REFERENCE_SHA256='a'*64),p)
        a.http=Mock();a.http.post.return_value=self.adapter_response(reference='different')
        a.txt_to_audio(('错误。',{'generation':7}));self.assertFalse(p.frames)
        def stale(*args,**kwargs):a.epoch+=1;return self.adapter_response()
        a.http.post.side_effect=stale;a.txt_to_audio(('过期。',{'generation':7}));self.assertFalse(p.frames)


if __name__=='__main__':unittest.main()
