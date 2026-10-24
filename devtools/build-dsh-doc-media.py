"""Publish media from an accepted native-browser Echo run, without claiming an LLM test."""
from array import array
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('accepted_directory', type=Path)
    args = parser.parse_args()
    source_dir = args.accepted_directory.resolve()
    report_file = source_dir / 'media-smoke.json'
    report = json.loads(report_file.read_text(encoding='utf-8'))
    if (report.get('passed') is not True or report.get('kind') != 'real_media_echo_smoke'
            or report.get('cloud_llm_exercised') is not False
            or report.get('audio_resets') != 0
            or report.get('metrics', {}).get('missing_packets') != 0
            or len(report.get('requests', [])) != 2
            or any(row['status'] != 'COMPLETED' for row in report['requests'])):
        raise RuntimeError('Require the accepted complete/cancel/recovery Echo report')
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('Put native FFmpeg and FFprobe on PATH')
    source = source_dir / 'echo-playback.webm'
    pcm = subprocess.check_output([ffmpeg, '-nostdin', '-v', 'error', '-i', str(source),
                                   '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'])
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    windows = [math.sqrt(sum(v*v for v in samples[i:i+800])/len(samples[i:i+800]))/32768
               for i in range(0, len(samples), 800) if samples[i:i+800]]
    voiced = [i for i, rms in enumerate(windows) if rms > .006]
    if not voiced:
        raise RuntimeError('Recording has no audible speech')
    speech_start = max(0, voiced[0]*.05-.3)
    media = ROOT / 'docs/media'
    media.mkdir(parents=True, exist_ok=True)
    manifest = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
                'kind': 'real_media_echo_smoke', 'cloud_llm_exercised': False,
                'source': 'Actual native Chrome canvas/PCM MediaRecorder capture; MOSS 04 and MuseTalk',
                'source_sha256': sha(source), 'report_sha256': sha(report_file),
                'acceptance': 'docs/evidence/dsh-humanity-runtime.json',
                'gif_start_seconds': round(speech_start, 3), 'items': []}
    for src, name in [('studio-dsh.png', 'dsh-studio.png'), ('memory-dsh.png', 'dsh-memory.png')]:
        target = media / name
        shutil.copy2(source_dir / src, target)
        manifest['items'].append({'file': target.relative_to(ROOT).as_posix(),
                                  'sha256': sha(target), 'bytes': target.stat().st_size,
                                  'description': 'Actual browser page, without credential fields expanded'})
    jobs = [
        ('dsh-echo-playback.mp4', ['-c:v', 'libx264', '-preset', 'fast', '-crf', '24',
          '-c:a', 'aac', '-b:a', '96k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'],
         'Complete real recording, including synthesis wait; Echo, no cloud LLM'),
        ('dsh-echo-response.gif', ['-ss', str(speech_start), '-t', '7', '-vf',
          'fps=10,scale=270:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3',
          '-an', '-loop', '0'], 'Seven-second silent excerpt from actual speech at original playback speed'),
    ]
    for name, options, description in jobs:
        target = media / name
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source),
                        *options, str(target)], check=True, timeout=180)
        probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_entries',
            'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', str(target)], text=True))
        manifest['items'].append({'file': target.relative_to(ROOT).as_posix(),
            'sha256': sha(target), 'bytes': target.stat().st_size, 'description': description, 'media': probe})
    (media / 'dsh-media-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'ok': True, 'items': len(manifest['items']), 'gif_start_seconds': speech_start,
                      'cloud_llm_exercised': False}))


if __name__ == '__main__':
    main()
