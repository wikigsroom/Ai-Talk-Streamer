"""Deterministically compose the project's original instrumental room loops.

Native Python + NumPy, no model/download/borrowed recording. WAV originals are
the distributed assets; regenerate only these explicitly named files.
"""
from pathlib import Path
import hashlib
import json
import wave
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RATE = 24000
FOLDER = ROOT / 'assets/room/bgm'


def note(midi):
    return 440 * 2 ** ((midi - 69) / 12)


def compose(bpm, key, seed):
    beat = 60 / bpm
    length = 48 * beat
    audio = np.zeros(round(length * RATE), dtype=np.float64)
    rng = np.random.default_rng(seed)

    def add(start, seconds, midi, volume, instrument):
        count = min(round(seconds * RATE), len(audio) - round(start * RATE))
        if count <= 0:
            return
        t = np.arange(count) / RATE
        f = note(midi + key)
        if instrument == 'keys':
            sound = (np.sin(2*np.pi*f*t) + .18*np.sin(4*np.pi*f*t) + .04*np.sin(6*np.pi*f*t)) * np.exp(-t / .9)
            envelope = np.minimum(t / .012, 1) * np.minimum((seconds-t) / .15, 1)
        else:
            sound = (.7*np.sin(2*np.pi*f*t) + .2*np.sin(2*np.pi*f*1.002*t))
            envelope = np.minimum(t / .45, 1) * np.minimum((seconds-t) / .6, 1)
        audio[round(start*RATE):round(start*RATE)+count] += volume * sound * np.clip(envelope, 0, 1)

    chords = [[48, 55, 59, 64], [45, 52, 55, 60], [41, 48, 52, 57], [43, 50, 55, 59]]
    for bar, chord in enumerate(chords):
        for midi in chord:
            add(bar * 12 * beat, 12 * beat, midi, .027, 'pad')
        for step in range(12):
            midi = chord[[0, 2, 1, 3, 2, 1][step % 6]] + 12
            add((bar * 12 + step) * beat, 1.65 * beat, midi, .043 + .006 * (step % 3 == 0), 'keys')
        for step in [1, 4, 7, 10]:
            add((bar * 12 + step + .5) * beat, 1.2 * beat, chord[int(rng.integers(1, 4))] + 24, .013, 'keys')
    # A short symmetric fade avoids clicks at the native single-track loop seam.
    fade = round(.08 * RATE)
    audio[:fade] *= np.linspace(0, 1, fade)
    audio[-fade:] *= np.linspace(1, 0, fade)
    audio *= .34 / max(.34, np.max(np.abs(audio)))
    return audio, length


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    rows = []
    specs = [('daylight-notes', '日光便笺', 100, 0, 110), ('window-breeze', '窗边微风', 90, 2, 220), ('small-weekend', '小小周末', 96, -2, 330)]
    for i, (slug, name, bpm, key, seed) in enumerate(specs):
        audio, seconds = compose(bpm, key, seed)
        target = FOLDER / (slug + '.wav')
        with wave.open(str(target), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(RATE)
            stream.writeframes(np.round(audio * 32767).astype('<i2').tobytes())
        rows.append({'id': slug, 'name': name, 'path': target.relative_to(ROOT).as_posix(), 'duration': round(len(audio)/RATE, 6), 'bytes': target.stat().st_size, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'position': i,
                     'peak_dbfs': round(20*np.log10(max(np.max(np.abs(audio)), 1e-9)), 3), 'rms_dbfs': round(20*np.log10(max(np.sqrt(np.mean(audio**2)), 1e-9)), 3)})
    manifest = {'schema_version': 1, 'provenance': 'Original procedural instrumental compositions, created for Ai-Talk-Streamer; no external recordings or voice samples.', 'license': 'CC0-1.0', 'sample_rate': RATE, 'channels': 1, 'bits': 16, 'tracks': rows}
    (FOLDER / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'tracks': len(rows), 'bytes': sum(t['bytes'] for t in rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
