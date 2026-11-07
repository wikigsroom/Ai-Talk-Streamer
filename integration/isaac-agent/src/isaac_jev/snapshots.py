"""Publish complete observations without exposing a truncated live file."""
import json
from pathlib import Path
import time
import uuid


def publish_json(path: Path, value, *, timeout: float = .25) -> None:
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        deadline=time.monotonic()+timeout
        while True:
            try:
                temporary.replace(path)
                return
            except PermissionError:
                # Windows readers may briefly deny delete sharing. Retain the
                # last complete observation while retrying the atomic rename.
                if time.monotonic()>=deadline:
                    raise
                time.sleep(.005)
    finally:
        temporary.unlink(missing_ok=True)
