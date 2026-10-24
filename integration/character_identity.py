"""Read a public character record without changing prepared avatar paths."""
import json
from pathlib import Path

_SOURCE = Path(__file__).resolve()
ROOT = _SOURCE.parents[3] if _SOURCE.parent.name == 'server' else _SOURCE.parents[1]


def character_identity():
    return json.loads((ROOT / 'configs/characters/female-a.json').read_text(encoding='utf-8'))


def conversation_prompt(custom_prompt=''):
    identity = character_identity()
    custom = custom_prompt.strip()
    return identity['persona_prompt'] + ('\n' + custom if custom else '')
