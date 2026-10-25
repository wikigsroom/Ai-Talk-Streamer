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
                check(not private.search(text), 'Private device identifier in: ' + rel.as_posix())
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
    dsh_docs = load('docs/evidence/dsh-humanity-doc-validation.json')
    for item in dsh_docs['artifacts']:
        digest = hashlib.sha256(local(item['path']).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(digest == item['sha256'], 'DSH documented source changed after validation: ' + item['path'])
    dsh_runtime = load('docs/evidence/dsh-humanity-runtime.json')
    for name, expected in dsh_runtime['code_sha256'].items():
        digest = hashlib.sha256(local(name).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
        check(digest == expected, 'DSH runtime evidence source changed: ' + name)

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
        counts['ffprobe_videos'] = len(videos)

    result = {'ok': not failures, 'scope': 'repository checks; not a fresh GPU deployment', 'counts': counts, 'failures': failures}
    cache = ROOT / 'cache'
    cache.mkdir(exist_ok=True)
    (cache / 'repository-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1

if __name__ == '__main__':
    sys.exit(main())
