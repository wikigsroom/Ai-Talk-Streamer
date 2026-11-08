"""Copy pinned, existing inference dependencies without pip or external links."""
from __future__ import annotations

from pathlib import Path
import re
import shutil

from .common import AdmissionError,file_hash,inside,read_json,write_json

EXISTING_SHARED_SITE=Path('C:/dev/虚拟数字人直播/runtime/tts/Lib/site-packages')
EXISTING_PACKAGES={'pydub':'0.25.1','sentencepiece':'0.2.2'}


def install_voice_dependencies(root):
    root=Path(root).resolve()
    config_path=inside(root,'configs/issac/offline-voice-dependencies.json')
    config=read_json(config_path)
    source=EXISTING_SHARED_SITE.resolve()
    if Path(config['existing_source']).resolve()!=source:
        raise AdmissionError('PINNED_EXISTING_VOICE_DEPENDENCY_SOURCE_REQUIRED')
    target=inside(root,'runtime/tts-benchmark/omnivoice/Lib/site-packages')
    rows=config['files']
    packages=config.get('packages',[{'name':'pydub','version':'0.25.1'}])
    if (not isinstance(packages,list) or not packages or any(not isinstance(p,dict) or
            EXISTING_PACKAGES.get(p.get('name'))!=p.get('version') for p in packages)
            or len({p['name'] for p in packages})!=len(packages)):
        raise AdmissionError('PINNED_EXISTING_VOICE_PACKAGES_REQUIRED')
    allowed={name for p in packages for name in (p['name'],p['name']+'-'+p['version']+'.dist-info')}
    names=[r['path'] for r in rows]
    if (not rows or len(names)!=len(set(names)) or any(Path(n).parts[0] not in allowed
            or Path(n).is_absolute() or '..' in Path(n).parts or ':' in n or '\\' in n for n in names)):
        raise AdmissionError('PINNED_INFERENCE_DEPENDENCY_MEMBERS_REQUIRED')
    if any(p['name']=='sentencepiece' for p in packages):
        required={'sentencepiece/__init__.py','sentencepiece/_sentencepiece.cp310-win_amd64.pyd',
                  'sentencepiece-0.2.2.dist-info/METADATA','sentencepiece-0.2.2.dist-info/WHEEL'}
        if not required.issubset(names):raise AdmissionError('PINNED_CP310_WINDOWS_SENTENCEPIECE_REQUIRED')
    for package in packages:
        for other in target.glob(package['name']+'-*.dist-info'):
            if other.name not in allowed:raise AdmissionError('EXISTING_VOICE_PACKAGE_CONFLICT_PRESERVED')
    for top in allowed:
        folder=target/top
        if folder.exists():
            for path in folder.rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                    if path.relative_to(target).as_posix() not in names:
                        raise AdmissionError('EXISTING_VOICE_PACKAGE_EXTRA_FILE_PRESERVED')
    # Verify the whole source and destination set before the first copy.
    for row in rows:
        path=source/row['path'];destination=inside(target,row['path'])
        if (not path.resolve().is_relative_to(source) or path.is_symlink() or not path.is_file()
                or not re.fullmatch('[0-9a-f]{64}',row['sha256'])
                or path.stat().st_size!=row['bytes'] or file_hash(path)!=row['sha256']):
            raise AdmissionError('EXISTING_VOICE_DEPENDENCY_CHANGED')
        if destination.exists() and (not destination.is_file() or file_hash(destination)!=row['sha256']):
            raise AdmissionError('EXISTING_VOICE_PACKAGE_CONFLICT_PRESERVED')
    copied=0
    for row in rows:
        path=source/row['path'];destination=inside(target,row['path'])
        if not destination.exists():
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination);copied+=1
        if destination.stat().st_size!=row['bytes'] or file_hash(destination)!=row['sha256']:
            raise AdmissionError('COPIED_VOICE_DEPENDENCY_CHECKSUM_MISMATCH')
    record={'package':'+'.join(p['name'] for p in packages),'version':'+'.join(p['version'] for p in packages),
        'packages':packages,'files_verified':len(rows),
        'bytes_verified':sum(r['bytes'] for r in rows),'new_files_copied':copied,
        'configuration_sha256':file_hash(config_path),'new_download_bytes':0,
        'external_runtime_path_added':False,'application_import_tested':False,
        'voice_selection_changed':False}
    write_json(inside(root,'.setup/voice-offline-dependencies.json'),record)
    return record
