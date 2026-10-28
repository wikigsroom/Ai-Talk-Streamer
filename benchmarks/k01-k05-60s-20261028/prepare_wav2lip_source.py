"""Fetch/verify the two immutable upstream network files, never model weights."""
import base64,hashlib,json,os,urllib.request
from pathlib import Path
W=Path(__file__).resolve().parent;R=W.parent.parent;O=R/'outputs/lipsync-k01-k05-60s-20261028'
FILES={'wav2lip.py':'ae5d6919169ec497f0f0815184f5db8ba9108fbd','conv.py':'ed83da00cb199e027ef217fd360352d91a7891ff'}

def git_blob(data):return hashlib.sha1(b'blob '+str(len(data)).encode('ascii')+b'\0'+data).hexdigest()

def main():
 target=W/'wav2lip-original';target.mkdir(parents=True,exist_ok=True)
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));records=[]
 for name,expected in FILES.items():
  path=target/name;url=f'https://api.github.com/repos/Rudrabha/Wav2Lip/git/blobs/{expected}'
  if path.exists():data=path.read_bytes()
  else:
   with opener.open(urllib.request.Request(url,headers={'User-Agent':'Ai-Talk-Streamer-native-benchmark'}),timeout=30) as r:payload=json.load(r)
   if payload.get('encoding')!='base64' or payload.get('sha')!=expected:raise ValueError('Unexpected upstream blob metadata')
   data=base64.b64decode(payload['content'])
  canonical=data.replace(b'\r\n',b'\n')
  if git_blob(data)!=expected and git_blob(canonical)!=expected:raise ValueError('Upstream network source changed; refusing to overwrite or infer: '+name)
  if not path.exists():
   temp=path.with_suffix('.tmp');temp.write_bytes(data);os.replace(temp,path)
  records.append({'file':name,'git_blob_sha':expected,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'source_url':url,'line_endings_normalized_for_blob_check':git_blob(data)!=expected})
 O.mkdir(parents=True,exist_ok=True)
 (O/'wav2lip-source.json').write_text(json.dumps({'files':records,'terms_url':'https://github.com/Rudrabha/Wav2Lip#disclaimer','upstream_terms':'Personal/research/non-commercial use; upstream conditions are independent of the integration license.','network_files_unmodified':True,'model_weights_downloaded_by_this_script':False},ensure_ascii=False,indent=2),encoding='utf-8')
 print('Both original Wav2Lip network files match their frozen Git blobs; no weights downloaded.',flush=True)

if __name__=='__main__':main()
