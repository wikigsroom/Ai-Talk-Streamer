"""Native B-device gateway: same-origin browser audio/video from the A-device VPN address."""
from pathlib import Path
import argparse,asyncio,ipaddress,json,math,os,re,socket,subprocess,time
from urllib.parse import urlsplit

from aiohttp import ClientError,ClientSession,ClientTimeout,WSMsgType,web

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CONFIG=ROOT/'configs/receiver.private.json'
HOP_HEADERS={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade','content-length'}

def validate_config(value):
    config=dict(value)
    parsed=urlsplit(str(config.get('upstream','')))
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('upstream must be an http(s) origin')
    try:address=ipaddress.ip_address(parsed.hostname)
    except ValueError:address=None
    if address and (address.is_unspecified or address.is_multicast):raise ValueError('upstream must identify the A device')
    try:port=parsed.port or (443 if parsed.scheme=='https' else 80)
    except ValueError:raise ValueError('Invalid upstream port')
    if not 1<=port<=65535:raise ValueError('Invalid upstream port')
    receiver_id=config.get('receiver_id','receiver-b')
    if not isinstance(receiver_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',receiver_id):raise ValueError('Invalid receiver_id')
    bind=config.get('bind','127.0.0.1')
    if bind not in ('127.0.0.1','::1'):raise ValueError('The receiver binds to local loopback; use the VPN only for its upstream')
    listen=config.get('port',8020)
    if isinstance(listen,bool) or not isinstance(listen,int) or not 1<=listen<=65535:raise ValueError('Invalid receiver port')
    if (address and address.is_loopback or parsed.hostname.casefold()=='localhost') and port==listen:raise ValueError('Receiver cannot proxy itself')
    config.update(upstream=parsed.scheme+'://'+parsed.netloc,bind=bind,port=listen,receiver_id=receiver_id)
    return config

def official_client(config):
    raw=config.get('client_executable','')
    target=Path(raw).expanduser() if raw else None
    if target and not target.is_absolute():target=ROOT/target
    return target.resolve() if target and target.is_file() and target.name.casefold()=='livehime.exe' else None

def running_client(executable):
    import psutil
    for process in psutil.process_iter(['name','exe']):
        try:
            if (process.info['name'] or '').casefold()=='livehime.exe' and process.info['exe'] and Path(process.info['exe']).resolve()==executable:
                return process.pid
        except (psutil.Error,OSError):continue
    return None

class ReceiverGateway:
    def __init__(self,config):
        self.config=validate_config(config);self.client=None;self.started=time.time();self.active_sockets=set()
        self.metrics={'http_requests':0,'upstream_errors':0,'websocket_connections':0,'media_packets':0,'media_bytes':0,'last_media_at':None,'last_error':None,'last_http_ms':None,'player_metrics':None,'player_metrics_at':None,'media_codec':None,'player_fps':None}
        self.previous_player=None
    async def startup(self,app):
        self.client=ClientSession(timeout=ClientTimeout(total=None,connect=5,sock_read=120),trust_env=False,auto_decompress=False)
    async def cleanup(self,app):
        await asyncio.gather(*(ws.close(code=1001,message=b'Receiver stopping') for ws in list(self.active_sockets)),return_exceptions=True)
        if self.client:await self.client.close()
    async def status(self,request):
        media=self.metrics['last_media_at']
        return web.json_response({'role':'receiver','authentication_required':False,'receiver_id':self.config['receiver_id'],'upstream':self.config['upstream'],
            'client_installed':bool(official_client(self.config)),'source_url':f'http://127.0.0.1:{self.config["port"]}/output.html?output=platform&renderer=livehime',
            'media_connected':bool(media and time.time()-media<8),'active_connections':len(self.active_sockets),'uptime_seconds':round(time.time()-self.started),**self.metrics},headers={'Cache-Control':'no-store'})
    async def check(self,request):
        started=time.perf_counter();result={}
        for label,path in [('studio','/api/studio/status'),('dsh','/api/dsh/status')]:
            try:
                async with self.client.get(self.config['upstream']+path,timeout=ClientTimeout(total=12)) as response:
                    data=await response.json();result[label]={'http_status':response.status}
                    if label=='studio':result[label].update({key:data.get(key) for key in ['ready','tts_ready','avatar_ready','avatar_id','profile','voice','viewers','transport']})
                    else:result[label].update(broadcast=data.get('broadcast'),health=data.get('health'))
            except (ClientError,asyncio.TimeoutError,ValueError) as error:result[label]={'error':type(error).__name__}
        result.update(elapsed_ms=round((time.perf_counter()-started)*1000),receiver_id=self.config['receiver_id'])
        return web.json_response(result,headers={'Cache-Control':'no-store'})
    async def launch_client(self,request):
        executable=official_client(self.config)
        if executable is None:return web.json_response({'error':'RECEIVER_LIVEHIME_NOT_CONFIGURED'},status=503)
        existing=running_client(executable)
        if existing:return web.json_response({'already_running':True,'pid':existing,'public_broadcast_started':False,'on_device':'B'})
        record=ROOT/'outputs/receiver/client-launch.json';record.parent.mkdir(parents=True,exist_ok=True)
        kwargs={'cwd':str(executable.parent),'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL,'close_fds':True}
        if os.name=='nt':kwargs['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW
        try:process=subprocess.Popen([str(executable)],**kwargs)
        except OSError as error:
            if getattr(error,'winerror',None)==740:
                return web.json_response({'error':'RECEIVER_CLIENT_ELEVATION_REQUIRED','message':'此版本需要 Windows 管理员确认。请手动打开已配置的官方直播姬；程序运行后这里会复用它。'},status=409)
            raise
        value={'launch_requested':True,'pid':process.pid,'public_broadcast_started':False,'on_device':'B'}
        record.write_text(json.dumps(value)+'\n',encoding='utf-8');return web.json_response(value)
    async def page(self,request):return web.FileResponse(ROOT/'web/receiver.html')
    async def evidence_page(self,request):return web.FileResponse(ROOT/'web/receiver-evidence.html')
    async def evidence_file(self,request):
        name=request.match_info['name']
        allowed={'split-s01.mp4','split-s02.mp4','split-s03.mp4','split-s04.mp4','split-s05.mp4','split-response.gif','split-portrait.png','split-receiver.png'}
        if name=='receiver-full.mp4':target=ROOT/'outputs/split-device/receiver-full.mp4'
        elif name=='status.json':target=ROOT/'docs/evidence/split-device.json'
        elif name in allowed:target=ROOT/'docs/media'/name
        else:raise web.HTTPNotFound()
        if not target.is_file():raise web.HTTPNotFound()
        return web.FileResponse(target)
    async def proxy(self,request):
        # The upstream is a saved origin. Request paths never select another host.
        target=self.config['upstream']+request.rel_url.raw_path_qs
        if request.headers.get('Upgrade','').lower()=='websocket':return await self.websocket(request,target)
        self.metrics['http_requests']+=1;started=time.perf_counter()
        headers={key:value for key,value in request.headers.items() if key.lower() not in HOP_HEADERS|{'host','accept-encoding'}}
        body=await request.read()
        if request.path=='/api/dsh/platforms/output/player' and request.method=='POST':
            try:data=json.loads(body)
            except ValueError:return web.json_response({'error':'OUTPUT_PLAYER_INVALID'},status=400)
            if not isinstance(data,dict):return web.json_response({'error':'OUTPUT_PLAYER_INVALID'},status=400)
            now=time.time();frames=data.get('frames');consumer=data.get('consumer_id')
            if data.get('renderer')=='livehime' and type(frames) is int and 0<=frames<=1e12 and isinstance(consumer,str):
                old=self.previous_player
                if old and old['consumer']==consumer and frames>=old['frames'] and now-old['at']>=.5:
                    self.metrics['player_fps']=round((frames-old['frames'])/(now-old['at']),3)
                elif not old or old['consumer']!=consumer:self.metrics['player_fps']=None
                self.previous_player={'consumer':consumer,'frames':frames,'at':now}
            metrics=data.pop('stream_metrics',None)
            if data.get('renderer')=='livehime' and isinstance(metrics,dict):
                # Bounded browser diagnostics are observations, not proof of official-client capture.
                safe={key:metrics[key] for key in ('frames','received_frames','presented_frames','fps','audio_clock_seconds','decoder_queue','pending_video_frames','audio_underruns','audio_buffer_ms','missing_packets','skipped_video_frames','decode_errors','max_arrival_gap_ms')
                      if type(metrics.get(key)) in (int,float) and 0<=metrics[key]<=1e12 and math.isfinite(metrics[key])}
                if metrics.get('codec') in ('jpeg','h264_nvenc'):safe['codec']=metrics['codec']
                if metrics.get('fps_source') in ('video_presentation','canvas_draw'):safe['fps_source']=metrics['fps_source']
                if metrics.get('output_mode') in ('direct_canvas_audio','media_stream'):safe['output_mode']=metrics['output_mode']
                self.metrics.update(player_metrics=safe,player_metrics_at=time.time())
            data.update(receiver_id=self.config['receiver_id'],receiver_client_ready=bool(official_client(self.config)))
            body=json.dumps(data).encode('utf-8')
        try:
            async with self.client.request(request.method,target,data=body,headers=headers,allow_redirects=False) as upstream:
                response_headers={key:value for key,value in upstream.headers.items() if key.lower() not in HOP_HEADERS}
                if upstream.headers.get('Content-Type','').startswith('text/event-stream'):
                    result=web.StreamResponse(status=upstream.status,headers=response_headers);await result.prepare(request)
                    async for block in upstream.content.iter_any():await result.write(block)
                    return result
                result=web.StreamResponse(status=upstream.status,headers=response_headers);await result.prepare(request)
                async for block in upstream.content.iter_chunked(256*1024):await result.write(block)
                self.metrics['last_http_ms']=round((time.perf_counter()-started)*1000);return result
        except (ClientError,asyncio.TimeoutError,ConnectionError) as error:
            self.metrics['upstream_errors']+=1;self.metrics['last_error']=type(error).__name__
            return web.json_response({'error':'AVATAR_DEVICE_UNREACHABLE','message':'A设备暂不可达，正在等待恢复。'},status=502)
    async def websocket(self,request,target):
        try:upstream=await asyncio.wait_for(self.client.ws_connect(target,heartbeat=15,compress=0,max_msg_size=8*1024*1024),10)
        except (ClientError,asyncio.TimeoutError):
            self.metrics['upstream_errors']+=1;return web.json_response({'error':'AVATAR_STREAM_UNAVAILABLE'},status=502)
        local=web.WebSocketResponse(heartbeat=15,compress=False,max_msg_size=1024*1024);await local.prepare(request)
        self.active_sockets.add(local);self.metrics['websocket_connections']+=1
        async def forward(source,destination,media=False):
            async for message in source:
                if message.type==WSMsgType.BINARY:
                    if media:
                        self.metrics['media_packets']+=1;self.metrics['media_bytes']+=len(message.data);self.metrics['last_media_at']=time.time()
                        if len(message.data)>=20:self.metrics['media_codec']='h264_nvenc' if message.data[12:16]==b'AVC1' else 'jpeg'
                    await asyncio.wait_for(destination.send_bytes(message.data),5)
                elif message.type==WSMsgType.TEXT:await asyncio.wait_for(destination.send_str(message.data),5)
                elif message.type in (WSMsgType.CLOSE,WSMsgType.CLOSED,WSMsgType.ERROR):break
        tasks=[asyncio.create_task(forward(upstream,local,True)),asyncio.create_task(forward(local,upstream))]
        try:
            done,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        except (ClientError,asyncio.TimeoutError,ConnectionError):self.metrics['upstream_errors']+=1
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            await upstream.close();await local.close(code=1012,message=b'Upstream disconnected; reconnect');self.active_sockets.discard(local)
        return local
    def application(self):
        app=web.Application(client_max_size=2*1024*1024);app.on_startup.append(self.startup);app.on_cleanup.append(self.cleanup)
        app.router.add_get('/receiver/status',self.status);app.router.add_post('/receiver/check',self.check)
        app.router.add_post('/receiver/client/launch',self.launch_client);app.router.add_get('/receiver/',self.page)
        app.router.add_get('/receiver/evidence/',self.evidence_page);app.router.add_get('/receiver/evidence/{name}',self.evidence_file)
        app.router.add_route('*','/{path:.*}',self.proxy);return app

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG);args=parser.parse_args()
    config_path=args.config.resolve()
    if not config_path.is_relative_to(ROOT):raise ValueError('Receiver config must remain inside this project')
    config=validate_config(json.loads(config_path.read_text(encoding='utf-8-sig')))
    print(json.dumps({'role':'receiver','upstream':config['upstream'],'bind':config['bind'],'port':config['port'],'authentication_required':False}),flush=True)
    web.run_app(ReceiverGateway(config).application(),host=config['bind'],port=config['port'],print=None)

if __name__=='__main__':main()
