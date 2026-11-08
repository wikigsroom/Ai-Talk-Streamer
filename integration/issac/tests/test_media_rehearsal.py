"""The rehearsal's actual child contract must agree with native shutdown."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from integration.issac.common import AdmissionError
from integration.issac.shutdown import media_rehearsal_stops,stop_path


class StopContractTests(unittest.TestCase):
    def test_both_children_accept_their_candidate_scoped_normal_stop_request(self):
        with tempfile.TemporaryDirectory() as directory:
            first=media_rehearsal_stops(directory,'issac-0123456789ab-01234567')
            second=media_rehearsal_stops(directory,'issac-0123456789ab-89abcdef')
            self.assertEqual(len(set(first+second)),4)
            for path in first+second:
                with patch.dict(os.environ,{'ISSAC_STOP_FILE':str(path)}):
                    self.assertEqual(stop_path(directory),path)
            with patch.dict(os.environ,{'ISSAC_STOP_FILE':str(Path(directory)/'state/issac-stream/media30-voice.stop')}):
                with self.assertRaisesRegex(AdmissionError,'OWNED_STOP_FILE_SCOPE_REQUIRED'):stop_path(directory)

    def test_unfrozen_candidate_cannot_name_owned_stop_requests(self):
        for value in ('../other','issac-main','issac-'+('0'*40)):
            with self.assertRaises(AdmissionError):media_rehearsal_stops('.',value)
