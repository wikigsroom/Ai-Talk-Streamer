"""Public model identity shared by startup, control admission and channel probes."""
from .common import AdmissionError,inside,read_json


def core_model(root):
    value=read_json(inside(root,'configs/issac/core-model.json'))
    if (value.get('schema_version')!=1 or value.get('provider')!='studio-default'
            or value.get('model')!='gpt-6-luna' or value.get('protocol')!='responses'
            or value.get('base_url')!='http://43.160.221.28:9841/v1'
            or value.get('channel_source')!='issac_user_pinned_luna_api'):
        raise AdmissionError('ISAAC_MODEL_PROFILE_INVALID')
    return value


def model_identity_matches(root,value):
    expected=core_model(root)
    return value.get('model')==expected['model'] and value.get('protocol')==expected['protocol']


def current_core_channel_matches(root,value):
    expected=core_model(root)
    return (model_identity_matches(root,value) and value.get('channel_source')==expected['channel_source']
            and value.get('context_window_tokens')==expected['context_window_tokens'])
