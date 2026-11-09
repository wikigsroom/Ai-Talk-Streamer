"""Exercise real native FFmpeg with audible synthetic PCM, never private speech."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from integration.issac.av_export import inspect,mux_review,trim_official
from integration.issac.common import AdmissionError
from integration.issac.materials import ffmpeg

ROOT=Path(__file__).resolve().parents[3]


class ActualAudioExport(unittest.TestCase):
    def encode(self,*arguments):
        subprocess.run([ffmpeg(ROOT),'-hide_banner','-v','error','-n',*arguments],
            check=True,capture_output=True,timeout=90,creationflags=0x08000000)

    def test_raw_h264_and_pcm_produce_all_frames_and_an_audible_audio_track(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            self.encode('-f','lavfi','-i','testsrc2=size=128x128:rate=25:duration=2',
                '-c:v','libx264','-threads','2','-f','h264',str(folder/'actual.h264'))
            self.encode('-f','lavfi','-i','sine=frequency=440:sample_rate=16000:duration=2',
                '-c:a','pcm_s16le','-f','s16le',str(folder/'actual.s16le'))
            report=mux_review(ROOT,folder,50,sound_required=True)
            self.assertEqual(report['decoded_frames'],50)
            self.assertGreater(report['audio_rms'],1000)
            self.assertAlmostEqual(report['decoded_audio_samples']/16000,2,delta=.05)
            with self.assertRaises(AdmissionError):inspect(ROOT,folder/'review.mp4',49,25)

    def test_fractional_recording_offset_keeps_exact_continuous_frame_count(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);raw=folder/'official.mp4';final=folder/'continuous.mp4'
            self.encode('-f','lavfi','-i','testsrc2=size=1920x1080:rate=30:duration=2.2',
                '-f','lavfi','-i','sine=frequency=660:sample_rate=48000:duration=2.2',
                '-c:v','libx264','-threads','2','-preset','ultrafast','-c:a','aac',str(raw))
            report=trim_official(ROOT,raw,final,.137,1)
            self.assertEqual(report['decoded_frames'],30)
            self.assertGreater(report['audio_rms'],1000)
            self.assertAlmostEqual(float(report['probe']['streams'][0]['duration']),1,delta=.002)
