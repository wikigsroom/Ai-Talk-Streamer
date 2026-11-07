"""Read-only deployment checks. No model loading, configuration writes or stops."""
from pathlib import Path
import argparse
import json
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def contract(root):
    root = Path(root).resolve()
    registry = read(root/'configs/deployment-targets.json')
    selected = read(root/'configs/deployment-target.json')
    target = selected.get('target')
    if target is None:
        expected = registry['shared']
    else:
        if target not in registry['targets']:
            raise RuntimeError('Unknown deployment target')
        expected = registry['targets'][target]['selection']
    if selected != expected:
        raise RuntimeError('Deployment target descriptor differs from the branch contract')
    pointer = read(root/'configs/releases/current.json')
    expected_pointer = registry['shared_pointer'] if target is None else registry['targets'][target]['release_pointer']
    if pointer != expected_pointer:
        raise RuntimeError('Release pointer and deployment target do not match')
    return registry, selected


def validate_target(root=ROOT, *, expected_target=None, check_hardware=True, check_runtime=True, candidate=False):
    root = Path(root).resolve()
    registry, selected = contract(root)
    target = selected['target']
    if target == 'issac-rtx4090' and candidate:
        if expected_target != target:
            raise RuntimeError('Explicit issac-rtx4090 rehearsal target required')
        import sys
        if str(root) not in sys.path: sys.path.insert(0,str(root))
        from integration.issac.deployment import require_candidate
        return {'ok':True,'target':target,'branch':'issac','purpose':'frozen_candidate_local_rehearsal',
                **require_candidate(root,hardware=check_hardware),'public_broadcast_allowed':False}
    if target is None:
        raise RuntimeError('main contains shared source only. Use deploy/rtx3080 or deploy/rtx4090 before deploying or starting inference.')
    if selected.get('deployment_allowed') is not True:
        raise RuntimeError('Deployment is disabled for ' + target + '; integration and acceptance are pending. Services were not started.')
    if expected_target is not None and target != expected_target:
        raise RuntimeError('This operation requires ' + expected_target + '; selected target is ' + target)
    spec = registry['targets'][target]
    naimei = spec.get('engine') == 'flashhead-lite'
    if naimei and expected_target != target:
        raise RuntimeError('Naimei uses scripts/start_naimei.py; explicitly select naimei-rtx4090 instead of starting the inherited MuseTalk launcher')
    flags = {'creationflags':0x08000000} if os.name == 'nt' else {}
    if (root/'.git').exists():
        branch = subprocess.check_output(['git','-C',str(root),'branch','--show-current'],text=True,timeout=10,**flags).strip()
        if branch != selected['branch']:
            raise RuntimeError('Git branch differs from deployment target: expected ' + selected['branch'])
    else:
        origin_path = root/'.setup/deployment-origin.json'
        if not origin_path.is_file():
            raise RuntimeError('Copied runtime has no deployment-origin receipt; synchronize from its device branch first')
        origin = read(origin_path)
        if (origin.get('target'),origin.get('branch')) != (target,selected['branch']) or not re.fullmatch('[0-9a-f]{40}',str(origin.get('source_commit',''))):
            raise RuntimeError('Runtime source receipt belongs to another deployment target')
        if naimei and (not re.fullmatch('[0-9a-f]{64}', str(origin.get('archive_sha256', ''))) or not origin.get('verified_source_manifest')):
            raise RuntimeError('Naimei requires a verified source archive receipt from the naimei branch')
    if check_hardware:
        raw = subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader,nounits'],text=True,timeout=10,**flags)
        devices = [line.rsplit(',',1) for line in raw.strip().splitlines()]
        if not devices or any(len(row)!=2 or not re.search(spec['gpu_pattern'],row[0]) or int(row[1]) < spec['minimum_vram_mib'] for row in devices):
            raise RuntimeError('Inference GPU does not match ' + target + '; services were not started')
    if check_runtime:
        if naimei:
            options = read(root/'configs/naimei/live-runtime.json')
            expected = ('naimei', 'flashhead-lite', 512, 25, 4, spec['batch_size'])
            actual = tuple(options.get(key) for key in ('character_id', 'engine', 'size', 'fps', 'steps', 'stream_batch_size'))
            if actual != expected or options.get('target') != target or not options.get('native_windows_only') or options.get('cloud_inference_allowed'):
                raise RuntimeError('Naimei runtime differs from its native 512x512 single-stream contract')
            character = read(root/'configs/characters/naimei.json')
            if character.get('id') != 'naimei' or character.get('runtime_avatar_id') != 'naimei-o01-flashhead-512':
                raise RuntimeError('Naimei runtime character mismatch')
        else:
            options = read(root/'configs/livetalking.yaml')
            if (options.get('model'),options.get('batch_size'),options.get('fps')) != ('musetalk',spec['batch_size'],25):
                raise RuntimeError('MuseTalk configuration differs from the selected device baseline')
        pointer = read(root/'configs/dsh-active-policy.json')
        policy_path = (root/pointer['policy_file']).resolve()
        if not policy_path.is_relative_to(root):
            raise RuntimeError('DSH policy leaves the selected installation')
        state = read(policy_path)['deployment']['state_relative_path']
        if state.replace('\\','/').rstrip('/') != spec['state_path']:
            raise RuntimeError('DSH state directory belongs to another deployment target')
    return {'ok':True,'target':target,'branch':selected['branch'],'batch_size':spec['batch_size'],
            'state_path':spec['state_path'],'hardware_checked':check_hardware,'runtime_checked':check_runtime}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--describe',action='store_true')
    parser.add_argument('--expected-target',default=None)
    parser.add_argument('--candidate',action='store_true')
    args = parser.parse_args()
    if args.describe:
        print(json.dumps(contract(args.root)[1],ensure_ascii=False,indent=2))
    else:
        print(json.dumps(validate_target(args.root,expected_target=args.expected_target,candidate=args.candidate),ensure_ascii=False,indent=2))
