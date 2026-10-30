"""Read a public character record without changing prepared avatar paths."""
import json
import os
import re
from pathlib import Path

_SOURCE = Path(__file__).resolve()
ROOT = _SOURCE.parents[3] if _SOURCE.parent.name == 'server' else _SOURCE.parents[1]


def character_identity(character_id=None, *, root=None):
    """Select a published profile without importing another character's facts."""
    base = Path(root or ROOT).resolve()
    if character_id is None:
        character_id = os.getenv('AVATAR_CHARACTER_ID', '').strip()
        active = base / 'configs/active-character.json'
        if not character_id and active.is_file():
            character_id = json.loads(active.read_text(encoding='utf-8-sig'))['character_id']
    character_id = character_id or 'female-a'
    if not isinstance(character_id, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', character_id):
        raise ValueError('CHARACTER_ID_INVALID')
    path = (base / 'configs/characters' / (character_id + '.json')).resolve()
    if not path.is_relative_to(base):
        raise ValueError('CHARACTER_PATH_OUTSIDE_PROJECT')
    identity = json.loads(path.read_text(encoding='utf-8-sig'))
    if identity.get('id') != character_id or not identity.get('name') or not identity.get('persona_prompt'):
        raise ValueError('CHARACTER_IDENTITY_MISMATCH')
    return identity


def conversation_prompt(custom_prompt=''):
    identity = character_identity()
    custom = custom_prompt.strip()
    return identity['persona_prompt'] + ('\n' + custom if custom else '')
