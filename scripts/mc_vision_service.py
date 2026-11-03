"""Owned Windows vision worker; uses only already pinned local model files."""
from pathlib import Path
import os
import platform
import subprocess
import time
import urllib.parse
from native_operation import atomic_json, read_json, safe_path, registered_worker
from native_windows_process import NativeJob, identity_alive
from mc_application import NativeServices, require

ROOT = Path(__file__).resolve().parents[1]


def launch_arguments(root, lock):
    base = urllib.parse.urlsplit(lock['base_url'])
    require(base.scheme == 'http' and base.hostname == '127.0.0.1' and base.port == 8019,
            'MC_APPLICATION_VISION_CANONICAL_ENDPOINT')
    alias = lock.get('model_alias')
    require(isinstance(alias, str) and 0 < len(alias) <= 128 and all(c.isalnum() or c in '-_.' for c in alias),
            'MC_APPLICATION_VISION_ALIAS')
    files = [str(safe_path(root, root / lock[k]['path'])) for k in ('executable', 'model', 'projector')]
    return [files[0], '--model', files[1], '--mmproj', files[2], '--host', '127.0.0.1', '--port', '8019',
            '--alias', alias, '--ctx-size', '2048', '--parallel', '1', '--threads', '8',
            '--threads-batch', '12', '--batch-size', '256', '--ubatch-size', '128',
            '--image-min-tokens', '256', '--image-max-tokens', '256',
            '--n-gpu-layers', '0', '--no-webui', '--no-mmproj-offload']


def run(root=ROOT):
    root = Path(root).resolve()
    require(os.name == 'nt' and platform.node().casefold() == 'desktop-2qqpn1h',
            'MC_NATIVE_RUNTIME_REQUIRES_REMOTE_3080')
    services = NativeServices(root); lock = services.vision_lock(verify=True)
    arguments = launch_arguments(root, lock)
    end = time.monotonic() + 5; record = {}
    while time.monotonic() < end:
        record = read_json(safe_path(root, root / '.setup/mc-vision-owner.json'))
        if registered_worker(record, __file__): break
        time.sleep(.05)
    require(registered_worker(record, __file__), 'MC_APPLICATION_VISION_OWNER_MISSING')
    result = {'owner': {k: record[k] for k in ('pid', 'creation_ticks')}, 'downloads_performed': False,
              'public_broadcast_started': False, 'automatic_input_authorized': False}
    job = NativeJob(); child = None
    try:
        logs = safe_path(root, root / 'logs'); logs.mkdir(exist_ok=True)
        with (logs / 'mc-vision-server.log').open('ab') as stream:
            backend = 'cuda124' if lock.get('runtime_id')=='qwen3vl4b-q4km-llama-b11960-cuda124-v1' else 'vulkan' if lock.get('runtime_id')=='qwen3vl4b-q4km-llama-b11960-vulkan-v1' else 'cpu'
            environment = {**os.environ, 'CUDA_VISIBLE_DEVICES': '0' if backend=='cuda124' else '-1', 'GGML_VK_VISIBLE_DEVICES':'0', 'HF_HUB_OFFLINE': '1'}
            if backend != 'cpu':
                free = subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True,timeout=10)
                # Eight language layers consumed 869 MiB; the actual concurrent
                # speech/game/vision run left only 292 MiB. Keep this shared
                # 10 GiB card for avatar, voices, game and official recording.
                # The pinned Vulkan/CUDA binary can run both model parts on CPU.
                result['memory_budget'] = {'free_vram_mib_before': int(free.strip()),
                    'model_budget_mib': 0, 'render_reserve_mib': 1536,
                    'required_free_vram_mib': 1536, 'gpu_layers': 0, 'projector_device': 'cpu',
                    'language_device': 'cpu', 'threads': 8, 'batch_threads': 12}
                require(int(free.strip()) >= 1536, 'MC_VISION_FREE_VRAM_BELOW_RENDER_RESERVE')
                runtime = safe_path(root, root / 'runtimes/vision' / backend)
                environment['PATH'] = os.pathsep.join(sorted({str(p.parent) for p in runtime.rglob('*.dll')}) + [environment.get('PATH','')])
            child = job.spawn(arguments, cwd=root, env=environment, stdout=stream, stderr=stream)
            result['process'] = child.identity()
            atomic_json(root, root / '.setup/mc-vision-process.json', result)
            while child.poll() is None:
                stop = read_json(safe_path(root, root / '.setup/mc-vision-stop.json'))
                if stop.get('owner') == result['owner']:
                    result['stop_requested'] = True; job.rollback(); break
                time.sleep(.2)
            result['exit_code'] = child.wait(timeout=15)
    finally:
        if job.active(): job.rollback()
        result['all_owned_processes_closed'] = job.active() == 0
        job.close()
        if child: child.close()
        atomic_json(root, root / '.setup/mc-vision-exit.json', result)
    return result


if __name__ == '__main__': run()
