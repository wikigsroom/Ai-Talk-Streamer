"""Add this sanitized case to the existing 4090 Vercel gallery.

The current 1,000+ source objects remain SHA references; no old gallery snapshot
or video archive replaces production. Native Python only. Explicit publishing
flags are required, and production is checked against the staged base ID.
"""
from pathlib import Path
import argparse,base64,concurrent.futures,datetime,hashlib,json,os,re,time,urllib.request,urllib.error
REPO=Path(__file__).resolve().parents[1];ROOT=REPO.parent
WORK=ROOT/'outputs/performance-20261027/publication';WORK.mkdir(parents=True,exist_ok=True)
TEAM='team_d1wMBJF3rR0HBOBvngU2bkB8';PROJECT='remote-4090-workflow-gallery'
CASE='cases/ai-talk-streamer/2026-10-27'
def api(method,path,body=None,headers=None):
 auth=json.loads((Path(os.environ['APPDATA'])/'com.vercel.cli/Data/auth.json').read_text(encoding='utf-8-sig'))
 url='https://api.vercel.com'+path+('&' if '?' in path else '?')+'teamId='+TEAM
 hdr={'Authorization':'Bearer '+auth['token']};hdr.update(headers or {})
 if isinstance(body,dict):body=json.dumps(body,ensure_ascii=False).encode();hdr['Content-Type']='application/json'
 req=urllib.request.Request(url,data=body,method=method,headers=hdr)
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=45) as r:raw=r.read()
  return json.loads(raw) if raw else {}
 except urllib.error.HTTPError as e:
  message=e.read().decode('utf-8',errors='replace').replace(auth['token'],'[redacted]');raise RuntimeError(f'HTTP {e.code}: {message[:600]}') from None
def filetree(nodes,prefix=''):
 for n in nodes:
  name=prefix+n['name']
  if n['type']=='directory':yield from filetree(n.get('children',[]),name+'/')
  else:
   if not name.startswith('src/'):raise RuntimeError('Unexpected source prefix')
   yield {'file':name[4:],'sha':n['uid']}
def prepare():
 project=api('GET','/v9/projects/'+PROJECT);base=project['targets']['production']['id']
 files=list(filetree(api('GET','/v6/deployments/'+base+'/files')))
 assert len(files)>1000,'Refuse to replace a full gallery with a small stale subset'
 home=next(f for f in files if f['file']=='index.html');raw=api('GET','/v7/deployments/'+base+'/files/'+home['sha']);original=base64.b64decode(raw['data'])
 assert hashlib.sha1(original).hexdigest()==home['sha']
 (WORK/'original-home.html').write_bytes(original)
 source=original.decode('utf-8');marker='<!-- ai-talk-streamer-frozen-20261027 -->'
 section=f'''{marker}<section id="ai-talk-streamer-case" style="background:#fff;border:1px solid #c9d8e8;border-radius:12px;padding:24px;margin:24px 0">
<div style="color:#167d8d;font-size:12px">2026-10-27 · 已实测定型 · A4090 + B3080</div>
<h2 style="margin:8px 0 12px">女A / 林知夏：双机实时数字人直播</h2>
<p>4090承担MOSS04、MuseTalk FP16 batch8与DSH/Humanity；3080承担接收与哔哩哔哩官方直播姬。720×1280、25FPS、48段动作素材。7条真实弹幕与5段官方客户端验收均完整播完。</p>
<p><b>首播放回执平均34.10秒，整句完成44.40秒；Canvas中位25.285FPS。</b>本次已下播。语音RTF为1.952；资源采样明确为下播后常驻。记忆维护因20/20日额度延后，观众CDN延迟、真实礼物未测。</p>
<p><a href="/{CASE}/report.html">打开完整交互测试报告</a> · <a href="/{CASE}/report.pdf">16页PDF</a> · <a href="/{CASE}/data/requests.csv">32条请求CSV</a> · <a href="/{CASE}/baseline.md">定型方案</a> · <a href="https://github.com/wikigsroom/Ai-Talk-Streamer">方案仓库</a></p>
<a href="/{CASE}/report.html"><img src="/{CASE}/charts/reply-timeline.png" alt="七条真实弹幕的LLM、完整语音生成与播放周期" style="width:100%;max-width:1040px;height:auto"></a>
<p style="font-size:12px;color:#68788c">统计截止官方直播姬播放回执，非观众物理出声时间。保留旧调试异常、公开直播中断及记忆整理失败记录。未新增直播录制。</p></section><!-- /ai-talk-streamer-frozen-20261027 -->'''
 if marker in source:source=re.sub(re.escape(marker)+r'.*?<!-- /ai-talk-streamer-frozen-20261027 -->',section,source,flags=re.S)
 else:
  source,n=re.subn(r'(<main(?:\s[^>]*)?>)',lambda m:m[1]+section,source,count=1)
  if n!=1:raise RuntimeError('No single main entry for case insertion')
 additions={'index.html':source.encode('utf-8')}
 report=REPO/'docs/analysis/2026-10-27'
 for path in report.rglob('*'):
  if path.is_file():additions[CASE+'/'+path.relative_to(report).as_posix()]=path.read_bytes()
 additions[CASE+'/baseline.md']=(REPO/'docs/deployment/BASELINE_A4090_B3080.md').read_bytes()
 additions[CASE+'/baseline.json']=(REPO/'configs/releases/split-a4090-b3080-v1.json').read_bytes()
 # Public baseline links must remain usable outside the source repository.
 baseline=additions[CASE+'/baseline.md'].decode('utf-8')
 for rel in re.findall(r'\]\(([^)]+)\)',baseline):
  if ':' in rel or rel.startswith('#'):continue
  resolved=(REPO/'docs/deployment'/rel).resolve();relative=resolved.relative_to(REPO).as_posix()
  baseline=baseline.replace(']('+rel+')','](https://github.com/wikigsroom/Ai-Talk-Streamer/blob/main/'+relative+')')
 additions[CASE+'/baseline.md']=baseline.encode()
 private_values=[]
 for file in [Path(os.environ['APPDATA'])/'com.vercel.cli/Data/auth.json',REPO/'configs/channel.env']:
  if file.exists():
   text=file.read_text(encoding='utf-8-sig')
   if file.suffix=='.json':private_values.extend(v for k,v in json.loads(text).items() if 'token' in k.lower() and isinstance(v,str))
   else:private_values.extend(s.split('=',1)[1].strip().strip('"\'') for s in text.splitlines() if '=' in s and any(k in s.split('=',1)[0].lower() for k in ['key','token']))
 manifest=[];local=WORK/'new-files';local.mkdir(exist_ok=True)
 for name,content in additions.items():
  if Path(name).suffix in ['.html','.md','.json','.csv','.svg']:
   text=content.decode('utf-8-sig')
   if any(v and len(v)>12 and v in text for v in private_values) or re.search(r'sk-[a-zA-Z0-9]{24,}|SESSDATA=|bili_jct=',text):raise RuntimeError('Credential found in public case')
  destination=local/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(content)
  manifest.append({'file':name,'sha':hashlib.sha1(content).hexdigest(),'size':len(content),'sha256':hashlib.sha256(content).hexdigest()})
 merged={f['file']:f for f in files};merged.update({m['file']:{k:m[k] for k in ['file','sha','size']} for m in manifest})
 plan={'base_production_id':base,'project_id':project['id'],'project':PROJECT,'prepared_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'preserved_source_files':len(files)-1,'existing_source_count':len(files),'total_source_files':len(merged),'new_files':manifest,'files':list(merged.values()),'public_url':'https://4090.sid.mom/'+CASE+'/report.html'}
 (WORK/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in plan.items() if k not in ['files','new_files']},ensure_ascii=False),flush=True)
def publish(production=False):
 plan=json.loads((WORK/'plan.json').read_text(encoding='utf-8'));current=api('GET','/v9/projects/'+PROJECT)
 if current['targets']['production']['id']!=plan['base_production_id']:raise RuntimeError('Production changed; re-prepare against latest source, do not overwrite')
 def upload(row):
  content=(WORK/'new-files'/row['file']).read_bytes()
  api('POST','/v2/files',content,{'Content-Type':'application/octet-stream','x-vercel-digest':row['sha']});return row['file']
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  uploaded=list(pool.map(upload,plan['new_files']))
 payload={'name':PROJECT,'project':plan['project_id'],'files':plan['files'],'projectSettings':{'framework':None,'buildCommand':'','installCommand':'','outputDirectory':'.'},'meta':{'case':'ai-talk-streamer-20261027','release':'split-a4090-b3080-v1.0.0','preservedProduction':plan['base_production_id'],'measuredPublicReplies':'7'}}
 if production:
  preview=json.loads((WORK/'preview-status.json').read_text(encoding='utf-8'))
  if preview.get('readyState')!='READY':raise RuntimeError('Preview must be READY before production')
  payload['target']='production'
 kind='production' if production else 'preview';deployment=api('POST','/v13/deployments',payload)
 receipt={k:deployment.get(k) for k in ['id','url','readyState','createdAt','alias','errorCode','errorMessage']};receipt.update({'kind':kind,'base_production_id':plan['base_production_id'],'uploaded_files':len(uploaded),'total_source_files':len(plan['files'])})
 (WORK/(kind+'-receipt.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(receipt,ensure_ascii=False),flush=True)
def status(kind):
 receipt=json.loads((WORK/(kind+'-receipt.json')).read_text(encoding='utf-8'));d=api('GET','/v13/deployments/'+receipt['id']);saved={k:d.get(k) for k in ['id','url','readyState','alias','errorCode','errorMessage']};(WORK/(kind+'-status.json')).write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(saved,ensure_ascii=False),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--preview',action='store_true');g.add_argument('--production',action='store_true');g.add_argument('--status',choices=['preview','production']);a=p.parse_args()
 if a.prepare:prepare()
 elif a.status:status(a.status)
 else:publish(a.production)
