"""Make project FFmpeg shared DLLs visible to native Python extensions on Windows."""
from pathlib import Path
import os
_avatar_dll_handles=[]
if os.name=='nt' and hasattr(os,'add_dll_directory'):
    _avatar_root=Path(__file__).resolve().parents[1]
    for _avatar_name in ('ffmpeg7-shared','ffmpeg-shared'):
        _avatar_shared=_avatar_root/'tools'/_avatar_name
        if _avatar_shared.exists():
            for _avatar_dll in _avatar_shared.rglob('avcodec-*.dll'):
                _avatar_dll_handles.append(os.add_dll_directory(str(_avatar_dll.parent)))
                break
