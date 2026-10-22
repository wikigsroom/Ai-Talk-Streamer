"""Fill native decoder DLL and offline language-model assets used at runtime."""
from pathlib import Path
import hashlib,json,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deployment'))
from bootstrap import api,tool_release
from download_models import download,get

def main():
    release=api('https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest')
    candidates=[a['name'] for a in release['assets'] if 'win64-gpl-shared' in a['name'] and any(x in a['name'] for x in ['ffmpeg-n7.1-','ffmpeg-n8.0-','ffmpeg-n8.1-'])]
    if not candidates:raise RuntimeError('No supported shared FFmpeg runtime found')
    selected=sorted(candidates)[0]
    tool_release('ffmpeg-shared','BtbN/FFmpeg-Builds',lambda name:name==selected)
    result=download({'url':'https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin','local_path':'cache/fasttext/lid.176.bin','role':'offline language identification'})
    if not result['ok']:raise RuntimeError('FastText model download failed')
    md5=hashlib.md5((ROOT/result['local_path']).read_bytes()).hexdigest()
    if md5!='01810bc59c6a3d2b79c79e6336612f65':raise RuntimeError('FastText upstream MD5 mismatch')
    with get('https://api.github.com/repos/nltk/nltk_data/commits/gh-pages') as response:revision=json.load(response)['sha']
    results=[result]
    for kind,name in [('taggers','averaged_perceptron_tagger_eng'),('taggers','averaged_perceptron_tagger'),('tokenizers','punkt_tab'),('corpora','cmudict')]:
        item=download({'repo':'nltk/nltk_data','revision':revision,'url':f'https://raw.githubusercontent.com/nltk/nltk_data/{revision}/packages/{kind}/{name}.zip','local_path':f'downloads/nltk/{name}.zip','role':'offline text resource'})
        if not item['ok']:raise RuntimeError('NLTK resource download failed: '+name)
        destination=ROOT/'cache/nltk_data'/kind;destination.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(ROOT/item['local_path']) as z:z.extractall(destination)
        results.append(item)
    (ROOT/'.setup/runtime-assets.result.json').write_text(json.dumps({'ok':True,'shared_ffmpeg':selected,'models':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print('RUNTIME_ASSETS_READY',flush=True)

if __name__=='__main__':main()
