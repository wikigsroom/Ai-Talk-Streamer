"""Run the CPU installation and local speech-resource checks in their native environments."""
from pathlib import Path
import subprocess, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from runtime_environment import environment
env = environment(cpu=True)
for relative, executable in [('deployment/readiness.py', ROOT/'runtime/livetalking/Scripts/python.exe'), ('deployment/asset_probe.py', ROOT/'runtime/tts/Scripts/python.exe')]:
    subprocess.run([str(executable), '-X', 'utf8', '-B', str(ROOT/relative)], cwd=ROOT, env=env, check=True)
