"""Native relocation and read-only discovery before owned processes start."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re
import subprocess

from .common import AdmissionError, file_hash, inside, native_only, read_json, write_json
from .saves import SaveProtection, SLOT_FILE, GAME_SHA256


def windows_documents():
    native_only()
    # Use the actual Windows Documents known folder, including redirected
    # Documents. Do not assume the English spelling of a profile directory.
    documents=ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None,5,None,0,documents)!=0:
        raise AdmissionError('WINDOWS_DOCUMENTS_PATH_UNAVAILABLE')
    return Path(documents.value).resolve()


def save_roots(root):
    root=Path(root).resolve()
    candidates=[inside(root,'game')]
    parent=windows_documents()/'My Games'
    if parent.is_dir():
        candidates += sorted((p for p in parent.iterdir() if p.is_dir() and 'binding of isaac' in p.name.lower()),key=lambda p:p.name.lower())
    # Portable emulators may place data below the project game directory.
    # The recursive save-file filter in SaveProtection excludes game binaries.
    unique=[]
    for path in candidates:
        resolved=path.resolve()
        if not resolved.is_dir():
            continue
        if any(resolved.is_relative_to(p) for p in unique):
            continue
        unique.append(resolved)
    if not unique:
        raise AdmissionError('GAME_SAVE_ROOTS_NOT_OBSERVED')
    return [str(p) for p in unique]


def prepare_saves(root):
    executable=inside(root,'game/isaac-ng.exe')
    if file_hash(executable)!=GAME_SHA256:
        raise AdmissionError('GAME_EXECUTABLE_CHANGED')
    first_boot=windows_documents()/'My Games/Binding of Isaac Repentance'
    return SaveProtection(root).prepare(save_roots(root),first_boot_root=first_boot)


def relocate_native_environments(root):
    """Change only copied venv configuration; no package installation/network."""
    native_only()
    root=Path(root).resolve()
    base=inside(root,'runtime/python/cpython-3.10.22-windows-x86_64-none')
    if not (base/'python.exe').is_file():
        raise AdmissionError('COPIED_NATIVE_PYTHON310_BASE_REQUIRED')
    receipts=[]
    for relative in ('runtime/livetalking','runtime/tts-benchmark/omnivoice'):
        folder=inside(root,relative)
        cfg=folder/'pyvenv.cfg'
        if not cfg.is_file() or not (folder/'Scripts/python.exe').is_file():
            raise AdmissionError('COPIED_NATIVE_VENV_REQUIRED')
        before=file_hash(cfg)
        text=cfg.read_text('utf-8-sig')
        lines=[]
        for line in text.splitlines():
            key,sep,_=line.partition('=')
            if key.strip().lower() in {'home','base-executable','base-exec-prefix','base-prefix','executable'}:
                value=base/'python.exe' if key.strip().lower() in {'base-executable','executable'} else base
                line=key.strip()+' = '+str(value)
            lines.append(line)
        backup=inside(root,'operations/native-relocation')/relative.replace('/','_')/'pyvenv.cfg.original'
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():
            backup.write_bytes(cfg.read_bytes())
        cfg.write_text('\n'.join(lines)+'\n','utf-8')
        pths=[]
        for path in (folder/'Lib/site-packages').glob('*.pth'):
            content=path.read_text('utf-8-sig')
            # Absolute legacy project paths cannot leak back into this isolated
            # runtime. Relative library entries and ordinary import hooks stay.
            entries=content.splitlines()
            filtered=[]
            for line in entries:
                if re.match(r'^[A-Za-z]:[\\/]',line.strip()):
                    # Keep this installation's own paths on repeated startup.
                    # Never reintroduce a link to the live Naimei installation.
                    if not Path(line.strip()).resolve().is_relative_to(root):continue
                filtered.append(line)
            if entries!=filtered:
                target=backup.parent/path.name
                if not target.exists():target.write_bytes(path.read_bytes())
                path.write_text('\n'.join(filtered)+'\n','utf-8')
                pths.append(path.name)
        receipts.append({'environment':relative,'prior_config_sha256':before,'config_sha256':file_hash(cfg),
                         'removed_external_path_files':pths,'native_import_tested':False})
    media=inside(root,'runtime/livetalking/Lib/site-packages')
    voice=inside(root,'runtime/tts-benchmark/omnivoice/Lib/site-packages')
    version=(media/'torch/version.py').read_text('utf-8')
    if not re.search(r"__version__[^\n]*['\"]2\.9\.1\+cu128['\"]",version):
        raise AdmissionError('PINNED_EXISTING_TORCH_VERSION_REQUIRED')
    if (voice/'torch/version.py').is_file() and (voice/'torch/version.py').read_text('utf-8')!=version:
        raise AdmissionError('VOICE_TORCH_VERSION_CONFLICT')
    # .pth processing appends this directory after the voice environment's own
    # site-packages. Its OmniVoice/transformers versions retain precedence.
    shared=voice/'zz_issac_existing_torch.pth'
    shared.write_text(str(media)+'\n','utf-8')
    record={'environments':receipts,'new_packages_downloaded':0,'runtime_accepted':False,
            'voice_shared_torch':{'path':media.relative_to(root).as_posix(),
                'version_file_sha256':file_hash(media/'torch/version.py'),
                'pth_sha256':file_hash(shared),'voice_packages_precede_shared_packages':True}}
    write_json(inside(root,'.setup/native-relocation.json'),record)
    return record


def runtime_environment(root, kind):
    root=Path(root).resolve()
    env={k:v for k,v in os.environ.items() if not k.upper().startswith(('OPENAI_','ANTHROPIC_','DEEPSEEK_','AZURE_','JEV_','BOCHA_'))}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
               HF_DATASETS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',HTTP_PROXY='',HTTPS_PROXY='',ALL_PROXY='',
               NO_PROXY='127.0.0.1,localhost',TOKENIZERS_PARALLELISM='false')
    paths=[root]
    if kind in {'engine','studio','voice'}:
        for name in ('runtime/flashhead/deps310','runtime/flashhead/compile-deps310'):
            if kind!='voice':paths.insert(0,inside(root,name))
        if kind=='engine':
            compiler=inside(root,'runtime/flashhead/compile-deps310/triton')
            env['CUDA_PATH']=str(compiler/'backends/nvidia')
            env['CC']=str(compiler/'runtime/tcc/tcc.exe')
            env['TORCHINDUCTOR_USE_STATIC_CUDA_LAUNCHER']='0'
        cache=inside(root,'cache/issac/'+kind)
        cache.mkdir(parents=True,exist_ok=True)
        for key,directory in {'HF_HOME':'huggingface','TORCH_HOME':'torch','NUMBA_CACHE_DIR':'numba',
                              'TORCHINDUCTOR_CACHE_DIR':'inductor','TRITON_CACHE_DIR':'triton',
                              'TORCH_EXTENSIONS_DIR':'extensions','CUDA_CACHE_PATH':'cuda','TEMP':'tmp','TMP':'tmp'}.items():
            target=cache/directory;target.mkdir(exist_ok=True);env[key]=str(target)
        env.update(OMP_NUM_THREADS='6',MKL_NUM_THREADS='6',TORCHINDUCTOR_COMPILE_THREADS='1')
    env['PYTHONPATH']=os.pathsep.join(str(x) for x in paths)
    env['PATH']=str(inside(root,'tools/node/node-v24.22.1-win-x64'))+os.pathsep+env.get('PATH','')
    return env
