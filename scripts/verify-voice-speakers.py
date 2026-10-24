"""CPU CAM++ comparison of registered references and generated audition voices."""
import argparse
import datetime
import json
from pathlib import Path
import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model',type=Path,required=True,help='Existing SoulX campplus.onnx checkpoint; no downloads')
parser.add_argument('--output',type=Path,default=ROOT/'docs/evidence/voice-speakers.json')
args=parser.parse_args()
torch.set_num_threads(2)
options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
session=ort.InferenceSession(str(args.model),sess_options=options,providers=['CPUExecutionProvider'])


def embedding(path):
    array,rate=sf.read(str(path),dtype='float32',always_2d=True)
    waveform=torch.from_numpy(array.T.copy()).mean(0,keepdim=True)
    if rate!=16000:waveform=torchaudio.functional.resample(waveform,rate,16000)
    waveform=waveform/max(float(waveform.square().mean().sqrt()),1e-8)*.1
    features=kaldi.fbank(waveform,num_mel_bins=80,dither=0,sample_frequency=16000)
    features=features-features.mean(0,keepdim=True)
    vector=session.run(None,{session.get_inputs()[0].name:features.unsqueeze(0).numpy()})[0].reshape(-1)
    return vector/max(float(np.linalg.norm(vector)),1e-9)


catalog=json.loads((ROOT/'configs/voices/female-a-v1.json').read_text(encoding='utf-8'))
voices=catalog['voices'];ids=[item['voice_id'] for item in voices]
reference=np.array([embedding(ROOT/item['reference']) for item in voices])
generated=np.array([embedding(ROOT/item['repository_audio']) for item in voices])
scores=generated@reference.T
pairwise=generated@generated.T
items=[]
for index,item in enumerate(voices):
    nearest=int(np.argmax(scores[index]))
    items.append({'id':item['voice_id'],'audio_sha256':item['sha256'],'nearest_reference':ids[nearest],
                  'matches_registered_reference':nearest==index,'reference_cosines':{identity:round(float(value),5) for identity,value in zip(ids,scores[index])}})
report={'model':'SoulX campplus.onnx','provider':'CPUExecutionProvider','checked_at':datetime.datetime.now().astimezone().isoformat(),
        'reference_count':10,'generated_count':10,'matched_reference_count':sum(item['matches_registered_reference'] for item in items),
        'items':items,'generated_pairwise_cosines':{'voice_ids':ids,'values':[[round(float(value),5) for value in row] for row in pairwise]},
        'caveat':'Embedding similarity is an approximate comparison, not identity probability, proof of age, naturalness, MOS, or human listening.'}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'checked':10,'matched_reference_count':report['matched_reference_count'],'items':[{'id':item['id'],'nearest':item['nearest_reference'],'matched':item['matches_registered_reference']} for item in items]},ensure_ascii=False),flush=True)
