"""Check local text resources and audio decoding; no speech or avatar generation."""
from pathlib import Path
import json,os,sys,traceback
ROOT=Path(__file__).resolve().parents[1]
repo=ROOT/'src/GPT-SoVITS'
os.chdir(repo);sys.path.insert(0,str(repo));sys.path.insert(0,str(repo/'GPT_SoVITS'))
checks=[]

def check(name,operation):
    try:extra=operation();checks.append({'name':name,'ok':True,'details':extra})
    except Exception as exc:checks.append({'name':name,'ok':False,'error':str(exc),'traceback':traceback.format_exc()})
    print(json.dumps(checks[-1],ensure_ascii=False),flush=True)

def decode():
    import torchaudio
    audio,rate=torchaudio.load(str(ROOT/'assets/demo/reference_zh.wav'))
    assert audio.ndim==2 and audio.numel()>0
    return {'sample_rate':rate,'seconds':audio.shape[-1]/rate,'channels':audio.shape[0]}

def tokens():
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained('GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large',local_files_only=True)
    return {'tokenizer':type(tokenizer).__name__,'vocab_size':tokenizer.vocab_size}

def nltk_resources():
    import nltk
    paths=['corpora/cmudict','taggers/averaged_perceptron_tagger_eng','tokenizers/punkt_tab']
    for path in paths:nltk.data.find(path)
    return paths

def language_model():
    import fasttext
    path=os.path.relpath(ROOT/'cache/fasttext/lid.176.bin')
    model=fasttext.load_model(path)
    return {'loaded':True,'model_type':type(model).__name__,'model_file':path}

def dictionary():
    import pyopenjtalk
    path=Path(pyopenjtalk.OPEN_JTALK_DICT_DIR.decode('utf-8'))
    assert path.exists() and any(path.glob('*.dic'))
    return {'directory':str(path),'files':len(list(path.iterdir()))}

check('torchaudio_decode_unicode_path',decode)
check('local_chinese_tokenizer',tokens)
check('offline_nltk_resources',nltk_resources)
check('offline_fasttext_model_load',language_model)
check('local_openjtalk_dictionary',dictionary)
value={'ok':all(item['ok'] for item in checks),'checks':checks,'synthesis_run':False,'model_forward_run':False}
(ROOT/'.setup/asset-check.result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
sys.exit(0 if value['ok'] else 1)
