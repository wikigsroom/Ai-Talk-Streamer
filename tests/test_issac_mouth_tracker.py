"""Compare the live native correlation with the previous numerical definition."""
import unittest
import numpy as np
from PIL import Image
from numpy.lib.stride_tricks import sliding_window_view
from integration.issac.mouth import Tracker,gray


class TrackerCorrelation(unittest.TestCase):
    def test_native_correlation_preserves_original_locations_and_confidence(self):
        rng=np.random.default_rng(81)
        reference=rng.integers(25,230,(512,512,3),dtype=np.uint8)
        for mode in ('M01','M02','M03'):
            tracker=Tracker(reference,mode)
            for dx,dy in [(0,0),(2,2),(-2,-2),(4,0),(0,4)]:
                frame=np.roll(reference,(dy,dx),(0,1));bx,by=tracker.x-48,tracker.y-28
                region=np.asarray(Image.fromarray(frame).crop((bx,by,tracker.x+48,tracker.y+30)).resize((48,29)))
                windows=sliding_window_view(gray(region).astype(np.float32),(11,30))
                sums=windows.sum(axis=(-1,-2));sq=(windows**2).sum(axis=(-1,-2))
                scores=np.einsum('ijkl,kl->ij',windows,tracker.template,optimize=False)/(np.sqrt(np.maximum(1,sq-sums**2/330))*tracker.norm)
                y,x=np.unravel_index(np.argmax(scores),scores.shape);score=float(scores[y,x])
                measured=np.array([bx+x*2+30,by+y*2+10],np.float32) if score>=.4 else tracker.last
                expected=tracker.last+np.clip(measured-tracker.last,-3,3)*.75
                center,actual_score=tracker.locate(frame)
                np.testing.assert_allclose(center,expected,atol=1e-6)
                self.assertAlmostEqual(actual_score,score,places=4)
