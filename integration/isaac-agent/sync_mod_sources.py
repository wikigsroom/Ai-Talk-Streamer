"""Back up and synchronize six controller sources (including first install) to the selected game."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT=Path(__file__).resolve().parent
FILES=('main.lua','metadata.xml','timed_spikes.lua','tnt_safety.lua','weapon_control.lua','strategy_control.lua')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'native\d+',args.version):
        parser.error('Expected a native controller version')
    install=json.loads((ROOT/'game-install.json').read_text(encoding='utf8'))
    game_root=Path(install['game_root'])
    if not (game_root/install['executable']).is_file():
        raise RuntimeError('Selected game executable is missing')
    target=game_root/'mods/IsaacJev'
    if any(p.is_symlink() or p.is_junction() for p in (game_root,game_root/'mods',target)):
        raise RuntimeError('Linked destination is not supported')
    for name in FILES:
        if not (ROOT/'mods/IsaacJev'/name).is_file():
            raise RuntimeError('Missing selected installation or source file: '+name)
        if (target/name).is_symlink(): raise RuntimeError('Linked destination file: '+name)
    backup=ROOT/'backups'/('before-'+args.version+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    target.mkdir(parents=True,exist_ok=True)
    records=[]
    for name in FILES:
        dest=target/name
        before=hashlib.sha256(dest.read_bytes()).hexdigest() if dest.is_file() else None
        if dest.is_file(): shutil.copy2(dest,backup/name)
        shutil.copy2(ROOT/'mods/IsaacJev'/name,dest)
        after=hashlib.sha256(dest.read_bytes()).hexdigest()
        if after!=hashlib.sha256((ROOT/'mods/IsaacJev'/name).read_bytes()).hexdigest():
            raise RuntimeError('Source verification failed: '+name)
        records.append(dict(name=name,before=before,after=after))
    report=dict(version=args.version+' sources',target=str(target),backup=str(backup),
        files=records,runtime_mode='EnableMods=0; native input callbacks only')
    for path in (ROOT/'latest-mod-deployment.json',backup/'deployment.json'):
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(deployed=len(records),backup=str(backup)),ensure_ascii=False))


if __name__=='__main__':main()
