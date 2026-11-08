"""User-amended recording duration, separate from unchanged quality gates."""
from .common import AdmissionError, inside, read_json


def recording_seconds(root):
    seconds=read_json(inside(root,'configs/issac/runtime.json'))['programme']['required_official_recording_seconds']
    if seconds==600:return seconds
    if seconds not in {120,300}:raise AdmissionError('USER_SELECTED_RECORDING_DURATION_REQUIRED')
    amendment=read_json(inside(root,'configs/issac/live'+str(seconds)+'.json'))
    allowed={'NM-ISSAC-EXECUTION-120S-20261109-v1','NM-ISSAC-EXECUTION-120S-20261109-v2'} if seconds==120 else {'NM-ISSAC-EXECUTION-300S-20261109-v1'}
    if (amendment.get('amendment_id') not in allowed
            or amendment.get('branch')!='issac' or amendment.get('required_official_recording_seconds')!=seconds
            or amendment.get('public_broadcast_authorized') is not False):
        raise AdmissionError('EXPLICIT_USER_DELIVERY_AMENDMENT_REQUIRED')
    return seconds


def recording_gate(root):
    return 'official_recording_'+str(recording_seconds(root))
