"""CPU-only installation imports; does not instantiate TTS or generate media."""
from pathlib import Path
import importlib,json,os,sys,time,traceback
ROOT=Path(__file__).resolve().parents[1]
name=sys.argv[1]
repo=ROOT/'src'/('LiveTalking' if name=='livetalking' else 'GPT-SoVITS')
os.chdir(repo);sys.path.insert(0,str(repo))
if name=='tts':sys.path.insert(0,str(repo/'GPT_SoVITS'))
modules={'livetalking':['torch','torchvision','torchaudio','cv2','soundfile','librosa','diffusers','transformers','aiortc','openai','pyvirtualcam','avatars.musetalk_avatar','avatars.musetalk.utils.preprocessing','app'],
         'tts':['torch','torchaudio','transformers','onnxruntime','pyopenjtalk','fast_langdetect','jieba','gradio','pytorch_lightning','ctranslate2','faster_whisper','torchcodec','TTS_infer_pack.TTS']}[name]
results=[]
for module in modules:
    started=time.perf_counter()
    try:
        loaded=importlib.import_module(module)
        record={'module':module,'ok':True,'version':getattr(loaded,'__version__',None)}
    except Exception as exc:
        record={'module':module,'ok':False,'error':str(exc),'traceback':traceback.format_exc()}
    record['seconds']=round(time.perf_counter()-started,3)
    results.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
(ROOT/'.setup'/f'{name}.imports.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
sys.exit(0 if all(r['ok'] for r in results) else 1)
