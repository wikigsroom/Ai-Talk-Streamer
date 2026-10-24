"""Convert the accepted browser's real MOSS capture into documentation media."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
evidence = json.loads((ROOT / 'docs/evidence/moss-live-browser.json').read_text(encoding='utf-8'))
if not evidence.get('ok') or len(evidence['cases']) != 5:
    raise RuntimeError('Run all five actual browser cases successfully before publishing media')
source = ROOT / 'cache/moss-live-browser/moss-04-live-demo.webm'
ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
if not ffmpeg or not ffprobe:
    raise RuntimeError('Put native FFmpeg and FFprobe on PATH')
media = ROOT / 'docs/media'
jobs = [
    ('moss-04-live-demo.mp4', ['-c:v', 'libx264', '-preset', 'fast',
                             '-crf', '24', '-c:a', 'aac', '-b:a', '96k', '-pix_fmt', 'yuv420p',
                             '-movflags', '+faststart'], 'Full actual 720x1280 browser preview with MOSS speech'),
    ('moss-04-response.gif', ['-ss', '1.5', '-t', '7', '-vf',
                            'fps=10,scale=270:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3',
                            '-an', '-loop', '0'], 'Silent excerpt of the same real preview, original playback speed'),
]
manifest = {'source': 'actual browser preview, MediaRecorder VP8/Opus',
            'browser_evidence': 'docs/evidence/moss-live-browser.json',
            'checked_at': evidence['checked_at'], 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'items': []}
for name, options, description in jobs:
    target = media / name
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source), *options, str(target)], check=True, timeout=120)
    probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_entries',
                       'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', str(target)], text=True))
    manifest['items'].append({'file': target.relative_to(ROOT).as_posix(), 'description': description,
                              'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                              'bytes': target.stat().st_size, 'media': probe})
(media / 'moss-media-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'ok': True, 'outputs': len(jobs), 'bytes': sum(item['bytes'] for item in manifest['items'])}))
