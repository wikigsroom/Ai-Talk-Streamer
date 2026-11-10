"""Probe only the explicitly approved official API of the running Naimei core."""
import argparse
import json
from pathlib import Path
import urllib.request
from .common import AdmissionError,inside,write_json
from .deployment import require_candidate
from .core_model import model_identity_matches

def probe(root):
    candidate=require_candidate(root,hardware=False)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request=urllib.request.Request('http://127.0.0.1:3104/api/dsh/probe',data=b'{}',headers={'Content-Type':'application/json'})
    with opener.open(request,timeout=60) as response:value=json.load(response)
    if not(value.get('passed') is True and model_identity_matches(root,value)):
        raise AdmissionError('ACTUAL_APPROVED_OFFICIAL_CHANNEL_PROBE_REQUIRED')
    receipt={**candidate,**value,'automatic_provider_substitution':False,'checked_against_running_core':True}
    write_json(inside(root,'state/issac-acceptance/original-channel.json'),receipt)
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=Path)
    print(json.dumps(probe(parser.parse_args().root.resolve()),ensure_ascii=False))
