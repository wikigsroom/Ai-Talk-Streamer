"""Create documentation previews from actual recordings, preserving source provenance."""
from pathlib import Path
import hashlib, json, shutil, subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/media'
parser = __import__('argparse').ArgumentParser()
parser.add_argument('--delivery-root', type=Path, help='Existing delivery containing the original scenario recordings')
args = parser.parse_args()
FFMPEG = shutil.which('ffmpeg')
FFPROBE = shutil.which('ffprobe')
if not FFMPEG or not FFPROBE: raise RuntimeError('Put native FFmpeg and FFprobe on PATH')
delivery = args.delivery_root or ROOT
manifest = {'source': 'real OBS scenarios and real browser screen recording', 'items': []}

def convert(source, target, options, description):
    subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-y', '-i', str(source), *options, str(target)], check=True, timeout=150)
    data = json.loads(subprocess.check_output([FFPROBE, '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', str(target)], text=True))
    manifest['items'].append({'file': target.relative_to(ROOT).as_posix(), 'source_name': source.name, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'description': description, 'bytes': target.stat().st_size, 'media': data})

for sid in ['s01_welcome', 's02_explain', 's03_listen_reply', 's04_interrupt_resume', 's05_closing']:
    source = delivery / 'outputs/vertical/scenarios' / (sid + '.mp4')
    convert(source, OUT / (sid + '.mp4'), ['-vf', 'scale=432:768', '-c:v', 'libx264', '-preset', 'fast', '-crf', '26', '-c:a', 'aac', '-b:a', '80k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'], 'Full actual OBS scenario; resized to 432x768 for repository playback, original 720x1280')

capture = json.loads((OUT / 'capture-manifest.json').read_text(encoding='utf-8'))
source = ROOT / capture['raw_screencast']
start = capture['screencast_demo_start_seconds']
duration = capture['screencast_demo_end_seconds'] - start
convert(source, OUT / 'browser-interaction.mp4', ['-ss', str(start), '-t', str(duration), '-vf', 'scale=1280:-2,fps=20', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'], 'Actual browser screen capture: submit echo text, wait for local speech, select and display a wave. Screen capture has no audio track; OBS scenario clips retain audio.')

jobs = [
    (OUT/'s01_welcome.mp4', 'welcome.gif', 10.5, 7, 270, 12),
    (OUT/'s02_explain.mp4', 'explanation.gif', 28, 7, 270, 12),
    (OUT/'s04_interrupt_resume.mp4', 'interrupt-resume.gif', 14, 20, 216, 8),
    (source, 'browser-response.gif', max(0, capture['screencast_gesture_seconds']-2), 7, 864, 8),
]
for source, name, start, duration, width, fps in jobs:
    graph = f'fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3'
    convert(source, OUT/name, ['-ss', str(start), '-t', str(duration), '-vf', graph, '-an', '-loop', '0'], 'Silent GIF excerpt at original playback speed; not a benchmark')
(OUT / 'media-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'ok': True, 'outputs': len(manifest['items']), 'mib': round(sum(i['bytes'] for i in manifest['items'])/1024**2, 2)}))
