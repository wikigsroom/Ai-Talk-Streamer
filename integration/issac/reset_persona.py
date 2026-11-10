"""Explicit, stopped-stack reset authorized by the 2026-11-10 user amendment.

No game, save, asset, voice, shared branch or private API credential is deleted.
Only this branch's active conversation/memory/mood store is cleared.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import socket

from .common import AdmissionError,file_hash,read_json,write_json


def reset(root):
    root=Path(root).resolve()
    if root!=Path('C:/dev/虚拟数字人直播/issac').resolve():
        raise AdmissionError('PINNED_ISAAC_INSTALLATION_REQUIRED')
    target=read_json(root/'configs/deployment-target.json')
    if target['target']!='issac-rtx4090' or target['branch']!='issac':
        raise AdmissionError('ISOLATED_ISAAC_BRANCH_REQUIRED')
    for port in (3104,3103,9534,9541):
        with socket.socket() as sock:
            sock.settimeout(.3)
            if sock.connect_ex(('127.0.0.1',port))==0:
                raise AdmissionError('STOP_OWNED_STACK_BEFORE_MEMORY_RESET')
    state=(root/'state/issac-stream').resolve()
    if state.parent!=root/'state' or state.name!='issac-stream' or state.is_symlink():
        raise AdmissionError('EXACT_MEMORY_DIRECTORY_REQUIRED')
    channel=root/'private/issac/channel.env'
    values=channel.read_text('utf-8-sig')
    updated,count=re.subn(r'^AVATAR_LLM_MODEL=.*$', 'AVATAR_LLM_MODEL=gpt-6.1-sol',values,flags=re.M)
    if count!=1:raise AdmissionError('ONE_EXISTING_PRIVATE_MODEL_FIELD_REQUIRED')
    persona=root/'configs/characters/naimei.json'
    extensions=root/'configs/naimei/dsh-extensions.json'
    before={'persona_sha256':file_hash(persona),'extensions_sha256':file_hash(extensions)}
    if state.exists():shutil.rmtree(state)
    state.mkdir(parents=True)
    channel.write_text(updated,'utf8')
    receipt={'active_memory_cleared':True,'old_conversations_loaded':False,
        'model':'gpt-6.1-sol','protocol':'responses','channel_address_and_key_preserved':True,
        'complete_original_persona_republished_on_start':True,'seven_extensions_reload_on_start':True,
        **before,'public_stream_started':False}
    write_json(root/'state/issac-acceptance/persona-reset-20261110.json',receipt)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',required=True)
    print(json.dumps(reset(parser.parse_args().root),ensure_ascii=False))
