"""Resume local H3 renders, encode portrait clips, and keep honest review states."""
from pathlib import Path
import argparse,datetime,json,os,subprocess,time,traceback
from urllib.request import Request,build_opener,ProxyHandler
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'configs/vertical/materials';OUT=ROOT/'outputs/vertical/materials'
OUT.mkdir(parents=True,exist_ok=True);(OUT/'review').mkdir(exist_ok=True)
STATE=ROOT/'.setup/material-library-progress.json'
opener=build_opener(ProxyHandler({}))
parser=argparse.ArgumentParser();parser.add_argument('--ids',nargs='*');args=parser.parse_args()
catalog=json.loads((CONFIG/'catalog.json').read_text(encoding='utf-8'))
items=[x for x in catalog['items'] if not args.ids or x['id'] in args.ids]
if not items:raise RuntimeError('No requested catalog items')
ffmpeg=next((ROOT/'tools/ffmpeg').rglob('ffmpeg.exe'));ffprobe=ffmpeg.with_name('ffprobe.exe')
state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'items':{}}
state.update(status='running',pid=os.getpid(),target=len(catalog['items']),started_at=datetime.datetime.now().astimezone().isoformat())

def save():
 state['updated_at']=datetime.datetime.now().astimezone().isoformat()
 state['generated_count']=sum(x.get('status')=='generated_awaiting_review' for x in state['items'].values())
 temporary=STATE.with_suffix('.tmp');temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(STATE)

def api(endpoint,data=None):
 request=Request('http://127.0.0.1:8188/'+endpoint,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with opener.open(request,timeout=45) as response:return json.load(response)

def encode_and_review(item):
 name=item['id'];folder=OUT/(name+'_frames');frames=sorted(folder.glob('frame*.png'))
 if len(frames)!=192:raise RuntimeError(f'{name}: expected 192 generated frames, received {len(frames)}')
 target=OUT/(name+'.mp4')
 command=[str(ffmpeg),'-v','error','-y','-framerate','24','-i',str(folder/'frame%06d.png'),'-vf','scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=25','-an','-c:v','libx264','-threads','6','-preset','fast','-crf','16','-pix_fmt','yuv420p','-movflags','+faststart',str(target)]
 subprocess.run(command,check=True,timeout=180)
 metadata=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries','stream=width,height,nb_frames,r_frame_rate:format=duration','-of','json',str(target)],text=True))
 video=metadata['streams'][0]
 if (video['width'],video['height'])!=(720,1280) or int(video['nb_frames'])!=200:raise RuntimeError('Portrait encode verification failed')
 sample=[0,24,48,72,96,120,144,188]
 sheet=Image.new('RGB',(960,904),'#edf0f3');draw=ImageDraw.Draw(sheet)
 font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
 for i,index in enumerate(sample):
  with Image.open(frames[index]) as im:
   image=im.convert('RGB');image.thumbnail((240,427),Image.Resampling.LANCZOS)
   x=(i%4)*240;y=(i//4)*452
   sheet.paste(image,(x,y+25));draw.text((x+5,y+4),f'{name[:3]} / {index/24:.2f}s',font=font,fill='#1b2838')
 review=OUT/'review'/(name+'.jpg');sheet.save(review,quality=94)
 return {'status':'generated_awaiting_review','video':str(target.relative_to(ROOT)).replace('\\','/'),'review':str(review.relative_to(ROOT)).replace('\\','/'),'media':metadata,'bytes':target.stat().st_size,'title':item['title'],'category':item['category']}

failed=False
try:
 for item in items:
  name=item['id'];old=state['items'].get(name,{})
  reviews_path=CONFIG/'reviews.json'
  reviews=json.loads(reviews_path.read_text(encoding='utf-8')) if reviews_path.exists() else {}
  if reviews.get(name,{}).get('accepted') and (ROOT/item['source_video']).is_file():
   print('REUSE REVIEWED MATERIAL '+name,flush=True);continue
  if old.get('status')=='generated_awaiting_review' and (ROOT/old['video']).exists():continue
  if (ROOT/'.setup/materials-stop.request').exists():state['status']='stopped';break
  state['current']=name;save();print('START '+name,flush=True)
  try:
   prompt_id=old.get('prompt_id')
   history=api('history/'+prompt_id) if prompt_id else {}
   queue=api('queue')
   queued={x[1] for x in queue['queue_running']+queue['queue_pending']}
   if not prompt_id or (not history and prompt_id not in queued):
    graph=json.loads((CONFIG/(name+'.api.json')).read_text(encoding='utf-8').replace('${PROJECT_ROOT}', ROOT.as_posix()))
    receipt=api('prompt',{'prompt':graph,'client_id':'vertical-material-library-20261022'})
    prompt_id=receipt['prompt_id'];state['items'][name]={'status':'rendering','prompt_id':prompt_id,'submitted_at':time.time()};save()
   started=time.monotonic()
   while True:
    history=api('history/'+prompt_id)
    if history:break
    if time.monotonic()-started>2400:raise RuntimeError('Local render exceeded 40 minutes; existing job was left intact')
    state['elapsed_current_seconds']=round(time.monotonic()-started);save();time.sleep(5)
   record=history[prompt_id]
   (CONFIG/(name+'.history.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
   if record.get('status',{}).get('status_str')!='success':
    errors=[m[1].get('exception_message','unknown') for m in record.get('status',{}).get('messages',[]) if m[0]=='execution_error']
    raise RuntimeError('H3 render failed: '+'; '.join(errors))
   state['items'][name]={'prompt_id':prompt_id,**encode_and_review(item)};save()
   print('GENERATED '+name+' awaiting visual review',flush=True)
  except Exception:
   failed=True;state['items'][name]={**state['items'].get(name,{}),'status':'failed','error':traceback.format_exc()};save();print(traceback.format_exc(),flush=True)
   # Avoid submitting a large queue behind an unresolved failure.
   state['status']='failed';break
 else:state['status']='generated_awaiting_review' if not failed else 'failed'
except Exception:
 failed=True;state['status']='failed';state['error']=traceback.format_exc();print(state['error'],flush=True)
finally:
 save()
 queue=api('queue')
 if not queue['queue_running'] and not queue['queue_pending']:
  request=Request('http://127.0.0.1:8188/free',data=json.dumps({'unload_models':True,'free_memory':True}).encode(),headers={'Content-Type':'application/json'})
  try:
   with opener.open(request,timeout=30) as response:response.read()
  except Exception:pass
 print(json.dumps({'status':state['status'],'generated':state['generated_count'],'target':state['target']},ensure_ascii=False),flush=True)
raise SystemExit(1 if failed else 0)
