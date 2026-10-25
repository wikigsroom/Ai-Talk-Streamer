"""Create attributable documentation excerpts from an actual local RTMP recording."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--ui-recording', type=Path, required=True)
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--seconds', type=float, default=15)
    args = parser.parse_args()
    if args.start < 0 or args.seconds <= 2:
        raise ValueError('Expected a nonnegative start and a duration greater than two seconds')
    encoder = shutil.which('ffmpeg')
    if not encoder:
        raise RuntimeError('Native ffmpeg is required')
    folder = ROOT / 'docs/media'
    common = [encoder, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
    preview = folder / 'platform-local-preview.mp4'
    animation = folder / 'platform-local-response.gif'
    ui = folder / 'platform-ui-interaction.mp4'
    subprocess.run(common + ['-ss', str(args.start), '-i', str(args.input), '-t', str(args.seconds),
                   '-vf', 'scale=432:768,fps=25', '-c:v', 'libx264', '-preset', 'fast', '-crf', '21',
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(preview)],
                   check=True, timeout=90)
    filters = '[0:v]fps=12.5,scale=288:512:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3'
    subprocess.run(common + ['-ss', str(args.start + 2), '-i', str(args.input), '-t', str(min(8, args.seconds - 2)),
                   '-an', '-filter_complex', filters, str(animation)], check=True, timeout=90)
    subprocess.run(common + ['-i', str(args.ui_recording), '-vf', 'scale=1280:-2',
                   '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
                   '-movflags', '+faststart', str(ui)], check=True, timeout=90)
    result = {'kind': 'native_loopback_rtmp_documentation_excerpts', 'speed': 1,
              'preview': {'file': preview.relative_to(ROOT).as_posix(), 'start_seconds': args.start,
                          'duration_seconds': args.seconds, 'source_sha256': sha(args.input), 'audio': True},
              'gif': {'file': animation.relative_to(ROOT).as_posix(), 'start_seconds': args.start + 2,
                      'duration_seconds': min(8, args.seconds - 2), 'source_sha256': sha(args.input), 'audio': False},
              'ui': {'file': ui.relative_to(ROOT).as_posix(), 'source_sha256': sha(args.ui_recording), 'audio': False}}
    (folder / 'platform-edit.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
