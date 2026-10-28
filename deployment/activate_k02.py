"""Offline, narrowly scoped K02 activation in an existing native runtime root."""
import argparse
import ast
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys


def patch_sources(base, muse):
    """Check pinned source contracts and produce an idempotent reviewed patch."""
    base_marker = '            res_frame,audio_frames,idx = self.res_frame_queue.get(block=True, timeout=1)'
    if '            # K02: consume audio on the frame consumer' not in base:
        if base.count(base_marker) != 1:
            raise RuntimeError('Pinned frame-consumer contract missing or ambiguous')
        # Outside the queue try/except, so queue.Empty continues normally.
        start = base.index('    def process_frames(')
        marker = '            # 检测状态变化'
        at = base.index(marker, start)
        base = base[:at] + ('            # K02: consume audio on the frame consumer\n'
            '            if getattr(self, "_studio_k02", None) is not None:\n'
            '                self._studio_k02.advance(audio_frames)\n\n') + base[at:]
    if 'from server.lipsync_k02 import K02Compositor' not in muse:
        marker = 'from avatars.base_avatar import BaseAvatar'
        if muse.count(marker) != 1:
            raise RuntimeError('Pinned MuseTalk base import missing')
        muse = muse.replace(marker, marker+'\nfrom server.lipsync_k02 import K02Compositor', 1)
    if '        self._studio_k02 = K02Compositor()' not in muse:
        marker = '        super().__init__(opt)'
        if muse.count(marker) != 1:
            raise RuntimeError('Pinned MuseTalk constructor missing')
        muse = muse.replace(marker, marker+'\n        self._studio_k02 = K02Compositor()', 1)
    if '        # K02: composite the current frame using its dequeued PCM gate' not in muse:
        marker = '    def paste_back_frame(self,pred_frame,idx:int):'
        if muse.count(marker) != 1:
            raise RuntimeError('Pinned MuseTalk paste-back signature missing')
        muse = muse.replace(marker, marker+'\n'
            '        # K02: composite the current frame using its dequeued PCM gate\n'
            '        if getattr(self, "_studio_k02", None) is not None:\n'
            '            return self._studio_k02.blend(self.frame_list_cycle[idx], pred_frame, self.coord_list_cycle[idx])', 1)
    for name, source in [('base_avatar.py', base), ('musetalk_avatar.py', muse)]:
        ast.parse(source, filename=name)
    return base, muse


def activate(root):
    for port in (8010, 9880, 9881, 9882):
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('Stop this project media/TTS before offline K02 activation')
    root = root.resolve(strict=True)
    live = root/'src/LiveTalking'
    options = json.loads((root/'configs/livetalking.yaml').read_text('utf-8-sig'))
    hardware_path = root/'configs/hardware-profile.json'
    hardware = json.loads(hardware_path.read_text('utf-8-sig')) if hardware_path.exists() else {}
    approved_batch = options.get('batch_size') == 8 or (
        options.get('batch_size') == 4 and hardware.get('preset') == 'rtx3080-k02-batch4')
    if options.get('model') != 'musetalk' or options.get('fps') != 25 or not approved_batch:
        raise RuntimeError('Expected MuseTalk / 25 FPS with batch8 or the explicit RTX3080 batch4 profile')
    base_path, muse_path = live/'avatars/base_avatar.py', live/'avatars/musetalk_avatar.py'
    base, muse = patch_sources(base_path.read_text('utf-8-sig'), muse_path.read_text('utf-8-sig'))
    helper = root/'integration/lipsync_k02.py'
    ast.parse(helper.read_text('utf-8-sig'))
    sys.path.insert(0, str(root))
    # No Torch/CUDA import or model allocation: profile is an auditable constant.
    profile_tree = ast.parse(helper.read_text('utf-8-sig'))
    profile = next(ast.literal_eval(node.value) for node in profile_tree.body
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PROFILE' for t in node.targets))
    changed = {base_path: base, muse_path: muse,
        live/'server/lipsync_k02.py': helper.read_text('utf-8-sig'),
        root/'configs/lipsync.json': json.dumps({**profile, 'batch_size':options['batch_size'],
            'reference_profile_batch_size':profile['batch_size']}, ensure_ascii=False, indent=2)}
    stamp = datetime.datetime.now().astimezone().isoformat()
    backup = root/'.setup/k02/backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    records = []
    for target, text in changed.items():
        if target.exists():
            saved = backup/target.relative_to(root)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix+'.k02-part')
        temp.write_text(text+'\n', encoding='utf-8', newline='\n')
        temp.replace(target)
        records.append({'path':target.relative_to(root).as_posix(), 'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    receipt = {'at':stamp, 'profile':profile, 'files':records, 'batch_size':options['batch_size'],
        'backup':backup.relative_to(root).as_posix(), 'services_started':False,
        'new_models_downloaded':False, 'remote_inference_validated':False,
        'private_livetalking_config_changed':False, 'memory_or_platform_changed':False}
    out = root/'.setup/k02/activation.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    activate(parser.parse_args().root)
