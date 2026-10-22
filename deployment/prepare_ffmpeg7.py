"""Install the FFmpeg 7 shared runtime used by TorchCodec's Windows wheel."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys,urllib.error,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deployment'))
from bootstrap import api,download,request

def main():
    release=api('https://api.github.com/repos/GyanD/codexffmpeg/releases/tags/7.1.1')
    asset=next((item for item in release['assets'] if item['name']=='ffmpeg-7.1.1-full_build-shared.zip'),None)
    if asset is None:asset=next(item for item in release['assets'] if item['name']=='ffmpeg-7.1.1-full_build-shared.7z')
    digest=(asset.get('digest') or '').removeprefix('sha256:') or None
    checksum_url='https://www.gyan.dev/ffmpeg/builds/packages/'+asset['name']+'.sha256'
    if not digest:
        checksum_asset=next((item for item in release['assets'] if item['name']==asset['name']+'.sha256'),None)
        try:
            with request(checksum_asset['browser_download_url'] if checksum_asset else checksum_url) as response:
                digest=response.read().decode('utf-8-sig').split()[0]
        except urllib.error.HTTPError as exc:
            if exc.code!=404:raise
            print('Historical upstream asset has no published checksum; local SHA-256 will be recorded.',flush=True)
    archive=download(asset['browser_download_url'],ROOT/'downloads'/asset['name'],digest)
    destination=ROOT/'tools/ffmpeg7-shared';destination.mkdir(exist_ok=True)
    if not list(destination.rglob('avcodec-61.dll')):
        if archive.suffix=='.zip':
            with zipfile.ZipFile(archive) as z:z.extractall(destination)
        else:
            tar=shutil.which('tar.exe')
            if not tar:raise RuntimeError('Native tar.exe is unavailable')
            subprocess.run([tar,'-xf',str(archive),'-C',str(destination)],check=True,cwd=ROOT)
    if not list(destination.rglob('avcodec-61.dll')):raise RuntimeError('FFmpeg 7 decoder DLL was not extracted')
    data={'ok':True,'repo':'GyanD/codexffmpeg','tag':'7.1.1','asset':asset['name'],'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'upstream_digest':digest,'directory':str(destination)}
    (ROOT/'.setup/ffmpeg7-shared.tool.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(data,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
