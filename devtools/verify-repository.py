"""Verify publishable source, documentation, reviewed assets and optional video metadata."""
from pathlib import Path
import argparse
import ast
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]

def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

def report_digest_matches(path, expected):
    """Keep historical Windows report hashes valid after Git newline conversion."""
    data = path.read_bytes().replace(b'\r\n', b'\n')
    return expected in {
        hashlib.sha256(data).hexdigest(),
        hashlib.sha256(data.replace(b'\n', b'\r\n')).hexdigest(),
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media', action='store_true', help='Require native ffprobe and inspect all supplied MP4 files')
    args = parser.parse_args()
    failures = []
    counts = {}

    def check(ok, message):
        if not ok:
            failures.append(message)

    def local(relative):
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Manifest path leaves the repository')
        return path

    def load(relative):
        return json.loads(local(relative).read_text(encoding='utf-8-sig'))

    raw = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    files = sorted({local(p) for p in raw.decode('utf-8').split('\0') if p})
    check(bool(files), 'No repository files found')
    text_types = {'.py', '.js', '.cjs', '.mjs', '.sql', '.html', '.css', '.json', '.md', '.txt', '.csv', '.yaml', '.yml', '.ps1', '.cmd', '.example'}
    private = re.compile(r'192\.168\.\d+\.\d+|[A-Za-z]:[\\/]+Users[\\/]+(?:carzy|wuxie)\b|\.codex[\\/]', re.I)
    tokens = re.compile(r'\b(?:sk-[A-Za-z0-9_-]{24,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b')
    forbidden_roots = {'.setup', 'src', 'runtime', 'tools', 'cache', 'logs', 'downloads', 'models', 'node_modules', '.publish'}
    forbidden_names = {'channel.env', 'device.json', 'remote_control.py', 'remote_run.py', 'services.json'}
    # Earlier, already-published experiments contain LAN host markers. Preserve
    # those frozen files byte-for-byte; an exception applies only to its exact
    # normalized digest, never to credentials or newly edited archive content.
    legacy_hosts = load('configs/repository/historical-host-identifiers.json')['files']
    texts = {}
    for path in files:
        rel = path.relative_to(ROOT)
        check(rel.parts[0] not in forbidden_roots, 'Excluded runtime directory staged: ' + rel.as_posix())
        check(path.name not in forbidden_names, 'Private configuration staged: ' + rel.as_posix())
        check(path.is_file(), 'Missing indexed file: ' + rel.as_posix())
        if not path.is_file():
            continue
        check(path.stat().st_size < 95 * 1024**2, 'File exceeds publication size limit: ' + rel.as_posix())
        check(path.suffix.lower() not in {'.zip', '.7z', '.key', '.pem', '.pfx', '.mkv', '.pth', '.pt', '.ckpt', '.safetensors'},
              'Archive, key, raw recording or weight staged: ' + rel.as_posix())
        if path.suffix.lower() in text_types or path.name in {'LICENSE', 'NOTICE', '.gitignore', '.gitattributes'}:
            try:
                text = path.read_text(encoding='utf-8-sig')
                texts[path] = text
                legacy = legacy_hosts.get(rel.as_posix(), {})
                exact_legacy = (legacy.get('sha256_lf') == hashlib.sha256(text.replace('\r\n', '\n').encode()).hexdigest())
                check(not private.search(text) or exact_legacy, 'Private device identifier in: ' + rel.as_posix())
                check(not tokens.search(text), 'Possible credential in: ' + rel.as_posix())
            except UnicodeError:
                failures.append('Invalid UTF-8 source: ' + rel.as_posix())

    counts['files'] = len(files)
    counts['bytes'] = sum(p.stat().st_size for p in files if p.is_file())
    counts['python'] = 0
    counts['json'] = 0
    counts['markdown_links'] = 0
    for path, text in texts.items():
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix == '.py':
            try:
                ast.parse(text, filename=rel)
                counts['python'] += 1
            except SyntaxError:
                failures.append('Python syntax: ' + rel)
        if path.suffix == '.json':
            try:
                json.loads(text)
                counts['json'] += 1
            except ValueError:
                failures.append('JSON syntax: ' + rel)
        if path.suffix == '.md':
            # Strip fenced code before checking links; URLs inside examples are not file references.
            prose = re.sub(r'```.*?```', '', text, flags=re.S)
            links = re.findall(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)', prose)
            links += re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', prose)
            for target in links:
                target = target.strip('<>')
                if urlsplit(target).scheme or target.startswith('//'):
                    continue
                part, _, fragment = unquote(target).partition('#')
                dest = (path.parent / part).resolve() if part else path
                check(dest.is_relative_to(ROOT) and dest.exists(), 'Broken local documentation link: ' + rel + ' -> ' + target)
                if fragment and dest.is_file() and dest.suffix == '.md':
                    headings = re.findall(r'^#{1,6}\s+(.+)$', dest.read_text(encoding='utf-8-sig'), re.M)
                    anchors = [re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-') for h in headings]
                    check(fragment in anchors, 'Missing Markdown anchor: ' + rel + ' -> ' + target)
                counts['markdown_links'] += 1

    locks = load('configs/sources.lock.json')
    for name, item in locks.items():
        check(bool(re.fullmatch(r'[0-9a-f]{40}', item['sha'])), 'Invalid source lock: ' + name)
    with local('configs/model-files.csv').open(encoding='utf-8-sig', newline='') as stream:
        models = list(csv.DictReader(stream))
    counts['reference_model_records'] = len(models)
    for item in models:
        check(bool(re.fullmatch(r'[0-9a-f]{64}', item['sha256_local'])), 'Invalid model reference digest')
        local(item['local_path'].replace('\\', '/'))

    catalog = load('configs/vertical/materials/catalog.json')
    reviews = load('configs/vertical/materials/reviews.json')
    delivery = load('outputs/vertical/materials/delivery-manifest.json')
    index = load('configs/vertical/materials/motion-index.json')
    clips = catalog['items']
    by_id = {i['id']: i for i in delivery['items']}
    check(len(clips) == len(by_id) == 48, 'Expected 48 selected gesture clips')
    categories = {}
    hashes = []
    for item in clips:
        name = item['id']
        categories[item['category']] = categories.get(item['category'], 0) + 1
        video = local(item['source_video'])
        digest = sha256(video)
        hashes.append(digest)
        record = by_id[name]
        check(digest == record['sha256'] and video.stat().st_size == record['bytes'], 'Selected video checksum: ' + name)
        check(item['frames'] == 200 and item['duration_seconds'] == 8, 'Selected clip timing: ' + name)
        check(reviews.get(name, {}).get('accepted'), 'Selected clip lacks acceptance: ' + name)
        for relative in [item['workflow'], item['prompt'], 'configs/vertical/materials/' + name + '.history.json',
                         'outputs/vertical/materials/posters/' + name + '.jpg',
                         'outputs/vertical/materials/keyframes/' + name + '.png', reviews[name]['evidence']]:
            check(local(relative).is_file(), 'Missing selected material: ' + relative)
    check(len(set(hashes)) == 48, 'Duplicate selected video hashes')
    check(len(categories) == 6 and all(n == 8 for n in categories.values()), 'Expected six categories of eight clips')
    offset = 0
    for clip in index['clips']:
        check(clip['start_frame'] == offset and clip['frames'] == 200, 'Non-contiguous or unexpected motion region: ' + clip['id'])
        offset += clip['frames']
    check(offset == index['frames'] == 10000 and len(index['clips']) == 50 and index['fps'] == 25, 'Final bank dimensions')
    check({c['id'] for c in index['clips'][2:]} == set(by_id), 'Bank and catalog disagree')
    counts['selected_clips'] = len(clips)
    counts['bank_frames'] = offset
    baseline = load('configs/vertical/baseline-media.json')
    for item in baseline['items']:
        check(sha256(local(item['file'])) == item['sha256'], 'Baseline video checksum: ' + item['file'])

    poses = load('output/imagegen/motion-poses/delivery.json')
    pose_reviews = load('output/imagegen/motion-poses/reviews.json')
    check(poses['ok'] and poses['count'] == len(poses['items']) == 28, 'Expected 28 accepted independent pose photos')
    for item in poses['items']:
        check(pose_reviews.get(item['id'], {}).get('accepted'), 'Pose lacks acceptance: ' + item['id'])
        check(sha256(local(item['native'])) == item['sha256'], 'Native pose checksum: ' + item['id'])
        check(sha256(local(item['delivery'])) == item['delivery_sha256'], 'Delivery pose checksum: ' + item['id'])
        check(local(item['prompt']).is_file(), 'Missing pose prompt: ' + item['id'])
    counts['independent_poses'] = len(poses['items'])

    media = load('docs/media/media-manifest.json')
    check(len(media['items']) == 10, 'Expected six MP4s and four GIFs')
    for item in media['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'], 'Documentation media checksum: ' + item['file'])
    for manifest_name in ('capture-manifest.json', 'gallery-capture-manifest.json'):
        capture = load('docs/media/' + manifest_name)
        check(capture['ok'], 'Documentation capture failed: ' + manifest_name)
        for name in capture['screenshots']:
            path = local('docs/media/' + name)
            check(path.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n', 'Invalid screenshot: ' + name)

    acceptance = load('docs/evidence/browser-acceptance.json')
    check(acceptance['ok'] and len(acceptance['checks']) == 17 and all(c['ok'] for c in acceptance['checks']), 'Reference browser acceptance')
    scenarios = load('docs/evidence/scenarios.json')
    check(scenarios['ok'] and len(scenarios['items']) == 5 and all(c['ok'] for c in scenarios['items']), 'Reference scenario acceptance')
    check(abs(sum(c['seconds'] for c in scenarios['items']) - 217.24) < .01, 'Scenario duration total')

    deployment3080 = load('docs/evidence/rtx3080-deployment.json')
    check(deployment3080['ok'] and deployment3080['browser_ok'] and deployment3080['cloud_ok'], 'RTX 3080 deployment acceptance')
    check(deployment3080['profile']['preset'] == 'rtx3080-original' and deployment3080['profile']['batch_size'] == 8,
          'RTX 3080 original batch profile')
    browser3080 = load('docs/evidence/rtx3080-browser.json')
    check(browser3080['ok'] and all(c['ok'] for c in browser3080['checks']), 'RTX 3080 browser checks')
    speech3080 = next(c for c in browser3080['checks'] if c['name'] == 'speaking_rate')
    check(speech3080['fps'] >= 22.5 and abs(speech3080['fps'] - (speech3080['after']['frames'] - speech3080['before']['frames']) / speech3080['seconds']) < .001,
          'RTX 3080 actual received speech frame rate')
    scenarios3080 = load('docs/evidence/rtx3080-scenarios.json')
    check(scenarios3080['ok'] and len(scenarios3080['items']) == 5 and all(c['ok'] for c in scenarios3080['items']), 'RTX 3080 five scenarios')
    check(abs(sum(c['seconds'] for c in scenarios3080['items']) - 294.20) < .01, 'RTX 3080 scenario duration total')
    media3080 = load('docs/media/rtx3080-manifest.json')
    check(len(media3080['items']) == 8, 'Expected eight attributable RTX 3080 media files')
    for item in media3080['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'], 'RTX 3080 media checksum: ' + item['file'])
        if path.suffix in {'.mp4', '.gif'}:
            check(item['source_sha256'] == scenarios3080['items'][0]['sha256'], 'RTX 3080 preview source checksum')
    counts['rtx3080_scenarios'] = len(scenarios3080['items'])

    dsh_media = load('docs/media/dsh-media-manifest.json')
    check(dsh_media['kind'] == 'real_media_echo_smoke' and dsh_media['cloud_llm_exercised'] is False,
          'DSH documentation media must identify the actual Echo scope')
    for item in dsh_media['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'],
              'DSH media checksum: ' + item['file'])
    counts['dsh_documentation_media'] = len(dsh_media['items'])
    management_media = load('docs/media/dsh-management-manifest.json')
    check(management_media['kind'] == 'isolated_native_dsh_humanity_http_chrome_management'
          and management_media['fixture_facts'] is True
          and management_media['production_memory_mutated'] is False
          and management_media['cloud_llm_exercised'] is False, 'DSH management screenshot must identify isolated fixture scope')
    for item in management_media['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'],
              'DSH management media checksum: ' + item['file'])
    counts['dsh_management_media'] = len(management_media['items'])
    studio_flow = load('docs/evidence/dsh-studio-session-flow.json')
    check(studio_flow['passed'] is True and studio_flow['cloud_llm_exercised'] is True
          and len(studio_flow['checks']) == 10 and all(studio_flow['checks'].values())
          and studio_flow['request_status'] == 'COMPLETED'
          and studio_flow['voiced_interval']['audio_resets'] == 0,
          'DSH session-flow evidence must cover the real AI reply and ten UI checks')
    studio_media = load('docs/media/dsh-studio-session-manifest.json')
    check(studio_media['kind'] == 'native_studio_session_flow' and studio_media['cloud_llm_exercised'] is True
          and report_digest_matches(local(studio_media['report']), studio_media['report_sha256']),
          'DSH session media must identify its actual real-channel source')
    for item in studio_media['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'],
              'DSH session media checksum: ' + item['file'])
    counts['dsh_session_media'] = len(studio_media['items'])
    direct = load('docs/evidence/dsh-direct-studio-flow.json')
    check(direct['kind'] == 'native_open_access_studio' and direct['passed'] is True
          and direct['cloud_llm_exercised'] is True and direct['manual_login_requests'] == 0
          and len(direct['checks']) == 13 and all(direct['checks'].values())
          and len(direct['turns']) == 3
          and all(turn['status'] == 'COMPLETED' and turn['voiced_interval']['audio_resets'] == 0
                  and all(p['natural_end'] and not p['lost'] and not p['cancelled']
                          and p['played_samples'] == p['valid_sample_count'] > 0 for p in turn['playback'])
                  for turn in direct['turns']),
          'Current open-access evidence must cover thirteen checks and three actual completed utterances')
    direct_media = load('docs/media/dsh-direct-studio-manifest.json')
    check(direct_media['kind'] == 'native_open_access_studio'
          and direct_media['cloud_llm_exercised'] is True
          and report_digest_matches(local(direct_media['report']), direct_media['report_sha256']),
          'Open-access media must identify its actual real-channel source')
    for item in direct_media['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'],
              'Open-access media checksum: ' + item['file'])
    counts['dsh_open_access_media'] = len(direct_media['items'])
    dsh_docs = load('docs/evidence/dsh-humanity-doc-validation.json')
    for item in dsh_docs['artifacts']:
        digest = hashlib.sha256(local(item['path']).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(digest == item['sha256'], 'DSH documented source changed after validation: ' + item['path'])
    dsh_runtime = load('docs/evidence/dsh-humanity-runtime.json')
    platform_evidence = load('docs/evidence/platform-integration.json')
    livehime = load('docs/evidence/bilibili-livehime.json')
    check(livehime['local_acceptance']['ok'] is True
          and len(livehime['local_acceptance']['steps']) == 5
          and all(step['status'] in {'COMPLETED', 'PASSED'} for step in livehime['local_acceptance']['steps'])
          and len(livehime['local_acceptance']['utterances']) == 5
          and all(utterance['status'] == 'COMPLETED'
                  and utterance['valid_sample_count'] == utterance['contiguous_played_samples'] > 0
                  and any(observation['natural_end'] == 1 and observation['played_samples'] == utterance['valid_sample_count']
                          for observation in utterance['observations'])
                  for utterance in livehime['local_acceptance']['utterances'])
          and livehime['obs_used'] is False
          and livehime['platform_audience_verified'] is False
          and livehime['module_tests']['node_passed'] >= 76
          and livehime['module_tests']['node_skipped'] == 0
          and livehime['module_tests']['python_passed'] >= 23
          and livehime['module_tests']['native_route_count'] == 21,
          'Livehime evidence requires five native cases and complete regressions')
    native_video = next(stream for stream in livehime['local_acceptance']['recording']['probe']['streams']
                        if stream['codec_type'] == 'video')
    check((native_video['codec_name'], native_video['width'], native_video['height'], native_video['r_frame_rate'])
          == ('h264', 720, 1280, '30/1')
          and livehime['local_acceptance']['audio_measurement']['above_threshold_rms'] > .001
          and livehime['local_acceptance']['obs_processes'] == [], 'Livehime actual encoding and audio evidence')

    split = load('docs/evidence/split-device.json')
    split_run = split['local_acceptance']
    check(split_run['ok'] is True and len(split_run['steps']) == 5
          and all(step['status'] == 'COMPLETED' for step in split_run['steps'])
          and split_run['duplicate_rejected'] is True
          and split_run['reconnect']['new_consumer'] is True
          and split_run['cloud_llm_exercised'] is True
          and split_run['public_broadcast_started'] is False,
          'Split-device evidence requires five actual cross-device speech cases and recovery')
    split_metrics = split_run['final_metrics']
    check(split_metrics['codec'] == 'h264_nvenc'
          and (split_metrics['width'], split_metrics['height']) == (720, 1280)
          and split_metrics['fps'] >= 22
          and all(split_metrics[name] == 0 for name in ('audio_underruns', 'missing_packets', 'decode_errors')),
          'Split-device media continuity and actual presentation')
    check(len(split_run['utterances']) == 5
          and all(u['status'] == 'COMPLETED'
                  and u['valid_sample_count'] == u['contiguous_played_samples'] > 0
                  and any(o['natural_end'] == 1 and o['played_samples'] == u['valid_sample_count']
                          for o in u['observations']) for u in split_run['utterances'])
          and split['module_tests']['node_passed'] >= 81
          and split['module_tests']['node_skipped'] == 0
          and split['module_tests']['python_passed'] >= 34
          and split['module_tests']['native_route_count'] == 21,
          'Split-device complete sample receipts and regressions')

    voice_release = load('docs/evidence/voice-o07-f07.json')
    voice_runtime = voice_release['runtime_acceptance']
    check(voice_runtime['passed'] is True
          and voice_runtime['python_passed'] >= 46
          and voice_release['module_tests']['node_passed'] >= 82
          and voice_release['module_tests']['node_skipped'] == 0
          and voice_runtime['active_cancel_no_fallback'] is True
          and voice_runtime['real_primary_process_failure_fallback'] is True
          and voice_runtime['manual_switch_and_restore'] is True,
          'O07/F07 evidence requires real synthesis, cancellation, process-failure fallback and regressions')
    new_native = voice_release['local_acceptance']
    check(new_native['ok'] is True and len(new_native['steps']) == 5
          and new_native['duplicate_rejected'] is True
          and new_native['cloud_llm_exercised'] is True
          and new_native['public_broadcast_started'] is False
          and all(step['status'] == 'COMPLETED'
                  and len(step['utterances']) == 1
                  and all(u['status'] == 'COMPLETED'
                          and u['contiguous_played_samples'] == u['valid_sample_count'] > 0
                          and u['last_receipt']['natural_end'] == 1
                          for u in step['utterances']) for step in new_native['steps'])
          and new_native['metrics_summary']['receiver_canvas_fps_mean'] >= 23
          and all(v == 0 for v in new_native['metrics_summary']['continuity_deltas'].values())
          and voice_release['first_attempt']['passed'] is False
          and voice_release['final_runtime']['selected_voice'] == 'O07'
          and voice_release['final_runtime']['offair'] is True,
          'O07/F07 native receiver requires five full receipts, continuous playback and retained failed attempt')
    room_release = load('docs/evidence/room-admin.json')
    room_run = room_release['local_acceptance']
    check(room_run['ok'] is True and len(room_run['cases']) == 5
          and room_release['public_broadcast_started'] is False
          and all(c['status'] == 'COMPLETED' and len(c['utterances']) == 1
                  and all(u['valid_sample_count'] == u['contiguous_played_samples'] > 0
                          and u['last_receipt']['natural_end'] == 1
                          and u['last_receipt']['accepted'] == 1 for u in c['utterances'])
                  for c in room_run['cases'])
          and room_run['fps']['samples'] >= 100 and room_run['fps']['mean'] >= 24
          and all(v == 0 for v in room_run['continuity_deltas'].values())
          and room_run['checks']['ducking_observed'] is True
          and room_run['checks']['range_forwarding'] is True
          and room_run['checks']['large_upload']['bytes'] > 2 * 1024**2
          and room_run['checks']['private_agent']['auto_spoken'] is False
          and room_release['module_tests']['node_passed'] >= 96
          and room_release['module_tests']['node_skipped'] == 0
          and room_release['module_tests']['python_passed'] >= 46
          and room_release['module_tests']['native_route_count'] >= 27
          and room_release['first_attempt']['ok'] is False
          and room_release['final_update']['panic_and_restore'] is True
          and room_release['final_update']['offair'] is True,
          'Room release requires real full-sample playback, mixer, upload and regression evidence')
    native_3080 = load('docs/evidence/native-rtx3080-k02-20261029.json')
    native_report = load(native_3080['report'])
    native_final = native_report['final']
    check(native_3080['passed'] is True and native_report['passed'] is True
          and report_digest_matches(local(native_3080['report']), native_3080['report_sha256'])
          and native_report['parameters']['batch_size'] == 4
          and len(native_final['cases']) == 5
          and all(c['status'] == 'COMPLETED' for c in native_final['cases'])
          and native_final['fps']['mean'] >= 23
          and all(native_final['continuity'][k] == 0 for k in ('audio_underruns', 'missing_packets', 'decode_errors'))
          and all(c['status'] == 'COMPLETED' for c in native_report['private_agent_turns'])
          and len(native_report['private_agent_turns']) == 2
          and native_final['checks']['private_agent_not_auto_spoken']['job_status'] == 'COMPLETED'
          and native_final['checks']['no_comfy_job_overlap'] is True
          and native_3080['module_tests']['python_passed'] == 35
          and native_3080['module_tests']['node_passed'] == 11
          and native_report['scope']['public_broadcast'] is False,
          'Native3080 acceptance requires actual five-case playback, continuity, private turns and scoped regressions')
    for item in native_report['artifacts']:
        artifact = local(str(Path(native_3080['report']).parent / item['path']))
        check((sha256(artifact) == item['sha256'] if artifact.suffix == '.png'
               else report_digest_matches(artifact, item['sha256'])), 'Native3080 artifact checksum: ' + item['path'])
    for name, expected in native_3080['code_sha256'].items():
        actual = hashlib.sha256(local(name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(actual == expected, 'Native3080 source changed after acceptance: ' + name)

    def native_source_matches(name, current, historical):
        delta = native_3080['superseded_sources'].get(name, {})
        return (historical in delta.get('historical_sha256', [])
                and current == delta.get('current_sha256')
                and current == native_3080['code_sha256'].get(name)
                and bool(delta.get('validation')))

    for name, expected in room_release['code_sha256'].items():
        digest = hashlib.sha256(local(name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(digest == expected or native_source_matches(name, digest, expected), 'Room source changed after validation: ' + name)
    for item in room_release['media']:
        path = local(item['path'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'],
              'Room media checksum: ' + item['path'])
    for item in room_release['module_tests']['logs']:
        check(report_digest_matches(local(item['path']), item['sha256']), 'Room regression log checksum: ' + item['path'])

    def room_source_matches(name, current, historical):
        delta = room_release['superseded_sources'].get(name, {})
        return (historical in delta.get('historical_sha256', [])
                and current == delta.get('current_sha256')
                and current == room_release['code_sha256'].get(name)
                and bool(delta.get('validation')))

    for name, expected in voice_release['code_sha256'].items():
        digest = hashlib.sha256(local(name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(digest == expected or room_source_matches(name, digest, expected)
              or native_source_matches(name, digest, expected), 'O07/F07 source lacks successor validation: ' + name)
    pair = load('configs/voices/female-a-o07-f07.json')
    check(pair['default_voice_id'] == 'O07' and pair['fallback_voice_id'] == 'F07'
          and sha256(local(pair['reference_audio'])) == pair['reference_sha256'], 'O07/F07 fixed synthetic reference')
    for voice in pair['voices']:
        check(sha256(local(voice['audition'])) == voice['audition_sha256'], 'Selected audition checksum: ' + voice['id'])

    def source_matches(name, current, historical):
        if current == historical:
            return True
        if native_source_matches(name, current, historical):
            return True
        if room_source_matches(name, current, historical):
            return True
        # New acceptance supersedes source hashes only. Historical measurements,
        # recordings and their checksums continue to be verified unchanged.
        voice_delta = voice_release['superseded_sources'].get(name, {})
        if (historical in voice_delta.get('historical_sha256', [])
                and current == voice_delta.get('current_sha256')
                and current == voice_release['code_sha256'].get(name)
                and bool(voice_delta.get('validation'))):
            return True
        successor = split['superseded_sources'].get(name, {})
        if (historical in successor.get('historical_sha256', [])
                and current == successor.get('current_sha256')
                and current == split['code_sha256'].get(name)
                and bool(successor.get('validation'))):
            return True
        delta = livehime['superseded_sources'].get(name, {})
        return (historical in delta.get('historical_sha256', [])
                and current == delta.get('current_sha256')
                and bool(delta.get('validation')))

    check(platform_evidence['local_acceptance']['ok'] is True
          and platform_evidence['module_tests']['node_passed'] >= 68
          and platform_evidence['module_tests']['node_skipped'] == 0
          and platform_evidence['module_tests']['python_passed'] >= 23
          and platform_evidence['module_tests']['native_route_count'] == 18,
          'Platform evidence requires actual local media and complete module/proxy tests')
    deltas = platform_evidence['superseded_baseline_sources']
    for name, expected in dsh_runtime['code_sha256'].items():
        digest = hashlib.sha256(local(name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        if not source_matches(name, digest, expected):
            delta = deltas.get(name, {})
            check(delta.get('historical_sha256') == expected and source_matches(name, digest, delta.get('current_sha256'))
                  and bool(delta.get('validation')), 'DSH source lacks current validation evidence: ' + name)
    for name, expected in platform_evidence['code_sha256'].items():
        digest = hashlib.sha256(local(name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(source_matches(name, digest, expected), 'Platform evidence source changed without current evidence: ' + name)
    for name, expected in livehime['code_sha256'].items():
        digest = hashlib.sha256(local(name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(source_matches(name, digest, expected), 'Livehime evidence source changed: ' + name)
    for name, expected in split['code_sha256'].items():
        digest = hashlib.sha256(local(name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(source_matches(name, digest, expected), 'Split-device evidence source changed: ' + name)
    split_media = load('docs/media/split-device-media-manifest.json')
    check(report_digest_matches(local(split_media['report']), split_media['report_sha256']),
          'Split-device media report checksum')
    for item in split_media['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'],
              'Split-device media checksum: ' + item['file'])
    counts['split_device_documentation_media'] = len(split_media['items'])
    livehime_media = load('docs/media/livehime-media-manifest.json')
    check(report_digest_matches(local(livehime_media['report']), livehime_media['report_sha256']), 'Livehime media report checksum')
    for item in livehime_media['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'],
              'Livehime media checksum: ' + item['file'])
    counts['livehime_documentation_media'] = len(livehime_media['items'])
    platform_media = load('docs/media/platform-media-manifest.json')
    check(report_digest_matches(local(platform_media['report']), platform_media['report_sha256']),
          'Platform media report checksum')
    for item in platform_media['items']:
        path = local(item['file'])
        check(path.is_file() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'],
              'Platform media checksum: ' + item['file'])
    counts['platform_documentation_media'] = len(platform_media['items'])

    if args.media:
        probe = shutil.which('ffprobe')
        if not probe:
            raise RuntimeError('--media requires native ffprobe on PATH')
        videos = [p for p in files if p.suffix.lower() == '.mp4']
        for path in videos:
            data = json.loads(subprocess.check_output([probe, '-v', 'error', '-show_entries',
                'stream=codec_type,width,height,r_frame_rate,nb_frames:format=duration', '-of', 'json', str(path)], timeout=20))
            check(float(data['format']['duration']) > 0, 'Empty MP4: ' + path.name)
            video = next(s for s in data['streams'] if s['codec_type'] == 'video')
            relative = path.relative_to(ROOT).as_posix()
            if relative.startswith('outputs/vertical/materials/'):
                check((video['width'], video['height'], video['r_frame_rate'], int(video['nb_frames'])) == (720, 1280, '25/1', 200), 'Source media format: ' + relative)
            if relative.startswith('outputs/vertical/source/'):
                check((video['width'], video['height'], video['r_frame_rate'], int(video['nb_frames'])) == (736, 1312, '24/1', 192), 'Baseline generation format: ' + relative)
            if relative.startswith('docs/media/s0'):
                check((video['width'], video['height'], video['r_frame_rate']) == (432, 768, '25/1'), 'Preview format: ' + relative)
                check(any(s['codec_type'] == 'audio' for s in data['streams']), 'Scenario preview has no audio: ' + relative)
            if relative == 'docs/media/rtx3080-welcome.mp4':
                check((video['width'], video['height'], video['r_frame_rate']) == (432, 768, '25/1'), 'RTX 3080 preview format')
                check(any(s['codec_type'] == 'audio' for s in data['streams']), 'RTX 3080 preview has no audio')
            if relative.startswith('docs/media/livehime-') and relative != 'docs/media/livehime-ui-interaction.mp4':
                check((video['width'], video['height'], video['r_frame_rate']) == (432, 768, '30/1'), 'Livehime preview format: ' + relative)
                check(any(s['codec_type'] == 'audio' for s in data['streams']), 'Livehime preview has no audio: ' + relative)
        counts['ffprobe_videos'] = len(videos)

    result = {'ok': not failures, 'scope': 'repository checks; not a fresh GPU deployment', 'counts': counts, 'failures': failures}
    cache = ROOT / 'cache'
    cache.mkdir(exist_ok=True)
    (cache / 'repository-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1

if __name__ == '__main__':
    sys.exit(main())
