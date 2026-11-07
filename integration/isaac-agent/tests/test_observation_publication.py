"""Readers must see a complete observation, even during writes or failures."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.snapshots import publish_json


class ObservationPublicationTests(unittest.TestCase):
    def test_live_reader_never_observes_partial_or_mixed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'observation.json'
            publish_json(target,{'revision':0,'payload':'0'*32768})
            stop=threading.Event()
            failures=[]
            reads=[]
            def reader():
                while not stop.is_set():
                    try:
                        value=json.loads(target.read_text('utf8'))
                        if value['payload']!=str(value['revision'])*32768:
                            failures.append('mixed observation')
                        reads.append(value['revision'])
                    except PermissionError:
                        continue
                    except Exception as error:
                        failures.append(repr(error))
            thread=threading.Thread(target=reader)
            thread.start()
            try:
                for revision in range(1,40):
                    publish_json(target,{'revision':revision,'payload':str(revision)*32768})
            finally:
                stop.set()
                thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertTrue(reads)
            self.assertEqual(failures,[])
            self.assertEqual(json.loads(target.read_text('utf8'))['revision'],39)

    def test_failed_publication_preserves_last_complete_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'observation.json'
            publish_json(target,{'frame':123})
            with patch.object(Path,'replace',side_effect=PermissionError('reader holds file')):
                with self.assertRaises(PermissionError):
                    publish_json(target,{'frame':124},timeout=0)
            self.assertEqual(json.loads(target.read_text('utf8')),{'frame':123})
            self.assertEqual(list(Path(directory).glob('*.tmp')),[])


if __name__=='__main__':unittest.main()
