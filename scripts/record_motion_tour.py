"""Record every selected gesture through the actual live OBS output with local speech."""
from pathlib import Path
import asyncio,base64,datetime,hashlib,json,subprocess,time,uuid
from aiohttp import ClientSession,ClientTimeout

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/vertical'

async def main():
    catalog=json.loads((ROOT/'configs/vertical/materials/catalog.json').read_text(encoding='utf-8'))
    result={'ok':False,'at':datetime.datetime.now().astimezone().isoformat(),'clips':[]}
    auth_config=json.loads((ROOT/'tools/obs/config/obs-studio/plugin_config/obs-websocket/config.json').read_text(encoding='utf-8'))
    recorded=False
    try:
        async with ClientSession(timeout=ClientTimeout(total=60),trust_env=False) as client:
            async def api(route,data=None):
                async with client.request('GET' if data is None else 'POST','http://127.0.0.1:8010/api/studio/'+route,json=data) as response:
                    response.raise_for_status();return await response.json()
            if len((await api('motion')).get('clips',[]))<50:raise RuntimeError('The complete reviewed bank must be active')
            async with client.ws_connect('http://127.0.0.1:4457') as ws:
                hello=await ws.receive_json();identify={'rpcVersion':1,'eventSubscriptions':64}
                auth=hello['d'].get('authentication')
                if auth:
                    secret=base64.b64encode(hashlib.sha256((auth_config['server_password']+auth['salt']).encode()).digest()).decode()
                    identify['authentication']=base64.b64encode(hashlib.sha256((secret+auth['challenge']).encode()).digest()).decode()
                await ws.send_json({'op':1,'d':identify})
                if (await ws.receive_json())['op']!=2:raise RuntimeError('OBS authentication failed')
                record_event={'state':None}
                async def call(name,data=None):
                    rid=uuid.uuid4().hex
                    await ws.send_json({'op':6,'d':{'requestType':name,'requestId':rid,'requestData':data or {}}})
                    while True:
                        packet=await ws.receive_json()
                        if packet['op']==5 and packet['d']['eventType']=='RecordStateChanged':record_event['state']=packet['d']['eventData']['outputState']
                        if packet['op']==7 and packet['d']['requestId']==rid:
                            body=packet['d']
                            if not body['requestStatus']['result']:raise RuntimeError(name+': '+body['requestStatus'].get('comment','failed'))
                            return body.get('responseData',{})
                if (await call('GetRecordStatus'))['outputActive'] or (await call('GetStreamStatus'))['outputActive']:
                    raise RuntimeError('Leave the existing OBS output untouched')
                status=await api('status')
                if status['viewers']<1:raise RuntimeError('OBS must already be connected')
                await call('SetRecordDirectory',{'recordDirectory':str(OUT)})
                poses=OUT/'tour/poses';poses.mkdir(parents=True,exist_ok=True)
                text='欢迎来到我的直播间。你可以通过网页选择不同的人物动作，也可以输入一句话让我读出来。我们可以聊聊学习方法、校园生活，或者一起分享最近读过的书和喜欢的电影。动作会先完整做完，再切换到下一段。谢谢你在这里陪伴，也希望你今天有一个轻松愉快的好心情。'
                speech_pending=False
                async def keep_speaking():
                    nonlocal speech_pending
                    state=await api('status')
                    if state['speaking']:
                        speech_pending=False
                    elif not speech_pending:
                        await api('speak',{'text':text,'mode':'echo','interrupt':False})
                        speech_pending=True
                await call('StartRecord');recorded=True;start=time.monotonic()
                try:
                    for _ in range(20):
                        if (await call('GetRecordStatus'))['outputActive']:break
                        await asyncio.sleep(.25)
                    else:raise RuntimeError('OBS did not enter recording state')
                    await keep_speaking()
                    for item in catalog['items']:
                        mid=item['id'];await api('motion',{'id':mid})
                        deadline=time.monotonic()+20
                        while True:
                            motion=await api('motion')
                            if motion['active']==mid:break
                            if time.monotonic()>deadline:raise RuntimeError('Selected gesture never became active: '+mid)
                            await asyncio.sleep(.25)
                        evidence={'id':mid,'title':item['title'],'active_seconds':round(time.monotonic()-start,2)}
                        # Wait into the pose, allowing for the live output buffer.
                        await asyncio.sleep(3.5)
                        picture=await call('GetSourceScreenshot',{'sourceName':'Avatar','imageFormat':'png','imageWidth':720,'imageHeight':1280})
                        image=poses/(mid+'.png');image.write_bytes(base64.b64decode(picture['imageData'].split(',',1)[1]))
                        state=await api('status');evidence.update(speaking=state['speaking'],pose=str(image.relative_to(ROOT)))
                        result['clips'].append(evidence)
                        (OUT/'tour/progress.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                        print(json.dumps({'verified':len(result['clips']),'id':mid,'speaking':state['speaking']}),flush=True)
                        await keep_speaking()
                    await asyncio.sleep(7)
                finally:
                    if recorded:
                        stop=await call('StopRecord');recorded=False;result['recorded_path']=stop['outputPath']
                        stop_deadline=time.monotonic()+30
                        while record_event['state']!='OBS_WEBSOCKET_OUTPUT_STOPPED':
                            if time.monotonic()>stop_deadline:raise RuntimeError('OBS did not confirm recording finalization')
                            await call('GetRecordStatus');await asyncio.sleep(.2)
                    await api('interrupt',{});await api('motion',{'id':'auto'})
                result['obs_stats']=await call('GetStats')
        ffmpeg=next((ROOT/'tools/ffmpeg').rglob('ffmpeg.exe'));target=OUT/'motion-tour.mp4'
        subprocess.run([str(ffmpeg),'-nostdin','-v','error','-y','-i',result['recorded_path'],'-c','copy','-movflags','+faststart',str(target)],check=True,timeout=90)
        media=json.loads(subprocess.check_output([str(ffmpeg.with_name('ffprobe.exe')),'-v','error','-show_entries','stream=codec_type,width,height,r_frame_rate:format=duration','-of','json',str(target)],text=True))
        result['media']=media;result['bytes']=target.stat().st_size
        result['ok']=len(result['clips'])==len(catalog['items']) and any(s.get('width')==720 and s.get('height')==1280 for s in media['streams']) and float(media['format']['duration'])>=384
    except Exception as exc:result['error']=str(exc)
    (OUT/'tour').mkdir(exist_ok=True)
    (OUT/'tour/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='clips'},ensure_ascii=False),flush=True)
    raise SystemExit(0 if result['ok'] else 1)

asyncio.run(main())
