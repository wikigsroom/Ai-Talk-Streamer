"""Selected K02 compositor; no additional network, weights or CUDA allocation.

The gate consumes the two actual 20 ms PCM chunks dequeued with each video
frame. It must run on the frame consumer, never on the asynchronous producer.
Parameters and arithmetic reproduce the frozen 2026-10-28 K02 experiment.
"""
from functools import lru_cache

import cv2
import numpy as np


PROFILE = {
    'id': 'K02', 'engine': 'MuseTalk-1.5', 'precision': 'FP16',
    'batch_size': 8, 'fps': 25, 'sample_rate': 16000,
    'rms_threshold': 0.0015, 'gate_history_weight': 0.65,
    'ellipse_center': [0.50, 0.73], 'ellipse_radii': [0.43, 0.29],
    'edge_multiplier': 5.0, 'color_ring': [0.75, 1.30],
    'color_correction_limit': 18, 'additional_model_bytes': 0,
}


@lru_cache(maxsize=8)
def _geometry(height, width):
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    distance = ((xx-width*.50)/(width*.43))**2 + ((yy-height*.73)/(height*.29))**2
    alpha = np.clip((1.0-distance)*5, 0, 1)[..., None]
    ring = (distance > .75) & (distance < 1.3)
    alpha.flags.writeable = False
    ring.flags.writeable = False
    return alpha, ring


class K02Compositor:
    def __init__(self):
        self.strength = None

    def advance(self, audio_frames):
        """Advance exactly once for each dequeued video frame, including idle."""
        if len(audio_frames) != 2:
            raise ValueError('K02 requires two 20 ms chunks per video frame')
        chunks = [np.asarray(frame.data, dtype=np.float32).reshape(-1) for frame in audio_frames]
        if any(chunk.size != 320 or not np.isfinite(chunk).all() for chunk in chunks):
            raise ValueError('K02 requires finite 16 kHz mono PCM, 320 samples per chunk')
        wave = np.concatenate(chunks)
        rms = float(np.sqrt(np.mean(wave*wave)))
        target = 0.0 if rms < .0015 else 1.0
        self.strength = target if self.strength is None else .65*self.strength + .35*target
        return self.strength

    def blend(self, original, prediction, bbox):
        if self.strength is None:
            raise RuntimeError('K02 must consume the matching audio before compositing')
        return blend_mouth(original, prediction, bbox, self.strength)


def blend_mouth(source, prediction, bbox, strength):
    """Return an owned BGR frame; never mutate a cached motion-library image."""
    x1, y1, x2, y2 = map(int, bbox)
    height, width = y2-y1, x2-x1
    if not (0 <= x1 < x2 <= source.shape[1] and 0 <= y1 < y2 <= source.shape[0]):
        raise ValueError('K02 face box must be inside the source image')
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Invalid K02 gate strength')
    output = source.copy()
    if strength == 0:
        return output
    pred = cv2.resize(prediction, (width, height)).astype(np.float32)
    original = source[y1:y2, x1:x2].astype(np.float32)
    base_alpha, ring = _geometry(height, width)
    alpha = base_alpha*strength
    if ring.sum() > 10:
        correction = np.clip(np.median(original[ring]-pred[ring], axis=0), -18, 18)
        pred = np.clip(pred+correction, 0, 255)
    output[y1:y2, x1:x2] = np.clip(original*(1-alpha)+pred*alpha, 0, 255).astype(np.uint8)
    return output
