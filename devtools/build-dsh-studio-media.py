"""Publish the accepted real-channel studio flow separately from historical Echo media."""
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
    source_dir = parser.parse_args().accepted_directory.resolve()
    source_report = source_dir / 'studio-session-flow.json'
    report = json.loads(source_report.read_text(encoding='utf-8-sig'))
    required = {'offair_preview_and_shortcut_guard', 'anonymous_start_requires_login',
                'invalid_login_explained_and_cleared', 'inline_operator_login',
                'explicit_start_enables_send', 'controlled_late_409_has_actionable_message',
                'real_ai_natural_playback_completed', 'pause_and_shortcut_guard',
                'resume_same_broadcast_reclaims_playback', 'end_disables_send'}
    if not (report.get('passed') is True and report.get('kind') == 'native_studio_session_flow'
            and report.get('cloud_llm_exercised') is True and report.get('request_status') == 'COMPLETED'
            and all(report.get('checks', {}).get(key) is True for key in required)
            and report.get('voiced_interval', {}).get('audio_resets') == 0):
        raise RuntimeError('Require the accepted ten-check studio flow with actual AI playback')
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('Native FFmpeg and FFprobe are required')
    source = source_dir / 'studio-session-playback.webm'
    pcm = subprocess.check_output([ffmpeg, '-nostdin', '-v', 'error', '-i', str(source),
                                   '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'])
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    voiced = [i // 800 for i in range(0, len(samples), 800) if samples[i:i+800]
              and math.sqrt(sum(v*v for v in samples[i:i+800])/len(samples[i:i+800]))/32768 > .006]
    if not voiced:
        raise RuntimeError('Recording contains no audible speech')
    start = max(0, voiced[0]*.05-.3)
    media = ROOT / 'docs/media'
    public_report = ROOT / 'docs/evidence/dsh-studio-session-flow.json'
    shutil.copy2(source_report, public_report)
    manifest = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
                'kind': 'native_studio_session_flow', 'cloud_llm_exercised': True,
                'source_sha256': sha(source), 'report_sha256': sha(source_report),
                'report': public_report.relative_to(ROOT).as_posix(), 'gif_start_seconds': start,
                'recording_scope': 'First actual AI reply including waiting; pause/resume checks are in the report, not this video',
                'items': []}
    for name in ['studio-session-offair.png', 'studio-session-live.png']:
        target = media / ('dsh-' + name)
        shutil.copy2(source_dir / name, target)
        manifest['items'].append({'file': target.relative_to(ROOT).as_posix(), 'bytes': target.stat().st_size, 'sha256': sha(target)})
    for name, options in [
        ('dsh-studio-session-playback.mp4', ['-c:v', 'libx264', '-preset', 'fast', '-crf', '24', '-c:a', 'aac', '-b:a', '96k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart']),
        ('dsh-studio-session-response.gif', ['-ss', str(start), '-t', '5', '-vf', 'fps=10,scale=270:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3', '-an', '-loop', '0'])]:
        target = media / name
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source), *options, str(target)], check=True, timeout=180)
        probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_entries',
            'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', str(target)], text=True))
        manifest['items'].append({'file': target.relative_to(ROOT).as_posix(), 'bytes': target.stat().st_size, 'sha256': sha(target), 'media': probe})
    (media / 'dsh-studio-session-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'items': len(manifest['items']), 'cloud_llm_exercised': True, 'gif_start_seconds': start}))


if __name__ == '__main__':
    main()
