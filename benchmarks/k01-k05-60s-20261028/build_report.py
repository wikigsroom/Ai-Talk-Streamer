"""Publish only observed metrics; an incomplete run remains explicitly incomplete."""
import json,csv,io,datetime,hashlib,platform,sys,subprocess
from pathlib import Path
R=Path(sys.argv[1]) if len(sys.argv)>1 else Path('C:/dev/虚拟数字人直播');W=R/'operations/k01-k05-60s-20261028';O=R/'outputs/lipsync-k01-k05-60s-20261028'
NAMES={'K01':'MuseTalk 1.5 原方案','K02':'MuseTalk 1.5 局部融合优化','K03':'FeatherTalk 女A教师训练实验版','K04':'Wav2Lip GAN','K05':'LatentSync 1.6'}

def read(p,fallback=None):return json.loads(p.read_text(encoding='utf-8')) if p.exists() else fallback
def main():
 O.mkdir(parents=True,exist_ok=True);
 if (W/'RUNBOOK.md').exists():(O/'protocol.md').write_bytes((W/'RUNBOOK.md').read_bytes())
 if (W/'range_http.py').exists():
  viewer=(W/'range_http.py').read_text(encoding='utf-8')+'\nif __name__=="__main__":\n import argparse,functools\n from pathlib import Path\n parser=argparse.ArgumentParser(description="Read-only benchmark review; Python3.10+, no external dependencies")\n parser.add_argument("--port",type=int,default=8037);parser.add_argument("--host",default="127.0.0.1");args=parser.parse_args()\n root=Path(__file__).resolve().parent\n print(f"Review: http://{args.host}:{args.port}/",flush=True)\n http.server.ThreadingHTTPServer((args.host,args.port),functools.partial(MediaHandler,directory=str(root))).serve_forever()\n'
  (O/'viewer_server.py').write_text(viewer,encoding='utf-8')
 items=[];date=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
 for label,name in NAMES.items():
  row=read(O/label/'result.json',{'id':label,'name':name,'ok':False,'status':'not_run'});row.setdefault('name',name);verify=read(O/label/'verification.json',{});row['verified']=bool(verify.get('verified'));row['verification']=verify
  if label=='K03':row['synthetic_teacher_pilot']=True
  items.append(row)
 if R.drive.lower()=='c:':
  binaries=list((R/'tools/ffmpeg').rglob('ffmpeg.exe'))
  for row in items:
   if not row.get('ok'):continue
   video=O/row['video'];stamp=O/row['id']/'stills/source.json';indices=[0,50,275,550,850,1150,1400]
   signature={'decoded_from_final_mp4':True,'video':row['video'],'bytes':video.stat().st_size,'mtime_ns':video.stat().st_mtime_ns,'frame_indices':indices,'fps':25}
   if read(stamp,{})==signature and all((stamp.parent/f'{i:04d}.jpg').exists() for i in indices):continue
   if not binaries:raise RuntimeError('Native FFmpeg required to decode final review stills')
   stamp.parent.mkdir(parents=True,exist_ok=True)
   for index in indices:
    p=stamp.parent/f'{index:04d}.jpg'
    subprocess.run([str(binaries[0]),'-y','-loglevel','error','-threads','2','-ss',str(index/25),'-i',str(video),'-frames:v','1','-threads','2','-q:v','2',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
   stamp.write_text(json.dumps(signature,indent=2),encoding='utf-8')
 complete=all(r.get('ok') and r.get('verified') for r in items)
 audio_input=read(O/'audio/input.json',{});input_manifest=read(O/'input-manifest.json',{})
 timeline={'speech':audio_input.get('segments',[]),'motion':input_manifest.get('test_clips',[]),'silence_start_seconds':audio_input.get('speech_timeline_end_seconds')}
 data={'generated_at':date,'complete':complete,'audio_available':(O/'audio/common-60s.wav').exists(),'status_note':'五组原文件已逐帧解码与共用音频检查。' if complete else '测试尚未全部完成，未生成或失败的项目不提供性能成绩。','items':items,'timeline':timeline}
 (O/'results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 cols=['id','name','ok','verified','render_wall_seconds','render_rtf','render_fps','cold_load_seconds','total_with_load_seconds','source_prepare_seconds','resource_wait_seconds','render_resource_wait_seconds','render_active_seconds','first_frame_seconds','feature_seconds','inference_seconds','vae_encode_seconds','blend_seconds','encoder_backpressure_seconds','encoder_flush_seconds','torch_peak_allocated_mib','torch_peak_reserved_mib','gpu_total_used_mib_peak','gpu_util_percent_mean','process_rss_mib_peak','bytes','video','execution_adapter']
 stream=io.StringIO(newline='');writer=csv.DictWriter(stream,cols,extrasaction='ignore');writer.writeheader();writer.writerows(items);(O/'results.csv').write_text(stream.getvalue(),encoding='utf-8-sig')
 template=(W/'compare.html').read_text(encoding='utf-8');figures=''
 if not complete and (O/'first-run-stage-times.svg').exists():
  figures='<h2>首轮资源记录</h2><p class="note">以下为 K01、K02、K04 的共享负载首轮采样；'+('完整五组的数据见表格与原始记录。' if complete else '五组测评尚未全部完成。')+'</p><img style="width:100%;height:auto" alt="K01、K02、K04首轮阶段耗时" src="first-run-stage-times.svg"><img style="width:100%;height:auto" alt="K01、K02、K04首轮资源采样" src="first-run-resources.svg">'
 if (O/'all-five-stage-times.svg').exists():
  figures+='<h2>五组阶段耗时</h2><p class="note">同源60秒视频，分次测量；请结合各次后台负载，不将其视为独占GPU排名。</p><img style="width:100%;height:auto" alt="五组实际阶段耗时" src="all-five-stage-times.svg"><img style="width:100%;height:auto" alt="五组资源实测" src="all-five-resources.svg">'
 if (O/'K01-K05-comparison-60s.mp4').exists():
  figures+='<h2>五组总览</h2><p><a href="K01-K05-comparison-60s.mp4">打开五组同步60秒视频</a> · <a href="same-frame-face-sheet.jpg">六个同刻画面</a></p><details><summary>查看8—14秒嘴部对比GIF（6秒、无声）</summary><img loading="lazy" style="width:100%;height:auto" alt="五组同一段嘴部动作，8到14秒" src="mouth-comparison-08s-14s.gif"></details>'
 if (O/'mouth-comparison-silent-tail.gif').exists():figures+='<details><summary>查看57.35—60秒静音闭口GIF（无声，10FPS）</summary><img loading="lazy" style="width:100%;height:auto" alt="五组句尾静音口型" src="mouth-comparison-silent-tail.gif"></details>'
 (O/'index.html').write_text(template.replace('__FIGURES_HTML__',figures).replace('__BENCHMARK_JSON__',json.dumps(data,ensure_ascii=False).replace('</','<\\/')),encoding='utf-8')
 def number(row,key,d=2):
  v=row.get(key);return f'{v:.{d}f}' if isinstance(v,(int,float)) else '待实测'
 lines=['# 女A K01—K05：同源 60 秒口型模块横评','',f'更新时间：{date}', '', '**状态：'+('五组录播均已完成文件验证。' if complete else '准备 / 运行中；这不是一份已完成的五组测评。')+'**','', '## 比较表','', '| 编号 | 方案 | 状态 | 60秒生成耗时(s) | RTF | FPS | 冷启动(s) | 含初始化总耗时(s) | PyTorch峰值显存(MiB) |','|---|---|---|---:|---:|---:|---:|---:|---:|']
 for row in items:
  state='验证通过' if row.get('verified') else ('待验证' if row.get('ok') else ('失败' if row.get('error') else '未运行'))
  lines.append('| '+' | '.join([row['id'],row['name'],state,number(row,'render_wall_seconds'),number(row,'render_rtf'),number(row,'render_fps'),number(row,'cold_load_seconds'),number(row,'total_with_load_seconds'),number(row,'torch_peak_allocated_mib',0)])+' |')
 lines+=['','这些是不同共享负载窗口下的首轮实测，不是独占GPU速度排名。冷启动入口的加载/缓存/预热边界也不同；请结合阶段耗时、线程限制与资源曲线判断。']
 if complete:
  fastest=min(items,key=lambda r:r['render_wall_seconds'])
  lines+=['','## 本轮选型判断','',f"本轮最短的完整60秒生成来自{fastest['id']}，耗时{fastest['render_wall_seconds']:.2f}秒。五个入口的RTF均大于1；在这套原生共享负载、CPU线程与读图/融合实现下，没有一组证明完整离线生成已快于实时。它不等于生产常驻worker的速度，也不能否定各项目在其他数据和官方环境中的能力。",'', '当前优先保留K01作为对照、把K02作为下一轮局部优化回归候选。K03完成了合成教师初训，但仍有静音微张嘴和较柔的嘴部细节；K04细节更软；K05本次适配在多个发声画面中口型偏弱，且生成耗时很长。后两者当前结果不构成直接替换生产口播的依据。完整视觉观察与原片在后文。', '', 'K03峰值CUDA分配实测约8.8GiB，不能用约22MB视觉模型权重推断其完整运行显存；本报告保留真实峰值，未将未经单独实验的原因当成定论。人物专模、HuBERT、预处理和实际批次/运行时开销必须分别看待。']
 if not complete and any(x.get('ok') for x in items):
  lines+=['','## 当前阶段观察（五组尚未完成）','', '已有录播来自其他项目运行期间的共享资源环境，不能把时长直接解释为算法的独占GPU排名。K01/K02的融合计时包含原图与口罩读取、解码；K04音频特征阶段包含首次librosa数值库初始化。','', '同刻截图中，K04的嘴部和牙齿边缘比K01/K02更模糊，符合96像素中间口型贴回大画面的限制；这是一项视觉观察，不是自动质量分数。仍需看完整原片做选择。','', 'K04初次加载发现当前LiveTalking内置网络结构与原GAN权重不匹配。本轮已改用原作者96像素结构，严格加载全部权重后完成测试；首次失败证据保存在attempts/，没有用忽略权重键的方式继续推理。']
  if (O/'first-run-stage-times.svg').exists():lines+=['','![已完成三组的首轮阶段耗时](first-run-stage-times.svg)','','![对应资源采样](first-run-resources.svg)']
 if complete and (O/'all-five-stage-times.svg').exists():lines+=['','![五组阶段耗时](all-five-stage-times.svg)','','![五组实际资源曲线](all-five-resources.svg)']
 lines+=['','## 固定输入与实验边界','', '- 原人物：女A / 林知夏；宿舍、手部、身体动作沿用既有 10,000 帧素材库。','- 测试为 720×1280、25 FPS、1,500 帧、60 秒。八个动作片段按同一顺序组合，不用新视频替换身体和场景。','- 所有模型使用同一份 O07 原始 WAV；保留句间停顿，不对语音变速，不截断完整测试句子。以 audio/input.json 和 input-manifest.json 的最终 SHA-256 为准。','- 主测试关闭 BGM、滤镜和网页覆盖层；不调用云端视频、口型或 TTS 推理。','- 测试是离线录播生成；不启动 B站公共直播，不以此证明平台互动链路的首响或端到端延迟。','- 全部使用原生 Windows / Python；没有 Docker、WSL 或虚拟机。','', '## 每组替换范围','', '| 编号 | 实际替换 | 口型尺寸与强度 | 保留 / 说明 |','|---|---|---|---|','| K01 | 既有 MuseTalk 1.5 | FP16、batch 8、256级面部预测 | 原生产融合口罩 |','| K02 | K01 的后处理消融 | 相同网络/权重/精度/batch | 下半脸椭圆羽化、有限颜色校正、静音渐变；不是一个独立新模型 |','| K03 | FeatherTalk 人物专模 | 原144×144模型、FP32、batch16、60轮初训 | 独立动作 + 独立台词的 K01 教师合成训练；实验版，不能代表真实人物训练的质量上限 |','| K04 | Wav2Lip GAN | 原96×96网络、FP32、batch16 | 使用既有坐标、原80-bin mel输入；公开权重为非商业研究用途 |','| K05 | LatentSync 1.6 | 原512、16帧块、20 DDIM步、CFG1.5、FP16 | Windows dlib几何适配替换InsightFace检测，保留原仿射/网络/采样强度；复用既有VAE |','', 'K02—K05 最终合成均约束在同一原画面的下半脸区域；K01 保留生产融合规则作为基线。K03 的人物预处理和训练时间单列，绝不合并到每次 60 秒推理耗时中隐藏。','', '## 指标口径','', '- **冷启动**：模块导入后开始加载网络、头像缓存与适用的预热，至可执行测试前；不包括下载和安装。各结果记录精确边界。','- **生成耗时**：进入该模型本次音频特征处理至最终 60 秒 MP4 编码关闭的墙钟时间，包括读图、推理、融合、编码阻塞及编码收尾。K05 额外列出源视频准备成本。','- **RTF** = 生成耗时 / 60，**FPS** = 1500 / 生成耗时。二者是本次离线吞吐，不是观看帧率或直播延迟。','- **首帧**：开始处理后第一张可编码口型帧的时间；不含模型冷启动。K05 官方批处理没有流式首帧，因此留空。','- **PyTorch峰值显存**：仅本次进程的 CUDA 分配/保留峰值；整卡显存、利用率、功耗为 nvidia-smi 1秒采样，包含用户的其他任务。','- 系统内存、进程RSS和CPU同样保留采样。保留其他项目/ComfyUI任务意味着这些结果不是独占GPU的极限跑分，需结合资源曲线看波动。','- K01/K02 提供约200ms右侧音频上下文，K04约200ms，K03约400ms；K05为离线批处理。吞吐快于实时仍需考虑算法前看、队列、音频分句、传输和播放器缓冲。','- 不伪造 SyncNet/LSE/人工质量分数。原始视频、同刻截图与网页并排播放用于人工比较；脸部帧差只描述运动，不代表口型正确性。','', '## 验收规则','', '1. 解码完整MP4，逐项确认1,500帧、25FPS、720×1280和60秒时长；禁止用截短、静帧循环冒充60秒口播。','2. 校验共用音频SHA。对最终AAC解码后与原WAV做相关校验，相关系数需>0.98，音频偏移绝对值<20ms。','3. 每秒抽样比较脸部允许区域以外的原图，平均像素误差阈值为3，容许统一H.264有损编码误差。','4. 每组保存六个同一帧号的全景截图，并保留完整的性能与资源JSON；失败必须显示错误原因。','5. 最后由观看者比较闭唇、牙齿、嘴角、颜色边界、动作稳定性。个人评分保存在浏览器，独立于测评原始记录。','', '## K03 训练与公平性','', '使用现有动作库中未参与60秒测试的其余40个动作片段，共8,000帧/320秒；训练台词与测试台词分开。K01生成带口型教师帧，FeatherTalk原110点预处理和FeatherHuBERT提取特征，以原损失默认权重训练60轮。Windows数据加载为num_workers=0。记录种子、每轮损失、训练时间、权重哈希和资源采样。','', '这解决了当前只有原始无声动作素材、缺少真实人物口播训练视频的问题，但训练标签带有MuseTalk误差，因此K03结果只适用于这一套合成教师训练试验。需要真人真实说话视频进一步训练时，应作为新实验独立归档。','', '## 文件索引','', '- `protocol.md`：原生环境、资源调度、复现和指标细则。','- `index.html`：本地同源对比页面，含同步播放、嘴部放大、按生成耗时/RTF/显存排序。','- `K01/`—`K05/`：60秒MP4、result.json、resources.json、verification.json、六张同刻截图。','- `audio/`：60秒原始WAV、逐句O07原始生成与时间轴。','- `input-manifest.json`：动作编号、帧序列、音频哈希和训练/测试分离声明。','- `training/`、`K03/training*.json`：人物训练来源与过程；训练权重属于模型目录，不进入Git。','- `results.json`、`results.csv`、`verification-summary.json`：可复核数据。','', '## 待完成与失败项目','']
 for row in items:
  if not row.get('verified'):lines.append(f"- {row['id']}："+(str(row.get('error')) if row.get('error') else ('已经生成，待文件验证。' if row.get('ok') else '尚未启动或尚未生成结果文件。')))
 if complete:lines.append('五组文件验证均完成；主观选型请结合原始录播。')
 if complete:
  lines+=['','## 逐阶段实测（秒）','','| 编号 | 音频特征 | 口型网络/VAE | 额外读图预处理 | 仿射对齐 | 扩散解码 | 面部还原 | 最终融合 | 编码阻塞 | 源视频准备 |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
  for row in items:lines.append('| '+' | '.join([row['id']]+[number(row,k) if k in row else '不适用/未分拆' for k in ['feature_seconds','inference_seconds','read_preprocess_seconds','affine_transform_video_seconds','decode_latents_seconds','restore_video_seconds','blend_seconds','encoder_backpressure_seconds','source_prepare_seconds']])+' |')
  lines+=['','“未分拆”不等于零成本；该开销包含在总墙钟或其父阶段。K01/K02网络计时含VAE解码，K05分拆扩散解码。K05源视频准备在生成主计时前，已包含在含初始化总耗时中。各入口冷启动的导入/预热边界不同，不能把冷启动数字视为统一的纯网络加载对照。']
 if complete:
  stage_names={'feature_seconds':'音频特征','inference_seconds':'口型网络 / VAE','read_preprocess_seconds':'额外读图 / 输入预处理','affine_transform_video_seconds':'仿射对齐','restore_video_seconds':'面部还原','vae_encode_seconds':'VAE编码','decode_latents_seconds':'扩散解码','blend_seconds':'读图 / 解码 / 最终融合','encoder_backpressure_seconds':'编码阻塞','render_resource_wait_seconds':'显式资源等待'}
  lines+=['','## 这次执行的主要瓶颈','','| 编号 | 最大已计时阶段 | 秒 | 占生成墙钟 |','|---|---|---:|---:|']
  for row in items:
   measured=[(title,row[key]) for key,title in stage_names.items() if isinstance(row.get(key),(int,float))]
   measured.append(('其他准备 / 未单独拆分',max(0,row['render_wall_seconds']-sum(v for _,v in measured))))
   title,seconds=max(measured,key=lambda pair:pair[1]);lines.append(f"| {row['id']} | {title} | {seconds:.2f} | {100*seconds/row['render_wall_seconds']:.1f}% |")
  lines+=['','这张表按本次入口的计时边界解释墙钟，不能把CPU贴回、原PNG读取或后台等待都算成GPU网络推理。K01/K02的读取、解码和融合为同一计时段；后续可单独检查原帧/口罩缓存、有限预取及CPU贴回，以新实验记录收益。阶段耗时小于60秒也不代表整条直播链路已经实时。K03的人物训练成本与K05的整段扩散成本需结合实际使用频率判断；选择替换前，还需在现有音频分句、播放时钟、B端接收和平台推流中另做实时回归。']
 lines+=['','## 首帧和初始化边界','','| 编号 | 处理开始至首张可编码帧 / 秒 | 边界 |','|---|---:|---|']
 for row in items:
  if not row.get('ok'):continue
  lines.append('| '+row['id']+' | '+number(row,'first_frame_seconds')+' | '+('本入口未提供流式首帧，不据分块完成时间推算' if row['id']=='K05' else '不含冷加载；含本入口特征提取、首批网络与输入处理')+' |')
 lines+=['','冷启动数字不覆盖整个进程启动。K01/K02和K04的部分模块导入发生在计时前；K03/K05的导入更多发生在入口内。冷启动加生成耗时也可能小于入口总耗时，差额来自两段计时外的输入、清单、编码器或其他准备。原始时长不做回填或修正。网页同步播放器只用于比较已生成文件，首帧指标不包含网络传输、网页缓冲或直播平台CDN。','', '七张同刻截图（含网页首帧海报）从最终交付MP4重新解码，源文件签名与帧号保存在各组stills/source.json；不是将编码前缓存当作最终文件截图。']
 lines+=['','| 入口 | 冷启动段中的预热 / 额外边界 |','|---|---|','| K01/K02 | 生产load_model/load_avatar和batch8 warm_up在冷启动内；主要模块导入更早发生 |','| K03 | 上游融合后模型加载、权重哈希、HuBERT加载与batch16视觉模型零输入预热在冷启动内；完整语音特征另计 |','| K04 | 原网络权重加载与batch16零输入预热在冷启动内；librosa导入更早发生，首次实际音频特征处理另计 |','| K05 | 权重加载及CUDA同步在冷启动内，未另做完整20步UNet预热；首次扩散执行成本保留在生成主计时 |','','若后续集成为常驻直播worker，模型可在开播准备时加载；本次每个独立录播入口的冷启动不等于每条弹幕都必须重复支付的成本。常驻并不会自动消除PNG读取、融合、音频分句和播放缓冲开销。']
 training=read(O/'K03/training.json',{});preprocessing=read(O/'K03/preprocessing.json',{})
 if training.get('ok'):
  teacher=read(O/'TRAIN/metadata-correction.json',{});raw_teacher=read(O/'TRAIN/result.json',{})
  lines+=['','## K03一次性构建成本','','| 环节 | 实际记录 |','|---|---|',f"| 320秒/8000帧教师素材 | 生成{raw_teacher.get('render_wall_seconds',0):.2f}秒；含加载{raw_teacher.get('total_with_load_seconds',0):.2f}秒 |",f"| 原权重关键点与音频预处理 | 完成段{preprocessing.get('wall_seconds',0):.2f}秒，{preprocessing.get('device','见原始记录')}；此前重试保存在attempts/ |",f"| 人物训练 | 请求60轮；本次训练入口总墙钟{training['wall_seconds']:.2f}秒；各轮详见training-history.json |",f"| 训练过程整卡显存峰值 | {training.get('gpu_total_used_mib_peak',0):.0f}MiB，含当时其他进程 |",f"| 独立推理权重 | {training.get('inference_checkpoint_bytes',0):,}字节，已从原最终模型导出，未包含优化器状态 |",'', '训练曲线描述原教师标签上的拟合过程，不是口型同步质量分。CPU批处理仍使用原SCRFD/PFLD权重和裁剪规则；十帧对照关键点差异为0像素，见preprocess-backend-check.json。最初教师帧的汇总标签问题使用TRAIN/metadata-correction.json公开纠正；原测量与原记录保留。']
  if (O/'K03-training-curves.svg').exists():lines+=['','![K03实际训练曲线](K03-training-curves.svg)']
 invocations=read(O/'K03/training-invocations.json',{})
 if invocations:
  attempts=invocations.get('prior_attempts',[]);boundaries='、'.join(str(a['completed_epochs']) for a in attempts)
  lines+=['','### 续训和失败成本','',f"本轮在已完成第{boundaries}轮的检查点后，共发生{len(attempts)}次Windows进度JSON替换被拒绝的入口退出。先增加唯一临时文件及有限重试，第二次后进一步将progress.json降为尽力而为的进度遥测，写入受阻时保留独立后备快照而不中止训练；检查点、训练历史和成绩仍为严格写入。只重载本实验的静态预览服务，使小JSON读完即关闭磁盘句柄，不重启MCP、设备或模型服务。",'', '每次均从原检查点恢复模型、优化器和轮次；已完成轮次保留，没有改为提前停止。失败证据与原资源序列归档到attempts/。实际Win32只读共享句柄回归检查验证了临时进度失败不会中断调用，正式成绩写入仍等待锁释放；具体持锁方未被确定，不能把它断言为某个其他项目的故障。', '', f"此前失败训练阶段墙钟合计{invocations['prior_failed_stage_wall_seconds']:.2f}秒；最终续训入口墙钟{invocations['current_entry_wall_seconds']:.2f}秒；两部分合计{invocations['aggregate_measured_training_wall_seconds']:.2f}秒。合计未包含各次启动之间的人工修复间隔，失败阶段包含suite包装与发布开销，不能当成纯GPU优化器时长。",'', '原上游检查点不保存全部Python/NumPy/CUDA随机数状态；续训入口重新设seed20261028。它是有记录的60轮续训实验，不宣称与一次不间断运行逐位一致。此前中断轮中已执行但未入检查点的批次会在恢复后重新执行。详见K03/training-attempts.json与K03/training-invocations.json。']
 inventory=read(O/'model-file-inventory.json',{}).get('files',[])
 if inventory:
  def select_bytes(names):
   found=[f for f in inventory if f['path'].replace('\\','/').split('/')[-1] in names]
   return sum(f['bytes'] for f in found),{f['path'].replace('\\','/').split('/')[-1] for f in found}
  lines+=['','## 实际新增权重与额外磁盘成本','','以下按真实文件stat记录计算，GB为十进制。K01/K02复用生产权重；环境、头像缓存、原始训练数据和可续训检查点另计。','','| 编号 | 新增推理权重 | 一次性预处理权重 | 说明 |','|---|---:|---:|---|','| K01 | 0GB | 0GB | 复用现有MuseTalk与预处理 |','| K02 | 0GB | 0GB | 相同网络，不导出新engine |']
  for label,names,prep,note in [('K03',{'inference.pth','feather_hubert.pth'},{'checkpoint_epoch_335.pth.tar','scrfd_2.5g_kps.onnx'},'另需574,673,361字节VGG19仅用于训练；续训检查点含优化器，未计入推理权重'),('K04',{'wav2lip_gan.pth'},set(),'原GAN权重，96像素'),('K05',{'latentsync_unet.pt','tiny.pt'},set(),'复用既有334,707,217字节VAE，不重复下载')]:
   size,found=select_bytes(names);aux,_=select_bytes(prep);text=f'{size/1e9:.6f}GB' if names<=found else '待完整文件统计'
   lines.append(f'| {label} | {text} | {aux/1e9:.6f}GB | {note} |')
  lines+=['','完整路径/字节与VAE哈希见model-file-inventory.json，选定下载的SHA256见setup-progress.json。库结构匹配不替代来源记录；K05使用既有VAE及dlib几何适配，应与原生官方检测器实验区分。']
 for row in items:
  if row.get('execution_adapter'):
   lines+=['','## '+row['id']+'实际执行适配','',row['execution_adapter']+'。原口型模型的分辨率、精度、窗口、扩散步数和CFG没有降低；这属于当前素材/共享资源下的执行实现，不能用其速度冒充官方未经修改的整段视频入口。','',f"本次资源等待总计{row.get('resource_wait_seconds',0):.2f}秒；生成主阶段内等待{row.get('render_resource_wait_seconds',0):.2f}秒，实际处理墙钟（扣除显式等待）{row.get('render_active_seconds',0):.2f}秒。表格主耗时包含生成阶段内等待。",'', 'K05直接分块读取同一组原始PNG，保留连续的仿射平滑状态、固定初始噪声、原音频特征和原20步DDIM更新。VAE仅沿独立图像批次切片；实际权重驻留方式见上面的execution adapter。mmap/meta初始化严格核验所有权重键与形状，不做部分权重加载。']
   if row['id']=='K05' and row.get('ok'):lines+=['',f"音频编码器产生{row.get('available_audio_feature_frames','见原始记录')}个特征帧，本实验取前1,500个，与60秒固定源帧逐一对齐；共94块，前93块各16帧，末块12帧。不会追加或循环额外视频帧。该尾部处理属于执行适配，不能宣称与官方按全部音频特征输出的尾块逐像素相同。"]
 if (O/'K01-K05-comparison-60s.mp4').exists():lines+=['','## 同步观看素材','','[五组同步60秒总览](K01-K05-comparison-60s.mp4) · [8—14秒嘴部GIF，6秒无声](mouth-comparison-08s-14s.gif) · [六个同刻人脸截图](same-frame-face-sheet.jpg)','','总览是五段真实测试视频的同步拼接，不能替代单个720×1280原片。GIF仅为局部预览，不代表60秒完整录播。']
 if (O/'mouth-comparison-silent-tail.gif').exists():lines+=['','[57.35—60秒句尾静音闭口GIF（无声，10FPS量化）](mouth-comparison-silent-tail.gif)；该区间共用WAV样本全为0，可独立检查没有声音时的闭口行为。']
 if (O/'review-notes.md').exists():lines+=['','## 成片人工观察','',(O/'review-notes.md').read_text(encoding='utf-8')]
 lines+=['','## 素材适配与官方来源','','| 编号 | 当前素材适配 | 固定来源 |','|---|---|---|','| K01/K02 | 既有LiveTalking的MuseTalk1.5裁脸与latent缓存；K02仅改后处理 | [MuseTalk](https://github.com/TMElyralab/MuseTalk)、[LiveTalking](https://github.com/lipku/LiveTalking)；本机入口快照随实验代码保留 |','| K03 | 原SCRFD/PFLD110点、152像素裁剪与144像素网络；训练素材为独立合成教师集 | [FeatherTalk固定commit](https://github.com/anliyuan/FeatherTalk/tree/7a8bb0439eb5da5e10601168df329a7052b7edf3) |','| K04 | 复用既有MuseTalk人脸坐标裁96像素输入，未重新使用原SFD检测/默认padding；属于素材适配结果 | [原Wav2Lip结构](https://github.com/Rudrabha/Wav2Lip)、[已校验GAN权重镜像](https://huggingface.co/camenduru/Wav2Lip/tree/bfcd9263d1ccb60ab724f074e7c1b3555f6cb162) |','| K05 | dlib几何锚点、分块原PNG读写、原仿射/口罩/扩散模型、VAE独立批次切片 | [LatentSync固定commit](https://github.com/bytedance/LatentSync/tree/a229c3948406bc2cf6eaf4873e662e70c6a04746)、[1.6固定权重](https://huggingface.co/ByteDance/LatentSync-1.6/tree/c42c7e6c8e9c213626389fa7d9a3c444b8536353) |','', '这些结论用于当前女A素材上的局部模块选型，不能代表每个项目使用官方最佳训练数据、检测器和独占硬件时的质量上限。正式直播的O07/F07、DSH、房间管理和B端推流未因这轮离线实验自动切换。']
 hardware=read(O/'benchmark-hardware.json',{})
 if hardware:
  lines+=['','## 实机与调度记录','','| 项目 | 本次快照 |','|---|---|',f"| GPU / 驱动 / 总显存MiB | {hardware['gpu_name_driver_vram_mib_csv']} |",f"| CPU | {hardware['cpu_name']}；{hardware['physical_cpu_cores']}核/{hardware['logical_cpu_threads']}线程 |",f"| 物理内存 | {hardware['physical_ram_gib']:.2f}GiB |",f"| 系统 | {hardware['platform']}，原生Windows |",'| 本任务GPU并行数 | 1；不停止其他项目 |','| 编码CPU线程 | 4 |','','硬件快照见benchmark-hardware.json；共享任务影响由各组逐秒resources.json记录。PyTorch线程限制为K01/K02/K03推理/K04各1线程，K03训练和预处理/K05各2线程，以保留其他项目的CPU空间；这也是复现吞吐的条件。','','| 编号 | 进程显存分配/保留峰值MiB | 进程RSS峰值MiB | 整卡GPU均值% | 整卡显存峰值MiB | 系统RAM峰值MiB |','|---|---:|---:|---:|---:|---:|']
  for row in items:
   if row.get('ok'):lines.append('| '+' | '.join([row['id'],number(row,'torch_peak_allocated_mib',0)+' / '+number(row,'torch_peak_reserved_mib',0),number(row,'process_rss_mib_peak',0),number(row,'gpu_util_percent_mean',1),number(row,'gpu_total_used_mib_peak',0),number(row,'system_ram_used_mib_peak',0)])+' |')
  lines+=['','整卡GPU/显存和系统RAM包括其他项目，不能当作该算法的独占消耗。RSS只统计Python主进程，未包括FFmpeg子进程。']
 lines+=['','## 同源台词与动作时间轴','','下列时间来自实际音频索引与冻结素材清单；网页可点击台词时间跳到对应画面。每8秒的动作切换来自同一份源素材，需与模型造成的局部抖动区分。','','| 台词编号 | 时间 / 秒 | 实际测试台词 |','|---|---:|---|']
 for segment in timeline['speech']:lines.append(f"| {segment['id']:02d} | {segment['start_seconds']:.2f}–{segment['end_seconds']:.2f} | {segment['text']} |")
 lines+=['','| 时间 / 秒 | 源动作 | 素材编号 |','|---:|---|---|']
 for clip in timeline['motion']:lines.append(f"| {clip['timeline_start_seconds']:.2f}–{clip['timeline_end_seconds']:.2f} | {clip['title']} | `{clip['id']}` |")
 lines+=['',f"最后一段台词在{timeline['silence_start_seconds']:.2f}秒结束；其后的静音用于观察句尾闭口。"] if timeline['silence_start_seconds'] is not None else []
 (O/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 from render_report import render_report
 (O/'report.html').write_text(render_report('\n'.join(lines)+'\n'),encoding='utf-8')
 guide=['# 女A K01—K05口型横评 / Review bundle','', '**'+('五组60秒原片已完成文件验证。' if complete else '测试进行中；仅已生成并通过验证的项目有完整成绩。')+'**','', '在线：<http://192.168.196.209:8035/>；本机：<http://127.0.0.1:8037/>。','', '- [完整HTML测评](report.html) / [原始Markdown](report.md)','- [复现、调度与指标协议 / Reproduction and measurement](protocol.md)','- [原始表格CSV](results.csv) / [原始数据JSON](results.json)','- [同源60秒PCM WAV](audio/common-60s.wav) / [台词与逐句原音索引](audio/input.json)','- [交付文件大小与SHA256清单](delivery-manifest.json)','', '对比网页可选择任意两组同步播放、放大嘴部、拖动到相同时刻，并按生成耗时/RTF/显存排序。个人评分保存在浏览器，独立于原始数据。','', '## 在其他原生系统打开 / Portable viewing','', '需要Python3.10或更新版本；不需要第三方包、Docker、WSL或GPU。保持整个目录结构，在本目录执行：','', '```powershell','python viewer_server.py --port 8037','```','', '访问 <http://127.0.0.1:8037/>。若端口已被占用，用`--port 8039`并访问对应地址；不要终止已有服务。','', 'The standalone viewer is read-only, binds to loopback by default and supports HTTP byte ranges. Copy the complete directory without flattening it. The bundle contains the five portrait files when completed, original speech, observed measurements and review materials. Large model installations and the8,000-frame training image cache remain on the4090 and are referenced by hashes/paths; they are not included in the delivery total.','', 'No PDF or compressed archive is produced. Offline rendering throughput is not live-stream latency. K03 is a synthetic-teacher identity-training pilot; K05 uses the documented native adapter. This experiment does not change the production stream.']
 (O/'README.md').write_text('\n'.join(guide)+'\n',encoding='utf-8')
 files=[p for p in O.rglob('*') if p.is_file()];size={'files':len(files),'bytes':sum(p.stat().st_size for p in files),'includes_training_cache':(O/'training').exists(),'compressed_archive':False,'pdf':False};(O/'package-size.json').write_text(json.dumps(size,indent=2),encoding='utf-8')
 print(json.dumps({'complete':complete,'verified':sum(x['verified'] for x in items),'size':size},ensure_ascii=False))
if __name__=='__main__':main()
