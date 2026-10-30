"""Package real paired output and make full-frame/mouth contact sheets for inspection."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
from PIL import Image, ImageDraw
import numpy as np

root = Path(__file__).resolve().parents[2]
folder = root / 'output/review/naimei-live-v1/flashhead'
ffmpeg = Path(r'E:\dev\sandbox\虚拟数字人直播\operations\naimei-asset-build-20261031\media-runtime\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe')
result = json.loads((folder / 'speech-check.json').read_text('utf-8'))
assert result.get('completed'), 'SOURCE_RECORDING_INCOMPLETE'
roi = (185, 352, 329, 445)
for item in result['cases']:
    aid = item['id']
    source = folder / (aid + '.mjpeg')
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-r', '25', '-f', 'mjpeg', '-i', str(source),
                    '-f', 's16le', '-ar', '16000', '-ac', '1', '-i', str(folder / (aid + '.s16le')),
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart',
                    str(folder / (aid + '.mp4'))], check=True)
    fragments = source.read_bytes().split(b'\xff\xd9')
    frames = [data + b'\xff\xd9' for data in fragments if data]
    assert len(frames) == item['frames']
    metadata = json.loads((folder / (aid + '-frames.json')).read_text('utf-8'))
    indices = [i for i, record in enumerate(metadata) if record['epoch'] == item['accepted']['epoch'] and record['flags'] & 1]
    sheet = Image.new('RGB', (12 * 144, ((len(indices) + 11) // 12) * 110), '#fff7ec')
    draw = ImageDraw.Draw(sheet)
    full = Image.new('RGB', (4 * 256, 3 * 276), '#fff7ec')
    full_draw = ImageDraw.Draw(full)
    selected = set(np.linspace(0, len(indices) - 1, 12).round().astype(int))
    hashes, changes, previous, full_index = [], [], None, 0
    for j, i in enumerate(indices):
        with Image.open(io.BytesIO(frames[i])) as image:
            image = image.convert('RGB')
            mouth = image.crop(roi)
            x, y = (j % 12) * 144, (j // 12) * 110
            sheet.paste(mouth, (x, y + 16))
            draw.text((x + 2, y + 2), f'{metadata[i]["offset"] / 16000:.2f}s', fill='#35251b')
            pixels = np.asarray(mouth, dtype=np.float32)
            if previous is not None:
                changes.append(float(np.abs(pixels - previous).mean()))
            previous = pixels
            hashes.append(hashlib.sha256(mouth.tobytes()).hexdigest())
            if j in selected:
                x, y = full_index % 4 * 256, full_index // 4 * 276
                full.paste(image.resize((256, 256)), (x, y + 20))
                full_draw.text((x + 4, y + 4), f'{metadata[i]["offset"] / 16000:.2f}s', fill='#35251b')
                full_index += 1
    sheet.save(folder / (aid + '-mouth-all-frames.jpg'), quality=92)
    full.save(folder / (aid + '-contact.jpg'), quality=92)
    item['visual_evidence'] = {'unique_mouth_crops': len(set(hashes)), 'consecutive_mouth_delta_mean': float(np.mean(changes)),
                               'consecutive_mouth_delta_p95': float(np.percentile(changes, 95)),
                               'note': 'Pixel variation is diagnostic; mouth/fang acceptance needs visual inspection.'}
    print(aid, item['speech_frames'], round(item['output_fps'], 3))
result['mouth_roi'] = list(roi)
(folder / 'speech-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
