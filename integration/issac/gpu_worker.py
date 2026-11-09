"""Owned application entry for the optional non-model CUDA geometry worker."""
import argparse
import importlib.util
from pathlib import Path
from .common import inside, read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    config = read_json(inside(args.root, 'configs/issac/gpu-geometry.json'))
    if config.get('enabled') is not True:
        raise RuntimeError('GPU_GEOMETRY_NOT_ENABLED')
    spec = importlib.util.spec_from_file_location('isaac_gpu_worker', inside(args.root, 'integration/isaac-agent/isaac_gpu_worker.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.serve(config['port'], config['health_port'])


if __name__ == '__main__': main()
