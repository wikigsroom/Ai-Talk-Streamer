# 对口型与面部控制选型：2026-10-28

当前建议：以现有 MuseTalk 1.5 为基准，先改善嘴部融合和素材质量；新后端首先评测 SoulX-FlashHead Lite，其次 Ditto；LivePortrait 先用于离线表情模板。已按用户要求补充 SoulX-FlashTalk 及相似流式项目，清单共 22 项。此文是源代码检查与第一方资料评估，**替代模型尚未在本项目跑分，表中没有将官方 FPS 当成本机成绩**。

[现有直播间管理](../live-room/README.md) · [本轮实测](../live-room/ACCEPTANCE.md) · [机器可读清单](lipsync-options.json) · [CSV表格](lipsync-options.csv) · [模型磁盘预算](AVATAR_MODEL_STORAGE_20261028.md) · [流式方案调优设计](STREAMING_AVATAR_TUNING_20261028.md)

## 当前实际链路

已读取 A4090 的运行配置、GPU worker、已安装模型加载器与 Whisper 特征代码，而不是只看仓库名称：

| 项目 | 核对结果 |
| --- | --- |
| 模型 | **MuseTalk 1.5**；加载器默认 `models/musetalkV15/unet.pth` 和 `musetalk.json`；权重文件 3,400,074,924 字节 |
| 精度/批量 | UNet、VAE、位置编码 FP16；batch 8；独立原生 GPU worker；cuDNN benchmark 已开启 |
| 图像生成 | 预处理的人脸 latent → 音频条件 UNet → VAE 解码 → 缩放/遮罩融合回源帧 |
| 音频条件 | O07 主用/F07 备用本地 TTS → 16 kHz 人物链路 PCM → Whisper 音频特征；Whisper 在这里用于特征提取，不是先做语音转文字 |
| 素材 | `student_dorm_motion_bank_v3`，女A日光宿舍、48 段动作素材；latent 和遮罩预处理复用 |
| 最终输出 | 720×1280、25 FPS，经 H264/NVENC + PCM 到 B；B 四秒缓冲、软件解码、官方直播姬节目素材 |
| 实际动作能力 | 嘴部跟随声音；眼睛、头姿、身体和手势主要来自预制视频，不具备随每句话自由生成动作的能力 |

MuseTalk 官方说明人脸区域为 256×256，因此 720×1280 竖屏输出不意味着嘴部以 720p 原生生成；模型也有唇形、颜色等身份细节保留限制。[官方说明](https://github.com/TMElyralab/MuseTalk)

最近五段 A→B 测试平均 24.991 FPS、最低 24.650 FPS，欠载/丢包/解码错误增量为零；这说明该轮播放连续性通过，不证明视觉口型偏移或牙齿细节已经达到最佳。人物 worker 的 75 次 render 合计 12.330 秒，平均每批约 164.4 ms，另有特征提取、CPU 融合、IPC、编码与缓冲；不能把 render 单项倒数写成全链路 FPS。[真实验收](../live-room/ACCEPTANCE.md)

## 可直接优化的部分

| 优化项 | 要解决的问题 | 建议实施/评测方法 | 风险和边界 |
| --- | --- | --- | --- |
| 人脸 ROI 与素材筛选 | 脸太小、侧转、手遮嘴时，嘴部细节不足或融合露边 | 按正面/轻转头/遮挡分类，逐段检查 bbox、mask、唇色和下巴；保留可追溯的重建缓存 | 不能仅放大 256 输入就声称提升模型原生分辨率 |
| 遮罩融合与时间稳定 | 嘴周亮度跳变、唇色变化、边缘闪烁 | 比较遮罩边缘、颜色匹配与时间稳定；对 ROI/融合权重做平滑，避免直接平均嘴部画面 | 直接平滑生成帧可能拖影并破坏闭唇瞬间 |
| 静音与句尾闭口 | 停顿仍张嘴、句末突然回到静止帧 | 保留真实语音尾部，按 valid samples 与停顿状态平滑回闭口素材；严格保留取消围栏 | VAD 仅帮助分段，不能用音量直接替代音素口型 |
| 动作与表情调度 | 说话、倾听、感谢之间动作重复或切换突兀 | 依据 DSH 已提交的说话/倾听/礼物事件选动作，限制头姿差和最短停留；由模板控制微笑/眨眼 | LLM 只能给有界意图，不能每帧产生任意坐标；手势仍由素材承担 |
| 启动/句间调度 | 首批等待、TTS 结束后的重新分配开销 | 分别记录特征首批、UNet、VAE、融合、IPC、编码；评估保留工作区、条件化 warm-up/cache 清理 | 现有预热和显存隔离已实施，进一步减少清理须验证 O07/F07 共驻留，不应直接删保护 |
| 小批量/缓冲实验 | 降低首帧积累和播放等待 | batch 8 为基准，对照 batch 4；B 缓冲从 4000 分阶段试 3000/2000 ms，比较 P95、欠载与恢复 | 降 batch 会降低吞吐，降缓冲会增加网络抖动影响；当前默认不改 |
| 图优化/后端加速 | 降低真正的 UNet/VAE 渲染耗时 | 固定 shape 下单独测 ONNX/TensorRT 或可用的原生编译路径，保留 FP16 输出对照 | Windows 插件/算子兼容性和数值漂移需验证，不预设能加速多少 |
| 轻量修复 | 牙齿/嘴部细节的可观看性 | 若确有收益，只对 ROI 做受限增强，对比纹理闪烁与身份保持 | 不默认叠加重型超分；可能增添假牙、过锐和延迟 |

当前已经是 1.5，因此“升级到 1.5”不能作为下一项优化。官方 `bbox_shift` 调节说明明确针对 1.0，不能把那套口型开合结论直接套到当前模型；当前应以实际预处理器和素材对照为准。[官方参数说明](https://github.com/TMElyralab/MuseTalk#use-of-bbox_shift-to-have-adjustable-resultsfor-10)

## 横向评测候选表

下列“可行性”是依据源码与官方环境推断；除 L00 外均待本项目实测。显存够用不等于原生 Windows 已安装，也不等于与 O07/F07 共驻留仍有同样速度。4090 的 48 GB 扩展显存不改变其计算吞吐。

| 编号 | 方案/官方来源 | 输入与能力 | 4090 48G / 实时判断 | 原生 Windows 和接入成本 | 预计新增模型磁盘 | 建议用途 |
| --- | --- | --- | --- | --- | --- | --- |
| **L00** | 当前 [MuseTalk 1.5](https://github.com/TMElyralab/MuseTalk) | 视频/图像 + 音频，重绘嘴部 | **已接入**，本轮 25 FPS 级节目播放 | 已运行；成本最低，复用 48 段素材 | 0 GB（已安装） | 必留基准组 |
| **L01** | MuseTalk 1.5 参数/融合/调度优化 | 同一模型，优化遮罩、素材、闭口与切换 | 高可行性；收益待实测 | 已有原生栈；改动少 | 0 GB（复用当前权重） | **第一优先**，先隔离视觉质量与系统延迟 |
| **L02** | [Ditto](https://github.com/antgroup/ditto-talkinghead) | 单图 + 音频，头部/表情，在线流式运动控制 | 官方面向实时；本机 FPS/共驻留未知 | 官方测试为 CentOS/A100/TRT8.6.1，另有 PyTorch；需 Windows 适配与重建 engine | 约 2.31 GB（PyTorch） | 实时替代主候选，成本中高 |
| **L03** | [SoulX-FlashHead Lite](https://github.com/Soul-AILab/SoulX-FlashHead) | 单图 + 音频，持续流式说话人像 | 官方单 4090 **96 FPS**；本项目未测，不含当前完整链路 | FlashAttention 等依赖需原生验证；替换人物生成后端，成本高 | 约 8.16 GB（Lite + LTX VAE + 音频编码器） | 实时新方案重点候选，观察脸部清晰度与长时漂移 |
| **L04** | [SoulX-FlashHead Pro](https://github.com/Soul-AILab/SoulX-FlashHead) | 同系列更重的人像生成 | 官方单 4090 **10.8 FPS**，未达本项目 25 FPS 门槛 | 同上且负载更高；48 GB 不会自动改善计算速度 | 约 6.92 GB（Pro + Wan VAE + 音频编码器） | 画质参考/离线素材，暂不作为单卡实时默认 |
| **L05** | [LivePortrait](https://github.com/KlingAIResearch/LivePortrait) + MuseTalk | 驱动视频/表情模板控制头姿、眼睛、嘴部，口型仍由 MuseTalk | 适合先离线建表情模板；实时级联需测耗时/冲突 | 官方有人像模式 Windows 入口；融合顺序和嘴部控制需设计 | 约 0.66 GB（人像模式） | **优先补表情**，眨眼/微笑/倾听，不直接当纯音频口型替代 |
| **L06** | [LatentSync 1.6](https://github.com/bytedance/LatentSync) | 视频 + 音频，512 分辨率扩散口型 | 官方推理最低 **18 GB**；48 GB 有容量余量，不能预设实时 | 上游脚本需原生依赖适配；可保留整段身体背景 | 约 5.2–5.6 GB；整包约 10 GB | 离线画质参考、重要片段精修 |
| **L07** | [FeatherTalk](https://github.com/anliyuan/FeatherTalk) / [Ultralight](https://github.com/anliyuan/Ultralight-Digital-Human) | 按角色训练的轻量口型，音频 + 专属模型/素材 | 轻量、适合低延迟；女A专属训练效果未知 | Ultralight 有 LiveTalking 入口，新 FeatherTalk 需适配；最大成本是干净对齐训练视频 | FeatherTalk 约 0.04–0.10 GB¹ | 固定女A长期运营的性能路线；现有静音动作不等同训练集 |
| **L08** | [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) | 视频 + 音频，经典嘴部替换 | 计算较轻，适合作速度基准，嘴部细节较旧 | LiveTalking 有后端；集成成本较低 | 约 0.53–0.60 GB（估算） | 研究对照；原始开放权重限制商业用途，不能直接作为商业直播默认 |
| **L09** | [EchoMimicV3-Flash](https://github.com/antgroup/echomimic_v3) | 图像/音频/多模态的人像及身体动画 | 官方称 8 步、12 GB、最高768²；不据此认定 25 FPS | 需原生依赖与长段拼接验证，成本高 | 约 20.75 GB（Flash-Pro + Wan 配套编码器/VAE） | 表情/上半身素材、离线自然度参考 |
| **L10** | [SadTalker](https://github.com/OpenTalker/SadTalker) | 单图 + 音频，3D 运动系数生成头动表情 | 单卡可尝试；官方原流程不是本项目实时后端 | 官方 Windows 入口；老依赖隔离，成本中 | 约 1.0–1.5 GB（估算） | 传统整脸动画对照，优先级较低 |
| **L11** | [SoulX-FlashTalk](https://github.com/Soul-AILab/SoulX-FlashTalk) | 14B，图像 + 音频，长时流式人物生成 | 官方 **32 FPS / 0.87秒启动为8×H800**；单卡需超过64GB，CPU卸载后约40GB；48G不代表实时 | FlashAttention / CUDA依赖须原生适配；当前没有单4090共驻留达标证据 | 约 54.79 GB（官方兼容权重组） | 流式架构参考、离线画质组，不替换正式直播 |
| **L12** | [fast-flashtalk](https://github.com/di-osc/fast-flashtalk) | 社区FlashTalk优化；A8W8、动态卸载、提示缓存 | 作者称4090约2倍相对加速、推荐24GB起；未给足以确认25FPS的绝对成绩 | GemLite、Triton、Flash/SageAttention是原生依赖门槛；流式音频编码还不等于实时帧回调 | 首次约 54.8 GB；复用 L11 约 0 GB² | 单4090 FlashTalk实验分支，先验证依赖/首帧/质量 |
| **L13** | [SoulX-LiveAct](https://github.com/Soul-AILab/SoulX-LiveAct) | 18B，长时人物动画，动作/情绪编辑、ConvKV | 官方双H100/H200约20FPS；消费卡卸载模式单5090约6FPS，不能推定4090达25FPS | SageAttention、vLLM、LightVAE等须原生适配；Blackwell FP4加速不能直接套4090 | 约 54.79 GB（官方兼容权重组） | 动作素材/离线表情参考，暂不作为实时主后端 |
| **L14** | [Alibaba-Quark LiveAvatar](https://github.com/Alibaba-Quark/LiveAvatar) | 14B，图像 + 音频，4步、块式长时生成 | 官方FP8支持48GB容量；45FPS来自多卡H800，未证明单4090实时 | 原生量化/编译/流式VAE需验证；还须测O07/F07共驻留 | 约 47.08 GB（基础 S2V + LoRA） | 高质量流式研究组，先做容量和吞吐门槛测试 |
| **L15** | [Hallo-Live](https://github.com/fudan-generative-vision/Hallo-Live) | 文本驱动，联合生成语音与视频 | 官方 **2×H200约20.38FPS / 0.94秒**；未有本机成绩 | 双流DiT与解码须重构接入；不直接消费既定O07/F07 PCM | 约 38.64 GB（推理必需权重组） | 联合生成架构参考，当前音色方案下优先级低 |
| **L16** | [FLOAT](https://github.com/deepbrainai-research/float) | 单图 + 音频，运动latent流匹配、7类情绪 | 官方测试Linux/A100/V100；没有据此可填的本机25FPS成绩 | 原生旧依赖隔离、流式/打断需适配；正脸分布限制 | 已知编码器约 1.64 GB + 主模型待核实 | 整脸/情绪研究对照；开放权重非商业许可 |
| **F01** | [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker) | 摄像头/视频 → 关键点、blendshape、头姿矩阵 | 轻量跟踪层；它本身不生成女A画面 | 可用原生/网页跟踪，需接 LivePortrait 或 3D rig | 约 0.00376 GB（3.76 MB） | 真人面捕、参数可视化、自动质量分析 |
| **F02** | [NVIDIA Audio2Face-3D SDK](https://github.com/NVIDIA/Audio2Face-3D-SDK) | 音频 → 面部动画/情绪参数，需要绑定3D角色 | 官方面向实时；总负载还包含3D渲染 | 官方支持 Win10/11、CUDA/TRT；需3D形象和渲染器，成本最高 | 约 0.78 GB；含情绪约 2.05 GB³ | 后续3D面控分支，不能直接替换照片视频中的嘴部 |
| **F03** | [PersonaLive](https://github.com/GVCLab/PersonaLive) | 图像 + 驱动视频/摄像头，流式人像表情迁移 | 有实时实现/TRT路径；12GB离线流式容量不代表本机实时吞吐 | 官方列有社区Windows入口；须接动作驱动，不能仅传TTS音频 | 约 15–17 GB（部分估算） | 面捕/表情迁移对照；README限定学术研究 |
| **F04** | [EditaLive](https://github.com/GVCLab/EditaLive) | PersonaLive后续项目；视频/摄像头的角色与全身编辑 | 官方FP8+快速VAE在H100上约31.4/38.4GiB；卸载更省显存，但无本机速度证据 | FlashAttention/FastVideo内核、原生Windows待适配；在线版本当前横屏 | 约 56.62 GB（官方脚本筛选的推理配套） | 离线身体动作/形象编辑参考；README限定学术研究 |
| **R01** | [StreamAvatar](https://streamavatar.github.io/) | 图像 + 用户/Agent双音频；说话/倾听与手势 | 官方928×704@25、双H800流水，含输入块延迟约1.20秒 | 本次未确认完整官方可部署推理代码与权重；不能列为已可安装选项 | 未公布/未确认，无法可靠估算 | 关注双向互动与身份锚定设计，待完整发布再排评测 |

磁盘列采用十进制 GB，以保留现有 MuseTalk/O07/F07 为前提，估算单独新增一项的权重及列明的配套模型；**不是显存占用，也不是包含 Python/CUDA 的完整安装目录**。已有的其他 ComfyUI 权重未逐项盘点，不预扣共享空间。公开文件大小相加仍属于安装前估算，实际下载选项与格式可能改变占用。[组件文件、版本、去重和估算细则](AVATAR_MODEL_STORAGE_20261028.md)

¹ FeatherTalk 是部署推理估算，女A模型尚未训练；预处理/训练文件另计，旧 Ultralight 编码器分支另算。² fast-flashtalk 与 L11 共用原始权重，A8W8 不代表下载自动减半。³ Audio2Face 的第二个数字包含可选情绪模型，3D角色和编译 engine 另计。FLOAT 的 1.64 GB 只是已知编码器，**不是总量**；未确认大小的项目不填零。

## 评测顺序与统一输入

推荐第一批 **L00、L01、L03、L02、L05**，再用L06作为离线质量参照。L12是第二批实验路线，先过原生依赖门槛；L07单列训练路线。L04/L09/L10/L11/L13/L14/L16适合离线或研究对照；L15会改变既定语音架构。F01–F04评测控制/驱动能力，不能把参数输出速度当成口型视频FPS；R01未确认完整部署发布，不计入可立即部署的候选数量。

SoulX系列不是同一模型换名字：FlashTalk是14B人物生成，FlashHead是面向消费卡的1.3B人像方案，LiveAct是18B动作与情绪路线。扩大显存只解决容量问题。官方离线演示、`--fps=25`输出参数、CPU卸载成功、两倍相对加速，都不能替代单4090连续25FPS的实测。

| 维度 | 统一执行规则 |
| --- | --- |
| 音频 | 同一 O07 原始 WAV，另加 F07 作为泛化；先固定 WAV 排除 TTS 差异。分 10/30/90 秒，包含 b/p/m 闭唇、f/v、圆唇、齿音、数字、停顿、笑声与中英混读 |
| 图像组 | 所有单图方案用同一女A锚点；视频重绘组用同一组源帧；既有身体视频与单图整脸生成分别评分 |
| 画幅 | 保存模型原生 face ROI/帧率，统一合成720×1280@25后再评观看效果；不能只写最终画幅冒充模型分辨率 |
| 时延 | 冷启动/热首帧、首段可播放时间、全段生成时长、RTF、取消至静音时间；纯推理和完整 A→B 延迟分别列 |
| 资源 | 同台 A4090、相同功耗/其他任务条件、原生环境；单独模型与 O07/F07 共驻留两种工况；记录峰值VRAM/RAM、GPU/编码占用 |
| 口型 | 同一 SyncNet/偏移估计工具 + 正常速度/慢放盲评；闭唇准确、同步偏移、牙齿/舌头、嘴周闪烁、身份保留；无真实GT时不得称为绝对误差 |
| 表情 | 眨眼、微笑、目光、点头、倾听、句末闭口、头身协调、长段漂移；主动控制和模型自动产生分列 |
| 流式稳定 | 10分钟连续交互、30次短回复、打断/重连/新代次，统计25FPS达标、欠载/丢包/错误，核对完整采样自然结束 |
| 人格接口 | DSH 只输出有界表情/动作意图，时间戳与 request/utterance/epoch/generation 一起传播；取消后旧表情和旧音频不能恢复 |
| 报告 | 每项保留输入SHA、代码/权重版本、原始音视频、参数、失败记录，未实测项留空；按首帧/全段耗时/峰值显存/人工质量提供独立排序 |

本次仅检查和列清单，未下载新权重、训练新角色或切换现有口型后端。所有后续评测继续使用原生 Windows，禁止 Docker/WSL，并保留 O07/F07 当前正式配置及历史测评。
