"""Run one real local Chinese synthesis and retain its audio and measurements."""
from pathlib import Path
import datetime,io,json,time
import numpy as np
import requests,soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'outputs/验收';target.mkdir(parents=True,exist_ok=True)
text='你好，欢迎来到数字人直播间。现在的声音和人物口型，都在这台电脑上生成。'
started=time.perf_counter()
result={'ok':False,'at':datetime.datetime.now().astimezone().isoformat(),'text':text}
try:
    client=requests.Session();client.trust_env=False
    response=client.post('http://127.0.0.1:9880/tts',json={'text':text,'text_lang':'zh','ref_audio_path':str(ROOT/'assets/demo/reference_zh.wav'),'prompt_text':'希望你以后能够做的比我还好呦。','prompt_lang':'zh','media_type':'wav','streaming_mode':False,'seed':42,'text_split_method':'cut5'},timeout=(10,240))
    if response.status_code!=200:raise RuntimeError(f'HTTP {response.status_code}: {response.text[:3000]}')
    data,rate=sf.read(io.BytesIO(response.content),dtype='float32')
    path=target/'tts_zh.wav';path.write_bytes(response.content)
    result.update(ok=bool(len(data)>rate and np.max(np.abs(data))>.01),seconds=time.perf_counter()-started,audio_seconds=len(data)/rate,sample_rate=rate,peak=float(np.max(np.abs(data))),rms=float(np.sqrt(np.mean(data**2))),file=str(path),bytes=len(response.content))
except Exception as exc:
    result.update(error=str(exc),seconds=time.perf_counter()-started)
(ROOT/'.setup/tts-test.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
