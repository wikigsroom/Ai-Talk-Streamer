"""Apply reviewable native-Windows integration patches and local configurations."""
from pathlib import Path
import datetime,hashlib,json,re,shutil
ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/'src/LiveTalking'
TTS=ROOT/'src/GPT-SoVITS'
changes=[]

def digest(data):return hashlib.sha256(data).hexdigest()
def update(path,text,reason):
    data=text.encode('utf-8');old=path.read_bytes() if path.exists() else b''
    rel=path.relative_to(ROOT)
    backup=ROOT/'.setup/upstream-originals'/rel
    if old and not backup.exists():
        backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(old)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    changes.append({'path':str(rel),'reason':reason,'original_sha256':digest(backup.read_bytes()) if backup.exists() else None,'installed_sha256':digest(data)})

def main():
    update(LIVE/'utils/__init__.py','"""LiveTalking application utilities."""\n','Make application utils an explicit package to avoid collision with vendored utils.py modules')
    target=LIVE/'avatars/musetalk/utils/preprocessing.py'
    text=target.read_text(encoding='utf-8')
    text=text.replace('from face_detection import FaceAlignment,LandmarksType','from avatars.musetalk.utils.face_detection import FaceAlignment,LandmarksType')
    text=text.replace('import face_recognition','from avatars.musetalk.utils import native_landmarks as face_recognition')
    update(target,text,'Use vendored detector import and native Windows dlib wheel with upstream landmark models')
    update(LIVE/'avatars/musetalk/utils/native_landmarks.py',(ROOT/'integration/native_landmarks.py').read_text(encoding='utf-8'),'Native Windows CPU landmark adapter')
    target=LIVE/'avatars/musetalk/utils/face_detection/api.py'
    text=target.read_text(encoding='utf-8').replace("__import__('face_detection.detection.'", "__import__('avatars.musetalk.utils.face_detection.detection.'")
    update(target,text,'Resolve the detector inside the vendored MuseTalk package')
    for path in (TTS/'GPT_SoVITS').rglob('*.py'):
        text=path.read_text(encoding='utf-8-sig')
        if 'jieba_fast' in text:
            update(path,text.replace('jieba_fast','jieba'),'Use upstream jieba Python API instead of the source-only C accelerator')
    update(LIVE/'llm.py',(ROOT/'integration/llm_channel.py').read_text(encoding='utf-8'),'Explicit configurable user LLM channel; no default provider or implicit model ID')
    target=LIVE/'app.py'
    text=target.read_text(encoding='utf-8').replace("web.TCPSite(runner, '0.0.0.0', opt.listenport)","web.TCPSite(runner, '127.0.0.1', opt.listenport)")
    update(target,text,'Bind the avatar service to loopback for same-machine OBS capture')
    target=LIVE/'tts/sovits.py'
    text=target.read_text(encoding='utf-8')
    text=text.replace("'media_type':'ogg'","'media_type':'wav'").replace("'streaming_mode':True","'streaming_mode':False")
    text=text.replace('stream=True,','stream=False,\n                timeout=(10,180),')
    text=text.replace('for chunk in res.iter_content(chunk_size=None):','for chunk in [res.content]:')
    update(target,text,'Decode one complete local WAV per short sentence instead of treating HTTP chunks as complete Ogg files')
    update(LIVE/'web/obs.html',(ROOT/'integration/obs.html').read_text(encoding='utf-8'),'Automatic local WebRTC receiver for an OBS browser source')
    config=ROOT/'configs';config.mkdir(exist_ok=True)
    channel=config/'channel.env'
    if not channel.exists():shutil.copyfile(config/'channel.env.example',channel)
    for path in ['assets/custom/avatar','assets/custom/voice','outputs','logs','cache/tmp']:(ROOT/path).mkdir(parents=True,exist_ok=True)
    live_config={'fps':25,'l':10,'m':8,'r':10,'model':'musetalk','avatar_id':'demo_musetalk_v15','batch_size':4,'tts':'gpt-sovits','TTS_SERVER':'http://127.0.0.1:9880','REF_FILE':str(ROOT/'assets/demo/reference_zh.wav'),'REF_TEXT':'希望你以后能够做的比我还好呦。','llm_provider':'channel','llm_model':'','transport':'webrtc','stun':'','push_url':'','max_session':1,'listenport':8010}
    # JSON is also valid YAML, and keeps Windows backslash escaping unambiguous.
    (config/'livetalking.yaml').write_text(json.dumps(live_config,ensure_ascii=False,indent=2),encoding='utf-8')
    base='GPT_SoVITS/pretrained_models/'
    for name,version,s1,s2 in [('v2','v2',base+'gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt',base+'gsv-v2final-pretrained/s2G2333k.pth'),('v2ProPlus','v2ProPlus',base+'s1v3.ckpt',base+'v2Pro/s2Gv2ProPlus.pth')]:
        settings={'custom':{'bert_base_path':base+'chinese-roberta-wwm-ext-large','cnhuhbert_base_path':base+'chinese-hubert-base','device':'cuda','is_half':True,'t2s_weights_path':s1,'version':version,'vits_weights_path':s2}}
        (config/f'tts-{name}.yaml').write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
    obs=ROOT/'tools/obs'
    (obs/'portable_mode.txt').touch()
    # OBS portable mode stores settings in the same unpacked directory.
    scene_dir=obs/'config/obs-studio/basic/scenes';scene_dir.mkdir(parents=True,exist_ok=True)
    scene={'name':'Avatar Local','current_scene':'Avatar','current_program_scene':'Avatar','scene_order':[{'name':'Avatar'}],'sources':[{'name':'Avatar Browser','id':'browser_source','versioned_id':'browser_source','settings':{'url':'http://127.0.0.1:8010/obs.html','width':720,'height':1280,'fps':25,'reroute_audio':True,'shutdown':True,'restart_when_active':False},'mixers':255,'volume':1.0,'enabled':True},{'name':'Avatar','id':'scene','versioned_id':'scene','settings':{'items':[{'name':'Avatar Browser','visible':True,'locked':False,'pos':{'x':0.0,'y':0.0},'scale':{'x':1.0,'y':1.0},'rot':0.0,'align':5,'bounds_type':0,'bounds_align':0,'bounds':{'x':0.0,'y':0.0}}]}}]}
    (scene_dir/'Avatar_Local.json').write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
    profile=obs/'config/obs-studio/basic/profiles/Avatar_Local';profile.mkdir(parents=True,exist_ok=True)
    (profile/'basic.ini').write_text('[General]\nName=Avatar Local\n\n[Video]\nBaseCX=720\nBaseCY=1280\nOutputCX=720\nOutputCY=1280\nFPSType=0\nFPSCommon=25 PAL\n\n[Output]\nMode=Simple\n\n[SimpleOutput]\nStreamEncoder=nvenc\nRecQuality=Small\nRecFormat2=mkv\nVBitrate=6000\nABitrate=160\n',encoding='utf-8')
    # Set local sample resources aside; their original projects supply them for demonstrations.
    (ROOT/'assets/demo/README.md').write_text('上游演示素材，仅用于安装后链路测试。视频来自 TMElyralab/MuseTalk 的 data/video/yongen.mp4；参考音频及文本来自 FunAudioLLM/CosyVoice 的 asset/zero_shot_prompt.wav 和 example.py。正式直播请替换为自己的形象和声音。\n',encoding='utf-8')
    recorded={item['path'] for item in changes}
    for original in (ROOT/'.setup/upstream-originals').rglob('*'):
        if not original.is_file():continue
        relative=original.relative_to(ROOT/'.setup/upstream-originals');installed=ROOT/relative
        if str(relative) not in recorded and installed.exists() and installed.read_bytes()!=original.read_bytes():
            changes.append({'path':str(relative),'reason':'Previous integration patch; original source preserved','original_sha256':digest(original.read_bytes()),'installed_sha256':digest(installed.read_bytes())})
    result={'ok':True,'at':datetime.datetime.now().astimezone().isoformat(),'patches':changes,'services_started':False,'inference_run':False}
    (ROOT/'.setup/configuration.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'patches':len(changes)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
