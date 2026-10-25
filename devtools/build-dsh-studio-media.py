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
    parser.add_argument('--open-access', action='store_true', help='Publish the current open-access flow instead of historical manual login')
    options = parser.parse_args()
    source_dir = options.accepted_directory.resolve()
    prefix = 'direct-studio' if options.open_access else 'studio-session'
    kind = 'native_open_access_studio' if options.open_access else 'native_studio_session_flow'
    source_report = source_dir / (prefix + '-flow.json')
    report = json.loads(source_report.read_text(encoding='utf-8-sig'))
    required = {'offair_preview_and_shortcut_guard', 'anonymous_start_requires_login',
                'invalid_login_explained_and_cleared', 'inline_operator_login',
                'explicit_start_enables_send', 'controlled_late_409_has_actionable_message',
                'real_ai_natural_playback_completed', 'pause_and_shortcut_guard',
                'resume_same_broadcast_reclaims_playback', 'end_disables_send'}
    accepted = (report.get('passed') is True and report.get('kind') == kind
            and report.get('cloud_llm_exercised') is True and report.get('request_status') == 'COMPLETED'
            and all(report.get('checks', {}).get(key) is True for key in required)
            and report.get('voiced_interval', {}).get('audio_resets') == 0)
    if options.open_access:
        required = {'fresh_browser_no_authentication', 'settings_write_without_credentials', 'memory_management_without_login', 'preview_automatically_starts_session',
                    'actual_ai_reply_and_natural_audio', 'explicit_pause_blocks_send',
                    'explicit_resume_keeps_context', 'send_after_end_automatically_starts_new_session',
                    'reload_requires_no_authentication', 'reload_reconnect_and_audio_work',
                    'no_manual_token_or_login', 'no_browser_exceptions', 'cleanup_offair'}
        accepted = (report.get('passed') is True and report.get('kind') == kind
                    and report.get('cloud_llm_exercised') is True
                    and all(report.get('checks', {}).get(key) is True for key in required)
                    and len(report.get('turns', [])) == 3 and report.get('manual_login_requests') == 0
                    and report['turns'][0]['mode'] == 'chat'
                    and all(t['status'] == 'COMPLETED' and t['voiced_interval']['audio_resets'] == 0
                            and all(p['natural_end'] and not p['lost'] and not p['cancelled']
                                    and p['played_samples'] == p['valid_sample_count'] > 0 for p in t['playback'])
                            for t in report['turns']))
    if not accepted:
        raise RuntimeError('Require an accepted studio flow with actual AI playback and its complete checks')
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('Native FFmpeg and FFprobe are required')
    source = source_dir / (prefix + '-playback.webm')
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
    public_report = ROOT / ('docs/evidence/dsh-' + prefix + '-flow.json')
    shutil.copy2(source_report, public_report)
    manifest = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
                'kind': kind, 'cloud_llm_exercised': True,
                'source_sha256': sha(source), 'report_sha256': sha(source_report),
                'report': public_report.relative_to(ROOT).as_posix(), 'gif_start_seconds': start,
                'recording_scope': 'First actual AI reply including waiting; pause/resume and subsequent Echo checks are in the report, not this video',
                'items': []}
    for name in [prefix + ('-connected.png' if options.open_access else '-offair.png'), prefix + '-live.png', *([prefix + '-memory.png'] if options.open_access else [])]:
        target = media / ('dsh-' + name)
        shutil.copy2(source_dir / name, target)
        manifest['items'].append({'file': target.relative_to(ROOT).as_posix(), 'bytes': target.stat().st_size, 'sha256': sha(target)})
    for name, options in [
        ('dsh-' + prefix + '-playback.mp4', ['-c:v', 'libx264', '-preset', 'fast', '-crf', '24', '-c:a', 'aac', '-b:a', '96k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart']),
        ('dsh-' + prefix + '-response.gif', ['-ss', str(start), '-t', '5', '-vf', 'fps=10,scale=270:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3', '-an', '-loop', '0'])]:
        target = media / name
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source), *options, str(target)], check=True, timeout=180)
        probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_entries',
            'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', str(target)], text=True))
        manifest['items'].append({'file': target.relative_to(ROOT).as_posix(), 'bytes': target.stat().st_size, 'sha256': sha(target), 'media': probe})
    (media / ('dsh-' + prefix + '-manifest.json')).write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'items': len(manifest['items']), 'cloud_llm_exercised': True, 'gif_start_seconds': start}))


if __name__ == '__main__':
    main()
