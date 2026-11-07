"""Atomic JSON publication tolerating Windows readers without delete sharing."""
import json
from pathlib import Path
import time
import uuid


def atomic_json(path,payload,timeout=3):
    path=Path(path)
    temporary=path.with_name(path.stem+'-'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(payload,ensure_ascii=True),encoding='utf-8')
    deadline=time.monotonic()+timeout
    try:
        while True:
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if time.monotonic()>=deadline: raise
                time.sleep(.01)
    finally:
        temporary.unlink(missing_ok=True)
