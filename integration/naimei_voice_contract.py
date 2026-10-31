"""Bind Naimei to the user's existing O07/F07 choice, without redesigning voices."""
from pathlib import Path
import hashlib
import json

APPROVED_REFERENCE_SHA256 = '310c5d326dfabf0701eb255ca28e9e08f5626795d8b81d4e3b641bbac6b573a8'
APPROVED_ENGINES = {'O07': 'OmniVoice', 'F07': 'F5-TTS-v1'}
APPROVED_SEED = 2026102807


def model_path(voice_id):
    return 'models/tts-benchmark/' + ('omnivoice' if voice_id == 'O07' else 'f5')


def load_profile(root):
    root = Path(root).resolve()
    profile = json.loads((root / 'assets/naimei/live-v1/voice/profile.json').read_text('utf-8'))
    source = json.loads((root / 'configs/voices/female-a-o07-f07.json').read_text('utf-8'))
    models = json.loads((root / 'configs/resident-tts.example.json').read_text('utf-8'))
    if (profile.get('character_id') != 'naimei' or profile.get('default_voice_id') != 'O07'
            or profile.get('fallback_voice_id') != 'F07'
            or source['reference_sha256'] != APPROVED_REFERENCE_SHA256
            or models['reference_sha256'] != APPROVED_REFERENCE_SHA256
            or profile.get('reference_sha256') != APPROVED_REFERENCE_SHA256
            or profile.get('approved_source') != 'configs/voices/female-a-o07-f07.json'
            or profile.get('model_configuration') != 'configs/resident-tts.example.json'
            or profile.get('reference_text') != source['reference_text']
            or models['reference_text'] != source['reference_text']
            or profile.get('seed') != APPROVED_SEED or models['seed'] != APPROVED_SEED or source['seed'] != APPROVED_SEED
            or profile.get('engine') != 'OmniVoice' or profile.get('fallback_engine') != 'F5-TTS-v1'
            or profile.get('speed') != 1.0):
        raise ValueError('APPROVED_VOICE_CONTRACT_MISMATCH')
    voices = profile.get('voices', [])
    if len(voices) != 2 or {v['id'] for v in voices} != set(APPROVED_ENGINES):
        raise ValueError('UNAPPROVED_VOICE_SELECTION')
    pack = root / 'assets/naimei/live-v1'
    for voice in voices:
        reference = (root / voice['reference']).resolve()
        spec = models['voices'][voice['id']]
        original = next(v for v in source['voices'] if v['id'] == voice['id'])
        expected_model = model_path(voice['id'])
        expected_source = 'src/tts-benchmark/' + ('omnivoice' if voice['id'] == 'O07' else 'f5')
        if (not reference.is_relative_to(pack) or voice['sha256'] != APPROVED_REFERENCE_SHA256
                or voice['reference_text'] != source['reference_text']
                or voice['engine'] != APPROVED_ENGINES[voice['id']]
                or spec['engine'] != voice['engine']
                or voice['steps'] != spec['steps'] or voice['precision'] != spec['precision']
                or voice['steps'] != original['steps'] or voice['precision'] != original['precision']
                or spec['model'] != expected_model
                or spec['source'] != expected_source
                or (voice['id'] == 'F07' and spec['vocoder'] != 'models/tts-benchmark/vocos-mel24')):
            raise ValueError('APPROVED_VOICE_CONTRACT_MISMATCH')
        if not reference.is_file() or hashlib.sha256(reference.read_bytes()).hexdigest() != APPROVED_REFERENCE_SHA256:
            raise ValueError('APPROVED_VOICE_REFERENCE_MISMATCH')
    return profile


def route_for(profile, voice_id):
    voice = next((v for v in profile['voices'] if v['id'] == voice_id), None)
    if not voice or voice_id not in APPROVED_ENGINES:
        raise ValueError('UNAPPROVED_VOICE_SELECTION')
    ids = ['O07', 'F07'] if voice_id == 'O07' else ['F07']
    return [('tts_primary_url' if vid == 'O07' else 'tts_fallback_url', next(v for v in profile['voices'] if v['id'] == vid)) for vid in ids]


def cache_matches(record, voice, text):
    return (record.get('voice_id') == voice['id'] and record.get('engine') == voice['engine']
            and record.get('reference_sha256') == voice['sha256'] and record.get('spoken_text') == text
            and record.get('steps') == voice['steps'] and record.get('seed') == APPROVED_SEED
            and record.get('model') == model_path(voice['id'])
            and record.get('precision') == ('torch.float16' if voice['precision'] == 'FP16' else 'torch.float32'))


def worker_matches(profile, health, voice_id):
    voice = next(v for v in profile['voices'] if v['id'] == voice_id)
    precision = 'torch.float16' if voice['precision'] == 'FP16' else 'torch.float32'
    return bool(health.get('ready') and health.get('voice_id') == voice_id
                and health.get('engine') == voice['engine'] and health.get('reference_sha256') == voice['sha256']
                and health.get('steps') == voice['steps'] and health.get('seed') == profile['seed']
                and health.get('model') == model_path(voice_id)
                and health.get('precision') == precision)
