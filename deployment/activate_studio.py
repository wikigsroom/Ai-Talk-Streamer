"""Install the reviewed studio integration, keeping project-local source backups."""
from pathlib import Path
import ast,datetime,hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/'src/LiveTalking'
changes=[]
def update(path,text):
    old=path.read_bytes() if path.exists() else b''
    backup=ROOT/'.setup/studio-originals'/path.relative_to(ROOT)
    if old and not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(old)
    if path.suffix=='.py':ast.parse(text,filename=str(path))
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
    changes.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
def main():
    target=ROOT/'src/GPT-SoVITS/GPT_SoVITS/text/LangSegmenter/langsegmenter.py'
    text=target.read_text(encoding='utf-8')
    if 'import os\n' not in text:text='import os\n'+text
    text=text.replace('cache_dir=Path(__file__).parent.parent.parent / "pretrained_models" / "fast_langdetect"','cache_dir=Path(os.environ.get("FTLANG_CACHE", str(Path(__file__).parent.parent.parent / "pretrained_models" / "fast_langdetect")))')
    update(target,text)
    target=LIVE/'avatars/base_avatar.py';text=target.read_text(encoding='utf-8')
    if '        torch.set_num_threads(1) # studio render worker' not in text:
        text=text.replace('    def inference(self, quit_event):','    def inference(self, quit_event):\n        import torch\n        torch.set_num_threads(1) # studio render worker')
    if 'motion.next_indices' not in text:
        text=text.replace('            current_speaking = not is_all_silence','            current_speaking = not is_all_silence\n            motion = getattr(self, "motion", None)\n            frame_indices = motion.next_indices(self.batch_size, current_speaking) if motion else None\n            self._studio_frame_indices = frame_indices')
        text=text.replace('idx = mirror_index(length, index)','idx = frame_indices[i] if frame_indices is not None else mirror_index(length, index)')
        text=text.replace('audio_frames[i*2:i*2+2], mirror_index(length, index)))','audio_frames[i*2:i*2+2], frame_indices[i] if frame_indices is not None else mirror_index(length, index)))')
    update(target,text)
    target=LIVE/'server/webrtc.py';text=target.read_text(encoding='utf-8')
    text=text.replace('    container.render(quit_event)','    import torch\n    torch.set_num_threads(1)\n    with torch.inference_mode():\n        container.render(quit_event)') if '    with torch.inference_mode():' not in text else text
    text=text.replace('new_frame = VideoFrame.from_ndarray(frame, format="bgr24")','new_frame = VideoFrame.from_ndarray(frame, format="bgr24").reformat(format="yuv420p")')
    if 'await asyncio.sleep(0) # yield to RTP senders' not in text:
        text=text.replace('        return frame\n','        await asyncio.sleep(0) # yield to RTP senders, including when catching up\n        return frame\n')
    update(target,text)
    target=LIVE/'avatars/musetalk/whisper/audio2feature.py';text=target.read_text(encoding='utf-8')
    if '    @torch.inference_mode()' not in text:text=text.replace('    def audio2feat(self, wav_data):','    @torch.inference_mode()\n    def audio2feat(self, wav_data):')
    if '_studio_silent_feature' not in text:
        text=text.replace('        input_feature = self.feature_extractor(', '        if not np.any(wav_data):\n            if not hasattr(self, "_studio_silent_feature"):\n                self._studio_silent_feature = np.zeros((1500, 5, 384), dtype=np.float16)\n            return self._studio_silent_feature\n        input_feature = self.feature_extractor(')
    update(target,text)
    for name in ['studio_rtc.py','studio_routes.py','dsh_bridge.py','character_identity.py','isolated_inference.py','local_broadcast.py','stream_encoder.py','viewer_buffer.py','frame_store.py','motion_control.py','pose_gallery.py','scenario_gallery.py','fast_blending.py','lipsync_k02.py']:update(LIVE/'server'/name,(ROOT/'integration'/name).read_text(encoding='utf-8'))
    for source in (ROOT/'web').glob('*'):
        if source.is_file():update(LIVE/'web'/source.name,source.read_text(encoding='utf-8'))
    update(LIVE/'web/obs.html',(ROOT/'integration/obs.html').read_text(encoding='utf-8'))
    target=LIVE/'app.py';text=target.read_text(encoding='utf-8')
    text=text.replace('from server.rtc_manager import RTCManager','from server.studio_rtc import StudioRTCManager as RTCManager')
    if 'from server.studio_routes import setup_studio' not in text:text=text.replace('from server.routes import setup_routes','from server.routes import setup_routes\nfrom server.studio_routes import setup_studio')
    if '    setup_studio(appasync)' not in text:text=text.replace('    setup_routes(appasync)','    setup_studio(appasync)\n    setup_routes(appasync)')
    if 'torch.set_num_interop_threads(1)' not in text:text=text.replace('    opt = parse_args()','    opt = parse_args()\n    torch.set_num_threads(1)\n    torch.set_num_interop_threads(1)')
    text=text.replace("web.TCPSite(runner, '127.0.0.1', opt.listenport)","web.TCPSite(runner, '0.0.0.0', opt.listenport)")
    update(target,text)
    target=LIVE/'avatars/musetalk_avatar.py';text=target.read_text(encoding='utf-8')
    if 'from server.frame_store import FrameStore' not in text:
        text=text.replace('def load_avatar(avatar_id):','from server.frame_store import FrameStore\n\ndef load_avatar(avatar_id):')
    if 'from server.fast_blending import paste_face' not in text:
        text=text.replace('from server.frame_store import FrameStore','from server.frame_store import FrameStore\nfrom server.fast_blending import paste_face')
    text=text.replace('combine_frame = get_image_blending(ori_frame, res_frame, bbox, mask, mask_crop_box)','combine_frame = paste_face(ori_frame, res_frame, bbox, mask, mask_crop_box)')
    text=text.replace('combine_frame = get_image_blending(ori_frame,res_frame,bbox,mask,mask_crop_box)','combine_frame = paste_face(ori_frame,res_frame,bbox,mask,mask_crop_box)')
    if 'combine_frame = paste_face(' not in text:raise RuntimeError('The pinned MuseTalk blending call was not found')
    text=text.replace('frame_list_cycle = read_imgs(input_img_list)','frame_list_cycle = FrameStore(input_img_list)')
    text=text.replace('mask_list_cycle = read_imgs(input_mask_list)','mask_list_cycle = FrameStore(input_mask_list)')
    text=text.replace('torch.load(latents_out_path)','torch.load(latents_out_path, map_location="cpu")')
    text=text.replace('latent_batch = latent_batch.to(dtype= self.unet.model.dtype)','latent_batch = latent_batch.to(device=self.unet.device, dtype=self.unet.model.dtype)')
    text=text.replace('latent_batch = latent_batch.to(dtype=self.unet.model.dtype)','latent_batch = latent_batch.to(device=self.unet.device, dtype=self.unet.model.dtype)')
    if 'AVATAR_GPU_WORKER_CHILD' not in text:
        text=text.replace('def load_model():','def load_model():\n    if os.getenv("AVATAR_GPU_ISOLATION") == "1" and os.getenv("AVATAR_GPU_WORKER_CHILD") != "1":\n        from server.isolated_inference import load_proxy\n        return load_proxy()')
        text=text.replace('def warm_up(batch_size,model):','def warm_up(batch_size,model):\n    if getattr(model[4], "is_isolated", False):return')
        text=text.replace('    def inference_batch(self, index, audiofeat_batch):','    def inference_batch(self, index, audiofeat_batch):\n        if getattr(self.audio_processor, "is_isolated", False):\n            return self.audio_processor.client.call("render",index=index,features=audiofeat_batch)')
    if 'Studio tensor metadata' not in text:
        text=text.replace('        pred_latents = self.unet.model(latent_batch,','        if not getattr(self, "_studio_tensor_logged", False):\n            logger.info("Studio tensor metadata latent=%s %s %s audio=%s %s model=%s threads=%s", tuple(latent_batch.shape), latent_batch.device, latent_batch.dtype, tuple(audio_feature_batch.shape), audio_feature_batch.device, next(self.unet.model.parameters()).device, torch.get_num_threads())\n            self._studio_tensor_logged = True\n        pred_latents = self.unet.model(latent_batch,')
    if 'self.motion = load_motion' not in text:
        text=text.replace('        super().__init__(opt)','        super().__init__(opt)\n        from server.motion_control import load_motion\n        self.motion = load_motion(opt.avatar_id)')
    text=text.replace('return self.audio_processor.client.call("render",index=index,features=audiofeat_batch)','return self.audio_processor.client.call("render",index=index,features=audiofeat_batch,indices=getattr(self,"_studio_frame_indices",None))')
    text=text.replace('idx = mirror_index(length, index + i)','idx = self._studio_frame_indices[i] if getattr(self,"_studio_frame_indices",None) is not None else mirror_index(length, index + i)')
    update(target,text)
    target=LIVE/'server/routes.py';update(target,target.read_text(encoding='utf-8').replace("pagename = 'index.html'","pagename = 'studio.html'"))
    update(LIVE/'llm.py',(ROOT/'integration/llm_channel.py').read_text(encoding='utf-8'))
    target=LIVE/'tts/sovits.py';text=target.read_text(encoding='utf-8')
    text=text.replace('import resampy','from scipy.signal import resample_poly\nfrom math import gcd')
    text=text.replace('resampy.resample(x=stream, sr_orig=sample_rate, sr_new=self.sample_rate)','resample_poly(stream, self.sample_rate // gcd(sample_rate, self.sample_rate), sample_rate // gcd(sample_rate, self.sample_rate)).astype(np.float32)')
    if 'def _studio_current' not in text:
        text=text.replace('    def stream_tts(self,audio_stream,msg:tuple[str, dict]):','    def _studio_current(self, info):\n        return "generation" not in info or info["generation"] == getattr(self.parent, "_studio_generation", None)\n\n    def stream_tts(self,audio_stream,msg:tuple[str, dict]):')
        text=text.replace('        for chunk in audio_stream:\n','        for chunk in audio_stream:\n            if not self._studio_current(textevent):return\n')
        text=text.replace('                while streamlen >= self.chunk:\n','                while streamlen >= self.chunk:\n                    if not self._studio_current(textevent):return\n')
    update(target,text)
    result={'ok':True,'at':datetime.datetime.now().astimezone().isoformat(),'patches':changes}
    (ROOT/'.setup/studio-install.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'files':len(changes)}))
if __name__=='__main__':main()
