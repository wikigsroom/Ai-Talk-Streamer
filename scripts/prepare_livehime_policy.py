"""Select a project-local playback lease for native Livehime GPU warm-up stalls."""
from pathlib import Path
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Keep an existing session and policy untouched while it is in use.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:3092/api/dsh/status', timeout=4) as response:
            if json.load(response).get('broadcast'):
                raise RuntimeError('End the local session before selecting a policy')
    except urllib.error.URLError:
        pass
    pointer = ROOT / 'configs/dsh-active-policy.json'
    source = ROOT / 'docs/dsh-humanity/examples/bridge-policy.example.json'
    if pointer.exists():
        source = (ROOT / json.loads(pointer.read_text(encoding='utf-8-sig'))['policy_file']).resolve()
        if not source.is_relative_to(ROOT):
            raise RuntimeError('Active policy leaves the project')
    policy = json.loads(source.read_text(encoding='utf-8-sig'))
    policy.pop('example_only', None)
    # Measured 11.66 s CUDA warm-up can stall the shared graphics driver.
    # Completion still requires contiguous samples and a natural end receipt.
    policy['playback']['lease_timeout_ms'] = 30000
    target = ROOT / 'configs/livehime-policy.private.json'
    target.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    pointer.write_text(json.dumps({'policy_file': target.relative_to(ROOT).as_posix()}) + '\n', encoding='utf-8')
    print(json.dumps({'prepared': True, 'restart_dsh_required': True, 'gpu_restart_required': False,
                      'playback_lease_timeout_ms': 30000, 'inference_settings_changed': False}))


if __name__ == '__main__':
    main()
