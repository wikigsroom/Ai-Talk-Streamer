"""Run one preparation stage with the same native/offline environment as live inference."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from runtime_environment import environment

ALLOWED = {
    'compose_vertical_loop', 'prepare_vertical_avatar', 'prepare_motion_library',
    'assemble_motion_bank', 'package_motion_materials', 'finalize_preparation',
}

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ALLOWED:
        raise SystemExit('Specify a documented avatar preparation stage')
    name = sys.argv[1]
    folder = 'deployment' if name == 'finalize_preparation' else 'scripts'
    command = [str(ROOT / 'runtime/livetalking/Scripts/python.exe'), '-X', 'utf8', '-B',
               str(ROOT / folder / (name + '.py')), *sys.argv[2:]]
    subprocess.run(command, cwd=ROOT, env=environment(), check=True)

if __name__ == '__main__':
    main()
