"""Pin Naimei to its approved merged reference; preserve legacy release validation."""
from pathlib import Path
import hashlib
import json

APPROVED_REFERENCE_SHA256 = '310c5d326dfabf0701eb255ca28e9e08f5626795d8b81d4e3b641bbac6b573a8'
APPROVED_ENGINES = {'O07': 'OmniVoice', 'F07': 'F5-TTS-v1'}
APPROVED_SEED = 2026102807
MERGED_VOICE_ID = 'NCM01'
MERGED_REFERENCE_SHA256 = '73ef5e49c20d2fad0cbf5911d6ff1b351836a0116635a1e6439fae4e195a6908'
MERGED_FREEZE_ID = 'NM-VOICE-FINAL-20261106-v1'
MERGED_PROFILE = 'assets/naimei/voice-final-v1/profile.json'
MERGED_REFERENCE_TEXT_SHA256 = '5bfdd017e75c2bb8e4b274cfc7955db2171b7f0c397210b5f91f03bb618a0613'


def model_path(voice_id):
    if voice_id in {'O07', MERGED_VOICE_ID}:
        return 'models/tts-benchmark/omnivoice'
    if voice_id == 'F07':
        return 'models/tts-benchmark/f5'
    raise ValueError('UNAPPROVED_VOICE_SELECTION')


def load_legacy_profile(root):
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


def load_profile(root, *, require_private=True):
    root = Path(root).resolve()
    runtime = root / 'configs/naimei/live-runtime.json'
    if runtime.exists() and json.loads(runtime.read_text('utf-8')).get('voice_profile') != MERGED_PROFILE:
        raise ValueError('APPROVED_VOICE_PROFILE_POINTER_MISMATCH')
    profile = json.loads((root / MERGED_PROFILE).read_text('utf-8'))
    expected_reference = 'assets/naimei/voice-final-v1/private/reference.wav'
    expected_transcript = 'assets/naimei/voice-final-v1/private/reference.txt'
    if (profile.get('character_id') != 'naimei' or profile.get('freeze_id') != MERGED_FREEZE_ID
            or profile.get('default_voice_id') != MERGED_VOICE_ID or profile.get('fallback_voice_id') is not None
            or profile.get('automatic_fallback') is not False or profile.get('fallback_engine') is not None
            or profile.get('engine') != 'OmniVoice' or profile.get('seed') != APPROVED_SEED
            or profile.get('steps') != 32 or profile.get('speed') != 1.0 or profile.get('sample_rate') != 24000
            or profile.get('reference_preprocess_prompt') is not False
            or profile.get('reference_sha256') != MERGED_REFERENCE_SHA256
            or 'reference_text' in profile or profile.get('reference_text_file') != expected_transcript
            or profile.get('reference_text_sha256') != MERGED_REFERENCE_TEXT_SHA256
            or profile.get('approved_source') != 'assets/naimei/voice-final-v1/manifest.json'
            or profile.get('model_configuration') != 'configs/naimei/voice-models.json'
            or not profile.get('voice_frozen') or not profile.get('naimei_audition_confirmed')):
        raise ValueError('APPROVED_VOICE_CONTRACT_MISMATCH')
    voices = profile.get('voices', [])
    if len(voices) != 1 or voices[0].get('id') != MERGED_VOICE_ID:
        raise ValueError('UNAPPROVED_VOICE_SELECTION')
    voice = voices[0]
    if (voice.get('reference') != expected_reference or voice.get('sha256') != MERGED_REFERENCE_SHA256
            or 'reference_text' in voice or voice.get('reference_text_file') != expected_transcript
            or voice.get('reference_text_sha256') != MERGED_REFERENCE_TEXT_SHA256 or voice.get('engine') != 'OmniVoice'
            or voice.get('precision') != 'FP16' or voice.get('steps') != 32
            or voice.get('preprocess_prompt') is not False):
        raise ValueError('APPROVED_VOICE_CONTRACT_MISMATCH')
    models = json.loads((root / profile['model_configuration']).read_text('utf-8'))
    expected_spec = {'engine': 'OmniVoice', 'python': 'runtime/tts-benchmark/omnivoice/Scripts/python.exe',
        'source': 'src/tts-benchmark/omnivoice', 'model': model_path(MERGED_VOICE_ID),
        'port': 9891, 'precision': 'FP16', 'steps': 32}
    if (models.get('voices') != {MERGED_VOICE_ID: expected_spec}
            or models.get('reference_sha256') != MERGED_REFERENCE_SHA256
            or 'reference_text' in models or models.get('reference_text_file') != expected_transcript
            or models.get('reference_text_sha256') != MERGED_REFERENCE_TEXT_SHA256
            or models.get('reference_audio') != expected_reference or models.get('seed') != APPROVED_SEED
            or models.get('reference_preprocess_prompt') is not False or models.get('automatic_fallback') is not False):
        raise ValueError('APPROVED_VOICE_CONTRACT_MISMATCH')
    freeze = json.loads((root / profile['approved_source']).read_text('utf-8'))
    if (freeze.get('status') != 'frozen' or freeze.get('freeze_id') != MERGED_FREEZE_ID
            or freeze.get('voice_id') != MERGED_VOICE_ID or not freeze.get('voice_identity_accepted')
            or freeze.get('approval', {}).get('by') != 'user'):
        raise ValueError('APPROVED_VOICE_FREEZE_MISMATCH')
    entries = freeze.get('files', [])
    names = {item['path'] for item in entries}
    expected_public = {MERGED_PROFILE, profile['model_configuration'],
        'assets/naimei/voice-final-v1/provenance.json', 'assets/naimei/voice-final-v1/approved-audition.wav',
        *(f'assets/naimei/voice-final-v1/samples/NCM01-S0{i}.wav' for i in range(1, 7))}
    if len(names) != len(entries) or names != expected_public:
        raise ValueError('APPROVED_VOICE_FREEZE_MISMATCH')
    for item in entries:
        path = (root / item['path']).resolve()
        if path.is_relative_to(root / 'assets/naimei/voice-final-v1/private'):
            raise ValueError('PRIVATE_REFERENCE_IN_REPOSITORY_FREEZE')
        in_pack = path.is_relative_to(root / 'assets/naimei/voice-final-v1')
        if not in_pack and path != root / 'configs/naimei/voice-models.json':
            raise ValueError('APPROVED_VOICE_FREEZE_PATH_MISMATCH')
        if not path.is_file() or path.stat().st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('APPROVED_VOICE_FREEZE_FILE_MISMATCH:' + item['path'])
    private = {item['path']: item for item in freeze.get('private_files', []) if item.get('required_for_runtime')}
    if (set(private) != {expected_reference, expected_transcript}
            or private[expected_reference]['sha256'] != MERGED_REFERENCE_SHA256
            or private[expected_transcript]['sha256'] != MERGED_REFERENCE_TEXT_SHA256
            or freeze.get('repository_contains_reference_audio') is not False):
        raise ValueError('APPROVED_PRIVATE_REFERENCE_CONTRACT_MISMATCH')
    available = True
    for name, item in private.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root / 'assets/naimei/voice-final-v1/private'):
            raise ValueError('APPROVED_PRIVATE_REFERENCE_PATH_MISMATCH')
        if not path.is_file():
            available = False
            if require_private:
                raise ValueError('APPROVED_PRIVATE_REFERENCE_MISSING:' + name)
        elif path.stat().st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('APPROVED_PRIVATE_REFERENCE_MISMATCH:' + name)
    profile['private_reference_available'] = available
    if available:
        transcript = (root / expected_transcript).read_text('utf-8').rstrip('\r\n')
        profile['reference_text'] = voice['reference_text'] = transcript
    return profile


def voice_for_engine(profile, engine):
    voice = next((v for v in profile['voices'] if v['engine'] == engine), None)
    if voice is None:
        raise ValueError('NO_APPROVED_VOICE_FOR_ENGINE:' + engine)
    return voice


def route_for(profile, voice_id):
    voice = next((v for v in profile['voices'] if v['id'] == voice_id), None)
    if not voice or voice_id not in {*APPROVED_ENGINES, MERGED_VOICE_ID}:
        raise ValueError('UNAPPROVED_VOICE_SELECTION')
    ids = [voice_id]
    if voice_id == profile['default_voice_id'] and profile.get('fallback_voice_id'):
        ids.append(profile['fallback_voice_id'])
    return [('tts_primary_url' if vid == profile['default_voice_id'] else 'tts_fallback_url', next(v for v in profile['voices'] if v['id'] == vid)) for vid in ids]


def cache_matches(record, voice, text):
    if voice['id'] == MERGED_VOICE_ID and (record.get('reference_preprocess_prompt') is not False
            or record.get('voice_freeze_id') != MERGED_FREEZE_ID):
        return False
    return (record.get('voice_id') == voice['id'] and record.get('engine') == voice['engine']
            and record.get('reference_sha256') == voice['sha256'] and record.get('spoken_text') == text
            and record.get('steps') == voice['steps'] and record.get('seed') == APPROVED_SEED
            and record.get('model') == model_path(voice['id'])
            and record.get('precision') == ('torch.float16' if voice['precision'] == 'FP16' else 'torch.float32'))


def worker_matches(profile, health, voice_id):
    voice = next((v for v in profile['voices'] if v['id'] == voice_id), None)
    if voice is None:
        return False
    if voice_id == MERGED_VOICE_ID and (health.get('reference_preprocess_prompt') is not False
            or health.get('voice_freeze_id') != MERGED_FREEZE_ID):
        return False
    precision = 'torch.float16' if voice['precision'] == 'FP16' else 'torch.float32'
    return bool(health.get('ready') and health.get('voice_id') == voice_id
                and health.get('engine') == voice['engine'] and health.get('reference_sha256') == voice['sha256']
                and health.get('steps') == voice['steps'] and health.get('seed') == profile['seed']
                and health.get('model') == model_path(voice_id)
                and health.get('precision') == precision)
