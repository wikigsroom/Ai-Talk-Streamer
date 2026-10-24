"""Project-local studio controls. Only configured text conversations use the cloud."""
from pathlib import Path
import asyncio,datetime,json,os,re,socket,subprocess,time
from urllib.parse import urlsplit
from aiohttp import web,ClientSession,ClientTimeout
from server.session_manager import session_manager
from server.character_identity import character_identity

ROOT=Path(__file__).resolve().parents[3]
STARTED=time.time()
GPU_CACHE={'at':0,'value':{}}
GPU_LOCK=asyncio.Lock()
CHANNEL_KEYS=('AVATAR_LLM_BASE_URL','AVATAR_LLM_API_KEY','AVATAR_LLM_MODEL','AVATAR_LLM_PROTOCOL','AVATAR_SYSTEM_PROMPT')

def response(data,status=200):return web.json_response(data,status=status,dumps=lambda obj:json.dumps(obj,ensure_ascii=False))

def channel_info():
    return {'base_url':os.getenv('AVATAR_LLM_BASE_URL',''),'model':os.getenv('AVATAR_LLM_MODEL',''),'protocol':os.getenv('AVATAR_LLM_PROTOCOL','chat_completions'),'system_prompt':os.getenv('AVATAR_SYSTEM_PROMPT','你是一位直播助手，请用简短自然的中文口语回复。'),'has_key':bool(os.getenv('AVATAR_LLM_API_KEY','')),'configured':all(os.getenv(k,'').strip() for k in CHANNEL_KEYS[:3])}

def same_origin(request):
    origin=request.headers.get('Origin')
    if origin and urlsplit(origin).netloc!=request.host:raise web.HTTPForbidden(text='请从演播台页面操作。')

async def status(request):
    manager=request.app['rtc_manager'];avatar=session_manager.get_session('studio')
    # Query the driver outside the HTTP loop; the web process needs no CUDA context.
    async with GPU_LOCK:
        if time.monotonic()-GPU_CACHE['at']>5:
            try:
                query=await asyncio.to_thread(subprocess.run,['nvidia-smi','--query-gpu=name,memory.free,memory.total','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,check=True)
                name,free,total=query.stdout.splitlines()[0].split(',')
                GPU_CACHE['value']={'name':name.strip(),'free_gib':round(int(free)/1024,2),'total_gib':round(int(total)/1024,2)}
            except Exception:pass
            GPU_CACHE['at']=time.monotonic()
    gpu=GPU_CACHE['value']
    tts=False
    try:
        async with ClientSession(timeout=ClientTimeout(total=2),trust_env=False) as client:
            async with client.get('http://127.0.0.1:9880/openapi.json') as res:tts=res.status==200
    except Exception:pass
    identity=character_identity()
    return response({'ready':tts,'tts_ready':tts,'avatar_ready':True,'speaking':bool(avatar and avatar.is_speaking()),'sessionid':'studio' if avatar else None,'viewers':len(manager.broadcast.viewers) if manager.broadcast else 0,'event_subscribers':len(avatar.msgqueues) if avatar else 0,'gpu':gpu,'channel':channel_info(),'uptime_seconds':round(time.time()-STARTED),'profile':'GPT-SoVITS v2','avatar':' · '.join((identity['archive_label'],identity['name'],identity['scene']['name'])),'character':identity,'avatar_id':request.app['opt'].avatar_id,'local_media':True,'transport':'local_websocket_jpeg_pcm'})

async def character_record(request):
    identity=character_identity()
    path=ROOT/identity['archive']['registry']
    archive=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
    return response({'character':identity,'archive':archive,'download_ready':(ROOT/identity['archive']['zip']).is_file()})

async def character_page(request):return web.FileResponse(ROOT/'web/character.html')

async def character_reference(request):return web.FileResponse(ROOT/character_identity()['appearance_reference'])

async def character_archive(request):
    path=ROOT/character_identity()['archive']['zip']
    if not path.is_file():raise web.HTTPNotFound()
    return web.FileResponse(path,headers={'Content-Disposition':'attachment; filename="female-a-lin-zhixia-v1.zip"'})

async def channel(request):
    if request.method=='GET':return response(channel_info())
    same_origin(request);data=await request.json()
    base=str(data.get('base_url','')).strip();model=str(data.get('model','')).strip();protocol=data.get('protocol','chat_completions')
    if base and urlsplit(base).scheme not in ('http','https'):return response({'error':'渠道地址需要以 http:// 或 https:// 开头。'},400)
    if protocol not in ('chat_completions','responses'):return response({'error':'请选择支持的请求协议。'},400)
    key=str(data.get('api_key','')).strip() or os.getenv('AVATAR_LLM_API_KEY','')
    values={'AVATAR_LLM_BASE_URL':base,'AVATAR_LLM_MODEL':model,'AVATAR_LLM_PROTOCOL':protocol,'AVATAR_LLM_API_KEY':key,'AVATAR_SYSTEM_PROMPT':str(data.get('system_prompt','')).strip() or '你是一位直播助手，请用简短自然的中文口语回复。'}
    if any('\n' in value or '\r' in value for value in values.values()):return response({'error':'配置请填写在单行内。'},400)
    target=ROOT/'configs/channel.env';temp=target.with_suffix('.tmp')
    temp.write_text('# User channel configuration; do not publish this file.\n'+'\n'.join(k+'='+v for k,v in values.items())+'\n',encoding='utf-8');temp.replace(target)
    os.environ.update(values)
    return response({'ok':True,'channel':channel_info()})

async def speak(request):
    same_origin(request);data=await request.json();text=str(data.get('text','')).strip();mode=data.get('mode','echo')
    if not text or len(text)>1500:return response({'error':'请输入 1–1500 字的播报内容。'},400)
    if mode not in ('echo','chat'):return response({'error':'请选择原文播报或 AI 回复。'},400)
    if mode=='chat' and not channel_info()['configured']:return response({'error':'请先在渠道设置中填写地址、密钥和实际模型 ID。'},400)
    manager=request.app['rtc_manager']
    if not manager.broadcast or not manager.broadcast.viewers:return response({'error':'请先连接预览或打开 OBS 画面。'},409)
    avatar=session_manager.get_session('studio')
    if data.get('interrupt',True):avatar.flush_talk()
    avatar._studio_generation=getattr(avatar,'_studio_generation',0)+1
    info={'request_id':str(int(time.time()*1000)),'generation':avatar._studio_generation}
    if mode=='echo':avatar.put_msg_txt(text,info)
    else:asyncio.get_running_loop().run_in_executor(None,request.app['llm_response'],text,avatar,info)
    return response({'ok':True,'sessionid':'studio','request_id':info['request_id']})

async def interrupt(request):
    same_origin(request);avatar=session_manager.get_session('studio')
    if avatar:
        avatar._studio_generation=getattr(avatar,'_studio_generation',0)+1
        avatar.flush_talk()
    return response({'ok':True})

async def poster(request):
    avatar_id=request.app['opt'].avatar_id
    path=next((ROOT/'src/LiveTalking/data/avatars'/avatar_id/'full_imgs').glob('*.png'))
    return web.FileResponse(path)

async def upload_portrait(request):
    same_origin(request)
    from PIL import Image
    import io,hashlib
    data=await request.read()
    if len(data)>20*1024*1024:return response({'error':'图片超过 20 MB。'},413)
    try:
        picture=Image.open(io.BytesIO(data));picture.verify()
        picture=Image.open(io.BytesIO(data)).convert('RGB')
        variant=request.query.get('variant','portrait')
        if variant not in ('portrait','source','background'):return response({'error':'不支持的素材类型。'},400)
        expected=(1280,720) if variant=='portrait' else (1536,1024)
        if picture.size!=expected:return response({'error':'图片尺寸不符合所选素材类型。'},400)
    except Exception:return response({'error':'请上传有效的图片文件。'},400)
    targets={'portrait':ROOT/'assets/custom/student-dorm.png','source':ROOT/'output/imagegen/student-dorm.png','background':ROOT/'output/imagegen/dorm-background.png'}
    target=targets[variant];target.parent.mkdir(parents=True,exist_ok=True)
    picture.save(target)
    return response({'ok':True,'asset':target.name,'width':picture.width,'height':picture.height,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})

async def demo(request):
    name=request.match_info['name'];allowed={'tts_zh.wav','digital-human-demo.mp4','vertical-demo.mp4','vertical-idle.mp4','motion-tour.mp4'}
    if name not in allowed:raise web.HTTPNotFound()
    path=ROOT/('outputs/vertical' if name.startswith('vertical-') or name=='motion-tour.mp4' else 'outputs/验收')/name
    if not path.exists():raise web.HTTPNotFound()
    return web.FileResponse(path)

async def guide(request):return web.FileResponse(ROOT/'web/guide.html')

def reviewed_materials():
    catalog_path=ROOT/'configs/vertical/materials/catalog.json'
    reviews_path=ROOT/'configs/vertical/materials/reviews.json'
    if not catalog_path.exists() or not reviews_path.exists():return []
    catalog=json.loads(catalog_path.read_text(encoding='utf-8'))
    reviews=json.loads(reviews_path.read_text(encoding='utf-8'))
    return [item for item in catalog['items'] if reviews.get(item['id'],{}).get('accepted') and (ROOT/item['source_video']).exists()]

async def materials(request):
    items=reviewed_materials()
    return response({'count':len(items),'seconds':sum(i['duration_seconds'] for i in items),'items':[{k:i[k] for k in ('id','title','category','category_label','duration_seconds')}|{'url':'/materials/video/'+i['id']+'.mp4','poster_url':'/materials/poster/'+i['id']+'.jpg'} for i in items]})

async def material_video(request):
    name=request.match_info['name']
    item=next((i for i in reviewed_materials() if i['id']+'.mp4'==name),None)
    if not item:raise web.HTTPNotFound()
    return web.FileResponse(ROOT/item['source_video'])

async def materials_page(request):return web.FileResponse(ROOT/'web/materials.html')

async def material_poster(request):
    name=request.match_info['name']
    if not any(i['id']+'.jpg'==name for i in reviewed_materials()):raise web.HTTPNotFound()
    path=ROOT/'outputs/vertical/materials/posters'/name
    if not path.exists():raise web.HTTPNotFound()
    return web.FileResponse(path)

async def material_download(request):
    path=ROOT/'outputs/vertical/portrait-motion-materials.zip'
    if not path.exists():raise web.HTTPNotFound()
    return web.FileResponse(path,headers={'Content-Disposition':'attachment; filename="portrait-motion-materials.zip"'})

async def motion(request):
    avatar=session_manager.get_session('studio')
    controller=getattr(avatar,'motion',None) if avatar else None
    if request.method=='GET':return response(controller.status() if controller else {'available':False,'clips':[]})
    same_origin(request)
    if not controller:return response({'error':'先连接预览，待动作素材加载后再选择动作。'},409)
    data=await request.json()
    try:return response({'ok':True,'motion':controller.request(str(data.get('id','')))})
    except ValueError:return response({'error':'请选择素材库中已就绪的动作。'},400)

async def local_stream(request):
    same_origin(request)
    return await request.app['rtc_manager'].handle_local_stream(request)

async def studio_sse(request):
    """Wake on actual events and release subscriptions when a preview closes."""
    avatar=session_manager.get_session(request.query.get('sessionid',''))
    if avatar is None:return response({'error':'session not found'},404)
    output=web.StreamResponse(headers={'Content-Type':'text/event-stream','Cache-Control':'no-cache','Connection':'keep-alive'})
    await output.prepare(request)
    loop=asyncio.get_running_loop();pending=asyncio.Queue(maxsize=64)
    class Subscription:
        active=True
        def put(self,value):
            if self.active:loop.call_soon_threadsafe(self.deliver,value)
        def deliver(self,value):
            if not self.active:return
            if pending.full():pending.get_nowait()
            pending.put_nowait(value)
    subscription=Subscription();avatar.add_msgqueue(subscription)
    try:
        await output.write(b': connected\n\n')
        while request.transport is not None and not request.transport.is_closing():
            try:
                message=await asyncio.wait_for(pending.get(),1)
                await output.write(('data: '+message+'\n\n').encode('utf-8'))
            except asyncio.TimeoutError:
                await output.write(b': heartbeat\n\n')
    except (asyncio.CancelledError,ConnectionResetError,RuntimeError):pass
    finally:
        subscription.active=False
        if subscription in avatar.msgqueues:avatar.msgqueues.remove(subscription)
    return output

def setup_studio(app):
    from server.pose_gallery import configure_pose_gallery
    configure_pose_gallery(app,ROOT)
    from server.scenario_gallery import configure_scenario_gallery
    configure_scenario_gallery(app,ROOT)
    # setup_routes is called after this hook and resolves its handler at runtime.
    from server import routes as native_routes
    native_routes.sse_handler=studio_sse
    app.router.add_get('/api/studio/stream',local_stream)
    app.router.add_get('/api/studio/status',status)
    app.router.add_get('/api/studio/character',character_record)
    app.router.add_get('/character',character_page)
    app.router.add_get('/character/reference.png',character_reference)
    app.router.add_get('/character/archive.zip',character_archive)
    app.router.add_get('/api/studio/channel',channel);app.router.add_post('/api/studio/channel',channel)
    app.router.add_post('/api/studio/speak',speak);app.router.add_post('/api/studio/interrupt',interrupt)
    app.router.add_get('/api/studio/poster',poster)
    app.router.add_post('/api/studio/assets/portrait',upload_portrait)
    app.router.add_get('/demo/{name}',demo)
    app.router.add_get('/guide',guide)
    app.router.add_get('/api/studio/materials',materials)
    app.router.add_get('/materials',materials_page)
    app.router.add_get('/materials/video/{name}',material_video)
    app.router.add_get('/materials/poster/{name}',material_poster)
    app.router.add_get('/materials/download',material_download)
    app.router.add_get('/api/studio/motion',motion);app.router.add_post('/api/studio/motion',motion)
