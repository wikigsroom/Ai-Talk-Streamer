"""Finalize the explicitly requested native RTX 3080 variant while media is off.

This configures an already prepared installation. It does not download models,
start services, migrate memory, change the cloud channel, or start broadcasting.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import importlib.util
import json
import shutil
import socket

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'native-rtx3080-v1.2.2-k02-o07-f07'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.3080-part')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def load(name):
    spec = importlib.util.spec_from_file_location('configure_3080_' + name, ROOT/'deployment'/(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure(batch_size=4):
    import runpy
    runpy.run_path(str(ROOT/'scripts/deployment_target.py'))['validate_target'](
        ROOT, expected_target='rtx3080', check_runtime=False)
    if batch_size not in (4, 8):
        raise ValueError('Only measured RTX3080 batch profiles are supported')
    for port in (8010, 9880, 9881, 9882, 3091, 3092):
        with socket.socket() as probe:
            probe.settimeout(.5)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Stop this project service on {port} before offline configuration')
    options = read(ROOT/'configs/livetalking.yaml')
    if (options.get('model'), options.get('avatar_id')) != ('musetalk', 'student_dorm_motion_bank_v3'):
        raise RuntimeError('Expected the retained female-A MuseTalk motion bank')
    live = ROOT/'src/LiveTalking'
    k02 = load('activate_k02')
    # Check the actual patched upstream contract before changing private options.
    k02.patch_sources((live/'avatars/base_avatar.py').read_text('utf-8-sig'),
                      (live/'avatars/musetalk_avatar.py').read_text('utf-8-sig'))
    resident = read(ROOT/'configs/resident-tts.example.json')
    if hashlib.sha256((ROOT/resident['reference_audio']).read_bytes()).hexdigest() != resident['reference_sha256']:
        raise RuntimeError('The approved O07 reference is missing or changed')
    for voice in resident['voices'].values():
        for key in ('python', 'source', 'model'):
            if not (ROOT/voice[key]).exists():
                raise RuntimeError('Missing prepared asset: ' + voice[key])
    pointer = ROOT/'configs/dsh-active-policy.json'
    old_policy_file = read(pointer)['policy_file'] if pointer.exists() else 'docs/dsh-humanity/examples/bridge-policy.example.json'
    old_policy = (ROOT/old_policy_file).resolve()
    if not old_policy.is_relative_to(ROOT.resolve()):
        raise RuntimeError('DSH policy must be inside this project')
    policy = read(old_policy)
    policy.pop('example_only', None)
    policy['deployment'].update(state_relative_path='state/female-a-3080-k02',
                                dsh_home_relative_path='state/female-a-3080-k02/dsh-home')
    policy['playback']['lease_timeout_ms'] = 30000
    stamp = datetime.datetime.now().astimezone().isoformat()
    backup = ROOT/'.setup/k02-3080/configuration-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    names = ['configs/livetalking.yaml', 'configs/hardware-profile.json',
             'configs/dsh-active-policy.json', 'configs/resident-tts.json',
             'configs/tts-selection.private.json', 'configs/dsh-enabled.json',
             'configs/platforms.private.json']
    for name in names:
        source = ROOT/name
        if source.is_file():
            target = backup/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    options.update(batch_size=batch_size, fps=25)
    write(ROOT/'configs/livetalking.yaml', options)
    write(ROOT/'configs/hardware-profile.json', {
        'preset': 'rtx3080-k02-batch4' if batch_size == 4 else 'rtx3080-k02-original', 'batch_size': batch_size, 'target_fps': 25,
        'cudnn_benchmark': True, 'canvas': [720, 1280],
        'minimum_free_gib': {'avatar': 2, 'tts': 2}, 'applied_at': stamp,
        'note': 'Launch gate only; actual original-strength co-residency must be tested.'})
    write(ROOT/'configs/dsh-3080-k02.private.json', policy)
    write(pointer, {'policy_file': 'configs/dsh-3080-k02.private.json'})
    platforms_path = ROOT/'configs/platforms.private.json'
    if platforms_path.exists():
        platforms = read(platforms_path)
        target = platforms.setdefault('platforms', {}).setdefault('bilibili', {})
        target.update(output_mode='livehime', client_location='receiver',
                      receiver_url='http://127.0.0.1:8020')
        write(platforms_path, platforms)
    # Existing native integrations are idempotent, with their own source backups.
    load('activate_studio').main()
    load('activate_resident_tts').activate()
    load('deploy_dsh').main()
    k02.activate(ROOT)
    receipt = {
        'release': RELEASE, 'configured_at': stamp, 'hardware': 'RTX 3080 10GB',
        'batch_size': batch_size, 'fps': 25, 'precision': 'FP16', 'lipsync': 'K02',
        'primary': 'O07', 'backup': 'F07', 'backup_directory': backup.relative_to(ROOT).as_posix(),
        'state_path': policy['deployment']['state_relative_path'],
        'prior_memory_migrated': False, 'channel_changed': False, 'platform_config_changed': True,
        'services_started': False, 'gpu_inference_validated': False, 'public_broadcast_started': False}
    write(ROOT/'.setup/k02-3080/configuration.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-size', type=int, choices=(4, 8), default=4)
    configure(parser.parse_args().batch_size)
