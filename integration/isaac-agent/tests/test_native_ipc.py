"""A short Windows file-sharing conflict must not stop unattended gameplay."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_ipc import atomic_json
import native_request


class NativeIPCTests(unittest.TestCase):
    def test_transient_sharing_violation_retries_complete_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'reply.json'
            replace=Path.replace
            attempts=[]
            def busy_then_publish(source,destination):
                attempts.append(source)
                if len(attempts)<3: raise PermissionError('simulated Windows reader')
                return replace(source,destination)
            with patch.object(Path,'replace',busy_then_publish): atomic_json(target,{'id':'one','result':'alive'})
            self.assertEqual(json.loads(target.read_text()),{'id':'one','result':'alive'})
            self.assertEqual(len(attempts),3)
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])

    def test_permanent_failure_is_bounded_and_removes_own_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'reply.json'
            target.write_text('{"old":true}')
            with patch.object(Path,'replace',side_effect=PermissionError('busy')):
                with self.assertRaises(PermissionError): atomic_json(target,{'new':True},timeout=0)
            self.assertEqual(json.loads(target.read_text()),{'old':True})
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])

    def test_reply_read_sharing_conflict_keeps_request_and_recovers(self):
        attempts=[]
        identity='same-request'
        def read_reply(path,**kwargs):
            attempts.append(path)
            if len(attempts)<3: raise PermissionError('Windows rename in progress')
            return json.dumps({'id':identity,'ok':True,'result':{'slot':3}})
        with patch.object(native_request.uuid,'uuid4') as unique, \
             patch.object(native_request,'atomic_json') as publish, \
             patch.object(Path,'read_text',read_reply):
            unique.return_value.hex=identity
            self.assertEqual(native_request._request(op='progress',timeout=1),{'slot':3})
        self.assertEqual(len(attempts),3)
        self.assertEqual(publish.call_count,1)

    def test_reply_permanent_sharing_conflict_times_out(self):
        with patch.object(native_request,'atomic_json'), \
             patch.object(Path,'read_text',side_effect=PermissionError('busy')):
            with self.assertRaises(TimeoutError):
                native_request._request(op='progress',timeout=.01)


if __name__=='__main__': unittest.main()
