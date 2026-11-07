"""Start exactly the configured native game; never select a slot or arm control."""
from pathlib import Path
import json
import subprocess
import time
from manage_stack import ROOT, game, read


def main():
    existing = game()
    if existing:
        print(json.dumps({'already_running': True, 'pid': existing.pid, 'gameplay_armed': False})); return
    config = read('game-install.json')
    root = Path(config['game_root']); exe = root/config['executable']
    if not exe.is_file(): raise RuntimeError('Configured game executable is missing')
    folder = ROOT/'logs/services'; folder.mkdir(parents=True, exist_ok=True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 4
    with (folder/('game-'+str(time.time_ns())+'.log')).open('ab', buffering=0) as output:
        process = subprocess.Popen([str(exe), *config.get('launch_arguments', ['--luadebug'])],
                                   cwd=root, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   close_fds=True, startupinfo=startup)
    print(json.dumps({'started': True, 'pid': process.pid, 'gameplay_armed': False,
                      'next': 'Wait for loading; select only authorized slot 3 using normal game menus.'}))


if __name__ == '__main__': main()
