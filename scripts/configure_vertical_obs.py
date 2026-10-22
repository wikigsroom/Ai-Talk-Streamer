"""Switch only the project's inactive OBS output and browser source to 9:16."""
from pathlib import Path
import asyncio, base64, datetime, hashlib, json, uuid
from aiohttp import ClientSession, ClientTimeout
ROOT=Path(__file__).resolve().parents[1]
async def main():
    settings=json.loads((ROOT/'tools/obs/config/obs-studio/plugin_config/obs-websocket/config.json').read_text(encoding='utf-8'))
    async with ClientSession(timeout=ClientTimeout(total=30),trust_env=False) as client:
        async with client.ws_connect('http://127.0.0.1:4457') as ws:
            hello=await ws.receive_json();identify={'rpcVersion':1,'eventSubscriptions':0};auth=hello['d'].get('authentication')
            if auth:
                secret=base64.b64encode(hashlib.sha256((settings['server_password']+auth['salt']).encode()).digest()).decode()
                identify['authentication']=base64.b64encode(hashlib.sha256((secret+auth['challenge']).encode()).digest()).decode()
            await ws.send_json({'op':1,'d':identify})
            if (await ws.receive_json())['op']!=2:raise RuntimeError('OBS authentication failed')
            async def call(name,data=None):
                rid=uuid.uuid4().hex
                await ws.send_json({'op':6,'d':{'requestType':name,'requestId':rid,'requestData':data or {}}})
                while True:
                    packet=await ws.receive_json()
                    if packet['op']==7 and packet['d']['requestId']==rid:
                        body=packet['d']
                        if not body['requestStatus']['result']:raise RuntimeError(name+': '+body['requestStatus'].get('comment','failed'))
                        return body.get('responseData',{})
            if (await call('GetStreamStatus'))['outputActive'] or (await call('GetRecordStatus'))['outputActive']:
                raise RuntimeError('Existing OBS output is active; left unchanged')
            before={'video':await call('GetVideoSettings'),'source':await call('GetInputSettings',{'inputName':'Avatar Browser'}),'items':await call('GetSceneItemList',{'sceneName':'Avatar'})}
            backup=ROOT/'.setup/vertical-obs-before.json'
            if not backup.exists():backup.write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
            await call('SetVideoSettings',{'baseWidth':720,'baseHeight':1280,'outputWidth':720,'outputHeight':1280,'fpsNumerator':25,'fpsDenominator':1})
            await call('SetInputSettings',{'inputName':'Avatar Browser','inputSettings':{'url':'http://127.0.0.1:8010/obs.html?v=vertical-1','width':720,'height':1280,'reroute_audio':True},'overlay':True})
            for item in before['items']['sceneItems']:
                if item['sourceName']=='Avatar Browser':
                    await call('SetSceneItemTransform',{'sceneName':'Avatar','sceneItemId':item['sceneItemId'],'sceneItemTransform':{'positionX':0,'positionY':0,'rotation':0,'scaleX':1,'scaleY':1,'alignment':5,'boundsType':'OBS_BOUNDS_NONE','cropLeft':0,'cropRight':0,'cropTop':0,'cropBottom':0}})
            await call('SetInputMute',{'inputName':'Avatar Browser','inputMuted':False})
            # Keep speech at a comfortable level and leave headroom in encoded audio.
            await call('SetInputVolume',{'inputName':'Avatar Browser','inputVolumeDb':-3.0})
            result={'at':datetime.datetime.now().astimezone().isoformat(),'video':await call('GetVideoSettings'),'source':await call('GetInputSettings',{'inputName':'Avatar Browser'}),'items':await call('GetSceneItemList',{'sceneName':'Avatar'})}
            (ROOT/'.setup/vertical-obs.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'ok':True,'video':result['video'],'source_size':[result['source']['inputSettings']['width'],result['source']['inputSettings']['height']]}))
asyncio.run(main())
