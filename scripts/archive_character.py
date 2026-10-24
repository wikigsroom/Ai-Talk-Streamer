"""Build and verify the 女A asset archive using reviewed, project-local files."""
from pathlib import Path
import argparse
import collections
import csv
import hashlib
import io
import json
import os
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'archives/female-a'
GROUPS = {
    'identity': '00_角色档案',
    'references': '01_人物与场景',
    'motions': '02_正式动作视频',
    'baseline': '03_基础待机',
    'poses': '04_独立动作照',
    'previews': '05_封面与关键帧',
    'generation': '06_提示词与生成记录',
    'review': '07_审核与历史记录',
    'validation': '08_测试录像与页面展示',
    'runtime': '09_运行配置与来源索引',
    'code': '10_配套代码与文档',
}


def local(relative):
    path = (ROOT / relative).resolve()
    path.relative_to(ROOT)
    return path


def load(relative):
    return json.loads(local(relative).read_text(encoding='utf-8'))


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def collect(identity):
    entries = {}

    def add(source, group, destination=None, asset_id=None):
        path = local(source)
        if not path.is_file():
            raise FileNotFoundError(source)
        if path.name in ('channel.env', 'device.json') or path.suffix in ('.env', '.key', '.pem'):
            raise ValueError('Private configuration cannot enter an asset archive')
        source = path.relative_to(ROOT).as_posix()
        if source in entries:
            raise ValueError('Duplicate source path: ' + source)
        archive_path = GROUPS[group] + '/' + (destination or source)
        entries[source] = {'source': source, 'archive_path': archive_path, 'group': group,
                           'bytes': path.stat().st_size, 'sha256': digest(path)}
        if asset_id:
            entries[source]['asset_id'] = asset_id

    add('configs/characters/female-a.json', 'identity', 'character.json')
    for field in ('appearance_reference', 'source_reference', 'portrait_source'):
        add(identity[field], 'references', Path(identity[field]).name)
    background = identity['scene']['background_reference']
    add(background, 'references', Path(background).name)

    catalog = load('configs/vertical/materials/catalog.json')
    reviews = load('configs/vertical/materials/reviews.json')
    delivered = load('outputs/vertical/materials/delivery-manifest.json')
    hashes = {item['id']: item['sha256'] for item in delivered['items']}
    clips = catalog['items']
    if len(clips) != 48 or any(not reviews.get(item['id'], {}).get('accepted') for item in clips):
        raise ValueError('Expected the complete 48-clip reviewed motion selection')
    for item in clips:
        add(item['source_video'], 'motions', item['category_label'] + '/' + item['id'] + '.mp4', item['id'])
        if entries[item['source_video']]['sha256'] != hashes[item['id']]:
            raise ValueError('Reviewed motion hash changed: ' + item['id'])
    if len({entries[item['source_video']]['sha256'] for item in clips}) != len(clips):
        raise ValueError('Motion copies must not count as independent generations')

    baseline = load('configs/vertical/baseline-media.json')['items']
    for item in baseline:
        add(item['file'], 'baseline', Path(item['file']).name)
        if entries[item['file']]['sha256'] != item['sha256']:
            raise ValueError('Baseline hash changed')

    poses = load('output/imagegen/motion-poses/delivery.json')
    pose_reviews = load('output/imagegen/motion-poses/reviews.json')
    if len(poses['items']) != 28 or not poses.get('ok'):
        raise ValueError('Expected 28 reviewed independent pose photographs')
    for item in poses['items']:
        if not pose_reviews.get(item['id'], {}).get('accepted'):
            raise ValueError('Unreviewed pose: ' + item['id'])
        for field, folder, expected in [('native', '原图', 'sha256'), ('delivery', '720x1280', 'delivery_sha256')]:
            add(item[field], 'poses', folder + '/' + item['category'] + '/' + item['id'] + '.png', item['id'])
            if entries[item[field]]['sha256'] != item[expected]:
                raise ValueError('Reviewed pose hash changed: ' + item['id'])
        add(item['prompt'], 'generation')

    for folder, group in [('outputs/vertical/materials/posters', 'previews'),
                          ('outputs/vertical/materials/keyframes', 'previews'),
                          ('outputs/vertical/materials/review', 'review')]:
        for path in sorted(local(folder).iterdir()):
            if path.is_file():
                add(path.relative_to(ROOT).as_posix(), group)
    for path in sorted(local('configs/vertical').rglob('*')):
        if not path.is_file():
            continue
        group = 'review' if path.name == 'reviews.json' else 'generation' if path.name.endswith(('.api.json', '.history.json', '.prompt.txt')) else 'runtime'
        add(path.relative_to(ROOT).as_posix(), group)
    for source, group in [('output/imagegen/motion-poses/manifest.json', 'generation'),
                          ('output/imagegen/motion-poses/reviews.json', 'review'),
                          ('output/imagegen/motion-poses/delivery.json', 'runtime'),
                          ('outputs/vertical/materials/delivery-manifest.json', 'runtime'),
                          ('configs/model-files.csv', 'runtime'),
                          ('configs/sources.lock.json', 'runtime'),
                          ('configs/channel.env.example', 'runtime'),
                          ('configs/requirements-tts-verified.txt', 'runtime'),
                          ('configs/requirements-livetalking-verified.txt', 'runtime')]:
        add(source, group)
    # Capture published evidence only; raw browser profiles and private recordings stay out.
    for folder in ['docs/media', 'docs/evidence']:
        for path in sorted(local(folder).iterdir()):
            if path.is_file():
                add(path.relative_to(ROOT).as_posix(), 'validation')
    for folder in ['integration', 'web', 'deployment', 'scripts', 'devtools', 'tests']:
        for path in sorted(local(folder).iterdir()):
            if path.is_file() and path.suffix in ('.py', '.js', '.cjs', '.html', '.css', '.ps1', '.cmd'):
                add(path.relative_to(ROOT).as_posix(), 'code')
    for path in sorted(local('docs').glob('*.md')):
        add(path.relative_to(ROOT).as_posix(), 'code')
    for path in sorted(ROOT.iterdir()):
        if path.is_file() and (path.suffix in ('.md', '.cmd', '.ps1') or path.name in ('LICENSE', 'NOTICE', 'package.json', 'package-lock.json', '.gitignore', '.gitattributes')):
            add(path.name, 'code')
    return sorted(entries.values(), key=lambda item: item['archive_path']), clips, poses, reviews


def build(refresh=False):
    identity = load('configs/characters/female-a.json')
    destination = local(identity['archive']['directory'])
    archive = local(identity['archive']['zip'])
    if (destination.exists() or archive.exists()) and not refresh:
        raise FileExistsError('Archive already exists. Use --refresh to update the same snapshot.')
    entries, clips, poses, reviews = collect(identity)
    counts = collections.Counter(item['group'] for item in entries)
    manifest = {
        'schema_version': 1, 'character_id': identity['id'], 'archive_label': identity['archive_label'],
        'name': identity['name'], 'scene_id': identity['scene']['id'], 'scene_name': identity['scene']['name'],
        'version': identity['archive']['version'], 'named_on': identity['archive']['named_on'],
        'runtime_avatar_id': identity['runtime_avatar_id'],
        'file_count': len(entries), 'total_bytes': sum(item['bytes'] for item in entries),
        'counts': {'selected_motion_clips': len(clips), 'selected_motion_seconds': sum(item['duration_seconds'] for item in clips),
                   'baseline_clips': 2, 'baseline_seconds': 16, 'live_bank_clips': 50, 'live_bank_frames': 10000,
                   'independent_pose_images': len(poses['items']), 'resized_pose_images': len(poses['items']),
                   'posters': 48, 'keyframes': 48, 'historical_scenario_recordings': 5,
                   'rejected_motion_review_records': sum(not item.get('accepted') for item in reviews.values())},
        'groups': [{'id': key, 'label': label, 'files': counts[key]} for key, label in GROUPS.items()],
        'notes': [
            'Historical test speech and evidence retain the original alias 小晴; current identity is 林知夏.',
            'Resized poses, posters and keyframes are derivatives, not additional independent generations.',
            'Rejected takes are retained as review records and evidence, not as accepted motion clips.',
            'Model weights, installed runtimes, credentials and the decoded live bank are not duplicated here.',
            'Original canonical source paths are preserved; archive_path is a separate categorized copy.',
        ],
        'items': entries,
    }
    REGISTRY.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
    (REGISTRY / 'manifest.json').write_text(manifest_text, encoding='utf-8', newline='\n')
    csv_text = io.StringIO(newline='')
    writer = csv.DictWriter(csv_text, fieldnames=['group', 'asset_id', 'source', 'archive_path', 'bytes', 'sha256'])
    writer.writeheader()
    writer.writerows(entries)
    (REGISTRY / 'inventory.csv').write_text(csv_text.getvalue(), encoding='utf-8-sig', newline='')
    for item in entries:
        target = destination / item['archive_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and digest(target) == item['sha256']:
            continue
        temporary = target.with_name(target.name + '.copying')
        shutil.copyfile(local(item['source']), temporary)
        temporary.replace(target)
    record = destination / GROUPS['identity']
    shutil.copyfile(REGISTRY / 'manifest.json', record / 'manifest.json')
    shutil.copyfile(REGISTRY / 'inventory.csv', record / 'inventory.csv')
    overview = (
        '# 女A · 林知夏 / Lin Zhixia\n\n'
        '场景：知夏的日光宿舍 / Zhixia\'s Daylight Dorm.\n\n'
        '角色为虚构的22岁中国女大学生，使用已确认的白天宿舍、浅蓝卫衣和9:16构图。\n\n'
        '48段正式动作 + 2段基础待机，共400秒；28张独立动作照及28张缩放版分别存放。\n\n'
        'manifest.json records source paths, categorized archive paths, file sizes and SHA-256 hashes. '
        'inventory.csv opens directly in Excel with Chinese labels. Reconstruct source layout using the source field.\n\n'
        '中文：请先看 character.json、manifest.json 和 inventory.csv；目录01到10分别存放参考图、动作视频、待机、动作照、预览、生成记录、审核、测试、配置和代码。\n\n'
        '历史测试中的“小晴”是命名前称呼；原始录屏与记录保留，不修改验收证据。\n\n'
        'Historical recordings retain the former test alias. Rejected generations are represented by review records, '
        'not counted as accepted footage. Resized images and video frames are derivatives.\n\n'
        '配套代码与文档位于10_配套代码与文档；直播技术编号保持 student_dorm_motion_bank_v3。'
        '模型权重、已安装程序、Python环境、密钥及解码后的万帧缓存沿用运行环境，不在本素材包内重复打包。\n\n'
        'Models, installed programs, environments, secrets and decoded frame caches are excluded. '
        'Third-party terms remain applicable; see THIRD_PARTY_NOTICES.md in the code/documentation directory.\n'
    )
    (record / 'README.md').write_text(overview, encoding='utf-8', newline='\n')
    members = [item['archive_path'] for item in entries] + [GROUPS['identity'] + '/' + name for name in ('manifest.json', 'inventory.csv', 'README.md')]
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_suffix('.zip.building')
    # Fixed metadata and stored media make archives deterministic across native hosts.
    date = tuple(map(int, identity['archive']['named_on'].split('-'))) + (0, 0, 0)
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
        for relative in sorted(members):
            info = zipfile.ZipInfo(relative, date_time=date)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            with (destination / relative).open('rb') as source, bundle.open(info, 'w', force_zip64=True) as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    os.replace(temporary, archive)
    result = verify()
    (REGISTRY / 'release.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return result


def verify():
    identity = load('configs/characters/female-a.json')
    manifest = load('archives/female-a/manifest.json')
    destination = local(identity['archive']['directory'])
    archive = local(identity['archive']['zip'])
    expected = {item['archive_path'] for item in manifest['items']}
    expected.update(GROUPS['identity'] + '/' + name for name in ('manifest.json', 'inventory.csv', 'README.md'))
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist()) != expected or len(bundle.namelist()) != len(expected):
            raise ValueError('Unexpected or duplicate archive member')
        archived_manifest = json.loads(bundle.read(GROUPS['identity'] + '/manifest.json'))
        if archived_manifest != manifest or json.loads((destination / GROUPS['identity'] / 'manifest.json').read_text(encoding='utf-8')) != manifest:
            raise ValueError('Archive manifest differs from the registry')
        for item in manifest['items']:
            target = destination / item['archive_path']
            if target.stat().st_size != item['bytes'] or digest(target) != item['sha256']:
                raise ValueError('Archive folder hash differs: ' + item['archive_path'])
            value = hashlib.sha256()
            with bundle.open(item['archive_path']) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(block)
            if value.hexdigest() != item['sha256']:
                raise ValueError('ZIP hash differs: ' + item['archive_path'])
    return {'ok': True, 'character_id': identity['id'], 'archive_label': identity['archive_label'],
            'name': identity['name'], 'scene_name': identity['scene']['name'], 'version': identity['archive']['version'],
            'archive': identity['archive']['zip'], 'bytes': archive.stat().st_size, 'sha256': digest(archive),
            'source_files': manifest['file_count'], 'zip_entries': len(expected),
            'download_url': '/character/archive.zip', 'counts': manifest['counts']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'verify'))
    parser.add_argument('--refresh', action='store_true', help='Replace the current generated snapshot; preserve source files')
    args = parser.parse_args()
    print(json.dumps(build(args.refresh) if args.action == 'build' else verify(), ensure_ascii=False))
