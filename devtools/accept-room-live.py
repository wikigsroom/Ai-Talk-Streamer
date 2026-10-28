from pathlib import Path
import requests,json,time,threading,uuid,datetime,io,wave,subprocess
r=Path(__file__).resolve().parents[1];out=r/'outputs/room-admin'/('acceptance-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True,exist_ok=False)
(r/'outputs/room-admin/latest-acceptance.json').write_text(json.dumps({'result':(out/'result.json').relative_to(r).as_posix()}),encoding='utf8')
s=requests.Session();s.trust_env=False;base='http://127.0.0.1:8020'
report={'ok':False,'scope':'A4090 real O07/F07 inference to the existing B3080 official Livehime browser source; local session and synthetic events only','public_broadcast_started':False,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cases':[],'samples':[],'checks':{}}
stop=threading.Event();owned=False;original=None;voice='O07'
def api(path,body=None,timeout=100):
 q=s.request('GET'if body is None else'POST',base+'/api/dsh'+path,json=body,timeout=timeout);d=q.json()
 if not q.ok:raise RuntimeError(str(q.status_code)+':'+d.get('error','REQUEST_FAILED'))
 return d
def studio(path,body=None):
 q=s.request('GET'if body is None else'POST',base+'/api/studio/'+path,json=body,timeout=20);q.raise_for_status();return q.json()
def save():(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
def config(patch):
 st=api('/room/state');return api('/room/config',{'expected_revision':st['revision'],'patch':patch})
def sample():
 client=requests.Session();client.trust_env=False
 while not stop.is_set():
  try:
   a=client.get(base+'/receiver/status',timeout=5).json();b=client.get(base+'/api/dsh/room/state',timeout=5).json()
   report['samples'].append({'at':round(time.time(),3),'fps':a.get('player_fps'),'stream':a.get('player_metrics',{}),'mixer':b.get('player'),'active':b.get('active')})
  except Exception as e:report['samples'].append({'at':round(time.time(),3),'error':type(e).__name__})
  stop.wait(.6)
 client.close()
def speech(case,text,mode='echo'):
 start=time.time();ack=api('/room/speak',{'text':text,'mode':mode,'idempotency_key':'room-'+uuid.uuid4().hex});rid=ack['request_id']
 until=time.monotonic()+180
 while time.monotonic()<until:
  row=api('/requests/'+rid)
  if row['status']=='COMPLETED':break
  if row['status']in ['FAILED','EXPIRED','CANCELLED','INTERRUPTED','UNKNOWN','REJECTED']:raise RuntimeError(case+':'+row['status'])
  time.sleep(.35)
 else:raise RuntimeError(case+':TIMEOUT')
 report['cases'].append({'id':case,'request_id':rid,'text':text,'status':row['status'],'elapsed_ms':round((time.time()-start)*1000),'voice':studio('status')['voice']['voice_id']});save();return rid
try:
 save();assert api('/status')['broadcast']is None
 original=api('/room/state');platform=api('/platforms/config');original_interaction=platform['interaction'];voice=studio('status')['voice']['voice_id']
 player=api('/platforms/status')['output_player'];assert player['connected']and player['receiver_id']=='receiver-3080'
 receiver=s.get(base+'/receiver/status',timeout=10).json();assert receiver['active_connections']==1
 assert original['player']and original['player']['connected'],'New room source must be refreshed in official client'
 report['initial_receiver']=receiver.get('player_metrics',{})
 # Exercise a 3 MB+ raw upload through B's 2 MiB-default application and A proxy.
 track=original['tracks'][0];raw=s.get(base+track['url'],timeout=15).content
 with wave.open(io.BytesIO(raw),'rb')as wav:params=wav.getparams();pcm=wav.readframes(wav.getnframes())
 temp=io.BytesIO()
 with wave.open(temp,'wb')as wav:wav.setparams(params);wav.writeframes(pcm*3)
 data=temp.getvalue();q=s.post(base+'/api/dsh/room/tracks/upload?name=room-acceptance-loop.wav',data=data,headers={'Content-Type':'application/octet-stream'},timeout=45);q.raise_for_status();uploaded=q.json()
 report['checks']['large_upload']={'bytes':len(data),'duration':uploaded['duration'],'track_id':uploaded['id']}
 q=s.get(base+uploaded['url'],headers={'Range':'bytes=0-43'},timeout=10);assert q.status_code==206 and len(q.content)==44
 report['checks']['range_forwarding']=True
 api('/room/tracks/delete',{'id':uploaded['id']})
 api('/platforms/config',{'interaction':{'mode':'echo'}});api('/platforms/bilibili/start',{});owned=True
 config({'audio':{'music_volume':.22,'muted':False,'ducking':True},'overlay':{'theme':'daylight','embedded':True}})
 api('/room/music',{'action':'play','track_id':'daylight-notes'})
 monitor=threading.Thread(target=sample,daemon=True);monitor.start()
 speech('R1-O07-BGM','大家好，我是林知夏。欢迎来到我的日光宿舍，一起聊聊今天开心的小事吧。')
 assert any((x.get('mixer')or{}).get('music_playing')for x in report['samples']),'BGM was not playing in official client'
 config({'filters':{'preset':'warm','brightness':1.02,'contrast':.97,'saturation':.97,'warmth':.16,'softness':0,'vignette':.1},'overlay':{'theme':'paper'}})
 api('/room/messages',{'action':'create','text':'本地验收：今天也一起，把平凡的小事过得有趣。','nickname':'导播验收','test':True,'feature':True})
 speech('R2-BOARD-FILTER','看到你的留言啦。有时候，一杯喜欢的饮料和朋友的一句问候，就能让一天变得很好。')
 # Same normal event normalization and routing path used by the live collector.
 event={'type':'comment','event_id':'room-admin-'+uuid.uuid4().hex,'room_id':'595139','user_id':'local-room-validator','nickname':'本地装修验收','text':'知夏，测试一下弹幕互动。今天也要好好休息，照顾自己。','timestamp':int(time.time()*1000),'test':True}
 start=time.time();ack=api('/platforms/events',{'platform':'bilibili','event':event});key=ack['results'][0]['event_key']
 for _ in range(240):
  row=next((e for e in api('/platforms/status')['events']if e['event_key']==key),{})
  if row.get('status')=='COMPLETED':break
  if row.get('status')in ['FAILED','IGNORED','EXPIRED','DROPPED','CANCELLED','INTERRUPTED']:raise RuntimeError('R3:'+str(row))
  time.sleep(.4)
 else:raise RuntimeError('R3:TIMEOUT')
 report['cases'].append({'id':'R3-NORMAL-COMMENT-ROUTING','request_id':row['request_id'],'status':row['status'],'text':event['text'],'elapsed_ms':round((time.time()-start)*1000),'voice':'O07'});save()
 api('/room/test-event',{'type':'gift'});studio('voice',{'voice_id':'F07'})
 speech('R4-F07-GIFT','谢谢你送来的小星星。这是本地礼物提醒测试，也祝你今天有很多小小的幸运。')
 studio('voice',{'voice_id':'O07'})
 api('/room/agent',{'action':'ask','text':'这是导播私聊验收。请用一句自然的话介绍你自己，再提一个适合日光宿舍的轻松聊天话题。不要声称已经操作任何后台控件。'})
 for _ in range(240):
  state=api('/room/state');job=state['agent']['job']
  if job['status']=='COMPLETED':break
  if job['status']in ['FAILED','CANCELLED']:raise RuntimeError('PRIVATE_AGENT:'+str(job))
  time.sleep(.5)
 else:raise RuntimeError('PRIVATE_AGENT:TIMEOUT')
 history=api('/room/agent')['history'];reply=next(x['text']for x in reversed(history)if x['role']=='assistant')
 report['checks']['private_agent']={'job_id':job['id'],'elapsed_ms':job['finished_at']-job['started_at'],'reply':reply,'auto_spoken':False}
 speech('R5-EXPLICIT-AGENT-TO-PROGRAM',reply[:140])
 report['checks']['ducking_observed']=any((x.get('mixer')or{}).get('ducked')and(x.get('mixer')or{}).get('music_gain',1)<.15 for x in report['samples'])
 assert report['checks']['ducking_observed'],'No real program speech ducking observed'
 report['final_receiver']=s.get(base+'/receiver/status',timeout=10).json().get('player_metrics',{})
 report['continuity_deltas']={k:report['final_receiver'].get(k,0)-report['initial_receiver'].get(k,0)for k in ['audio_underruns','missing_packets','decode_errors']}
 fps=[x['fps']for x in report['samples']if isinstance(x.get('fps'),(int,float))and x['fps']>0]
 report['fps']={'samples':len(fps),'mean':round(sum(fps)/len(fps),3),'min':min(fps),'max':max(fps)}
 assert not any(report['continuity_deltas'].values()),str(report['continuity_deltas'])
 assert report['fps']['mean']>=23
 report['ok']=True
except Exception as e:report['error']=str(e);raise
finally:
 stop.set()
 if 'monitor'in globals():monitor.join(timeout=7)
 try:
  if owned:api('/platforms/bilibili/stop',{})
  if 'uploaded'in globals():
   current=api('/room/state')
   if any(t['id']==uploaded['id']for t in current['tracks']):api('/room/tracks/delete',{'id':uploaded['id']})
  if original:
   api('/room/music',{'action':'pause'});config(original['settings']);api('/room/messages',{'action':'unfeature'});api('/room/messages',{'action':'unpin'});api('/room/messages',{'action':'clear_tests'})
  if 'original_interaction'in globals():api('/platforms/config',{'interaction':original_interaction})
  studio('voice',{'voice_id':'O07'})
  final=api('/room/state');report['final_state']={'offair':final['broadcast']is None,'music_playing':final['music']['playing'],'muted':final['settings']['audio']['muted'],'voice_id':studio('status')['voice']['voice_id']}
 except Exception as e:report['cleanup_error']=str(e);report['ok']=False
 report['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();save();print(json.dumps({k:report.get(k)for k in ['ok','error','cases','checks','fps','continuity_deltas','final_state']},ensure_ascii=False),flush=True)
