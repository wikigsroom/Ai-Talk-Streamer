"""Create attributed, original-speed excerpts from official Livehime recordings."""
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
    # Each window is selected from the actual recording's measured speech regions.
    parser.add_argument('--windows', type=Path, required=True,
                        help='JSON list: id, start_seconds, duration_seconds')
    args = parser.parse_args()
    encoder = shutil.which('ffmpeg')
    if not encoder:
        raise RuntimeError('Native FFmpeg is required')
    windows = json.loads(args.windows.read_text(encoding='utf-8-sig'))
    if len(windows) != 5:
        raise ValueError('Expected five spoken excerpts, separate from the five acceptance cases')
    source_hash = sha(args.input)
    folder = ROOT / 'docs/media'
    common = [encoder, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
    edits = []
    for window in windows:
        name = window['id']
        if name not in ['welcome', 'explanation', 'resume', 'queue-first', 'queue-second']:
            raise ValueError('Unknown excerpt ID')
        start, seconds = window['start_seconds'], window['duration_seconds']
        if start < 0 or not 2 < seconds <= 30:
            raise ValueError('Invalid original-speed excerpt interval')
        target = folder / ('livehime-' + name + '.mp4')
        subprocess.run(common + ['-ss', str(start), '-i', str(args.input), '-t', str(seconds),
                       '-vf', 'scale=432:768,fps=30', '-c:v', 'libx264', '-preset', 'fast', '-crf', '21',
                       '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(target)],
                       check=True, timeout=90)
        edits.append({**window, 'file': target.relative_to(ROOT).as_posix(), 'audio': True,
                      'source_sha256': source_hash, 'speed': 1})
    # The main preview is the same welcome excerpt, not a second generated performance.
    preview = folder / 'livehime-local-preview.mp4'
    shutil.copyfile(folder / 'livehime-welcome.mp4', preview)
    edits.append({**edits[0], 'file': preview.relative_to(ROOT).as_posix()})
    animation = folder / 'livehime-local-response.gif'
    gif_start = windows[0]['start_seconds'] + 1
    filters = '[0:v]fps=12.5,scale=288:512:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3'
    subprocess.run(common + ['-ss', str(gif_start), '-i', str(args.input), '-t', '6', '-an',
                   '-filter_complex', filters, str(animation)], check=True, timeout=90)
    edits.append({'file': animation.relative_to(ROOT).as_posix(), 'source_sha256': source_hash,
                  'start_seconds': gif_start, 'duration_seconds': 6, 'audio': False, 'speed': 1})
    ui = folder / 'livehime-ui-interaction.mp4'
    subprocess.run(common + ['-i', str(args.ui_recording), '-vf', 'scale=1280:-2', '-an',
                   '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
                   '-movflags', '+faststart', str(ui)], check=True, timeout=90)
    edits.append({'file': ui.relative_to(ROOT).as_posix(), 'source_sha256': sha(args.ui_recording),
                  'audio': False, 'speed': 1})
    output = folder / 'livehime-edit.json'
    output.write_text(json.dumps({'kind': 'official_livehime_local_recording_excerpts',
                                 'cloud_llm_exercised': False, 'edits': edits}, indent=2) + '\n',
                      encoding='utf-8', newline='\n')
    print(json.dumps({'ok': True, 'excerpts': len(edits), 'manifest': output.relative_to(ROOT).as_posix()}))


if __name__ == '__main__':
    main()
