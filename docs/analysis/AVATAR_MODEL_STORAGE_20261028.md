# 对口型/面控模型的磁盘增量预算：2026-10-28

[完整22项方案表](LIPSYNC_OPTIONS_20261028.md) · [可排序CSV](lipsync-options.csv) · [方案JSON](lipsync-options.json) · [逐文件大小与版本](avatar-model-storage.json)

## 预算口径

这里统计**模型磁盘空间**，统一为十进制 GB（1 GB = 1,000,000,000 字节）。显存由运行精度、激活、缓存、分辨率和并发共同决定，不能从磁盘体积直接换算。没有下载新权重，也没有将候选方案当成已经完成部署。

假定保留当前 MuseTalk 1.5、O07 OmniVoice 和 F07 F5-TTS；每行是从这个基线单独新增一个候选的预算。L00/L01 为零表示复用已安装权重。其他 ComfyUI 缓存没有逐文件核对，不预先宣称“已有”。兼容的 SD VAE 等组件可在版本/哈希确认后共享，不能只凭文件名相同就删除副本。

不含 Python 环境、Torch/CUDA/TensorRT、编译 engine、下载中间文件、重复缓存、训练视频、动作库和生成结果；这些都可能另占显著空间。可执行测试前应以选定锁定版本的实际清单和磁盘可用量再核算，不把本表当成承诺的完整安装峰值。首次安装大型候选宜只装一项并关闭自动全仓下载，逐组件安排空间。

Hugging Face 文件大小通过公开仓库元数据查询，网络传输使用 hf-mirror.com；组件清单保留官方仓库ID、revision、文件路径、字节数和可获得的LFS SHA256，并链接官方页面。关键目录大小已与官方文件页交叉检查。这不是已下载文件的本地哈希校验。带“估算”的行存在未发布的角色模型、辅助依赖或当前无法核对的外部底模；上下界为空表示未知，不应参与“总量最小”的排序。

## 分项预算

| 编号 | 方案 | 预计新增模型磁盘 | 构成、共享与边界 |
| --- | --- | --- | --- |
| L00 | 当前 [MuseTalk 1.5](https://github.com/TMElyralab/MuseTalk) | 0 GB（已安装） | 现有 MuseTalk、Whisper、VAE 和人脸辅助模型继续保留；不是说模型本身体积为零。 |
| L01 | MuseTalk 1.5 参数/融合/调度优化 | 0 GB（复用当前权重） | 仅参数、素材筛选、融合与调度优化；若额外上增强模型应单列，不包含在此行。 |
| L02 | [Ditto](https://github.com/antgroup/ditto-talkinghead) | 约 2.31 GB（PyTorch） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 ONNX 是另一种约 2.53 GB 的路径；导出/重建 Windows TensorRT engine 会另占磁盘，不能直接复用上游 Linux 构件。 |
| L03 | [SoulX-FlashHead Lite](https://github.com/Soul-AILab/SoulX-FlashHead) | 约 8.16 GB（Lite + LTX VAE + 音频编码器） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| L04 | [SoulX-FlashHead Pro](https://github.com/Soul-AILab/SoulX-FlashHead) | 约 6.92 GB（Pro + Wan VAE + 音频编码器） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| L05 | [LivePortrait](https://github.com/KlingAIResearch/LivePortrait) + MuseTalk | 约 0.66 GB（人像模式） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 动物权重不计入，当前 MuseTalk 不重复计入。 |
| L06 | [LatentSync 1.6](https://github.com/bytedance/LatentSync) | 约 5.2–5.6 GB；整包约 10 GB | 推理主权重和 tiny 约 5.15 GB，另计裁脸模型；复用现有同版本 SD VAE 时减少约 0.33 GB。官方整仓含评测/训练辅助权重达 9.64 GB，加单格式 VAE 接近 10 GB，不是最小推理安装量。 |
| L07 | [FeatherTalk](https://github.com/anliyuan/FeatherTalk) / [Ultralight](https://github.com/anliyuan/Ultralight-Digital-Human) | FeatherTalk 约 0.04–0.10 GB¹ | 只估部署推理权重：已发布 FeatherHuBERT 13,480,913 字节 + 5.46M 参数视觉模型 FP32 原始参数约 21.84 MB；序列化/缓冲需余量。女A专属视觉模型尚未训练。预处理检测/关键点、训练检查点和数据另计；旧 Ultralight 的 WeNet/HuBERT 分支大小须按所选编码器重算，不能沿用此数字。 |
| L08 | [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) | 约 0.53–0.60 GB（估算） | 约 0.44 GB 主检查点 + 约 0.09 GB SFD 检测模型；不同 GAN/非 GAN 发布版本须逐文件确认。SadTalker 官方历史发布中的 wav2lip.pth 为 435,807,851 字节，仅作同类检查点体积参照；不将其伪称为本项目已安装的原始权重。 |
| L09 | [EchoMimicV3-Flash](https://github.com/antgroup/echomimic_v3) | 约 20.75 GB（Flash-Pro + Wan 配套编码器/VAE） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| L10 | [SadTalker](https://github.com/OpenTalker/SadTalker) | 约 1.0–1.5 GB（估算） | 官方 v0.0.2-rc 单个 256/512 检查点均为 725,066,984 字节，选一个；mapping 约 0.156 GB，另计裁脸/可选 GFPGAN。不要把旧版全部检查点和两种分辨率一起相加。 |
| L11 | [SoulX-FlashTalk](https://github.com/Soul-AILab/SoulX-FlashTalk) | 约 54.79 GB（官方兼容权重组） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| L12 | [fast-flashtalk](https://github.com/di-osc/fast-flashtalk) | 首次约 54.8 GB；复用 L11 约 0 GB² | 这是独立采用本方案的首次原始权重预算；若已下载 L11 且路径共用，新增原始权重约零。A8W8 是运行时量化路径，不自动缩小原始下载文件；若另存量化权重/编译缓存，须追加实测占用。 |
| L13 | [SoulX-LiveAct](https://github.com/Soul-AILab/SoulX-LiveAct) | 约 54.79 GB（官方兼容权重组） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| L14 | [Alibaba-Quark LiveAvatar](https://github.com/Alibaba-Quark/LiveAvatar) | 约 47.08 GB（基础 S2V + LoRA） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| L15 | [Hallo-Live](https://github.com/fudan-generative-vision/Hallo-Live) | 约 38.64 GB（推理必需权重组） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| L16 | [FLOAT](https://github.com/deepbrainai-research/float) | 已知编码器约 1.64 GB + 主模型待核实 | 编码器合计约 1.64 GB 是已知部分，不是总量。float.pth 的官方 Google Drive 入口可确认，但本次没有取得可靠文件大小；总量上下界保留空值，避免编造。 |
| F01 | [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker) | 约 0.00376 GB（3.76 MB） | 官方 face_landmarker.task 的 Content-Length 为 3,758,596 字节；不包含渲染角色或图像生成模型。 |
| F02 | [NVIDIA Audio2Face-3D SDK](https://github.com/NVIDIA/Audio2Face-3D-SDK) | 约 0.78 GB；含情绪约 2.05 GB³ | 选 v3 基础模型包约 0.777 GB，选配 Audio2Emotion ONNX 增加约 1.271 GB；不包含旧 v2 三个人物包、TensorRT engine、3D角色与渲染器。情绪权重需要接受官方访问许可。 |
| F03 | [PersonaLive](https://github.com/GVCLab/PersonaLive) | 约 15–17 GB（部分估算） | 已核实六个 PersonaLive 核心文件约 10.55 GB；另加 SD 图像变体 UNet、图像编码器和 VAE。上游下载脚本指向的 lambdalabs 主分支当前没有返回所需权重，外部底模不能声称已逐文件核实；15–17 GB 只作预算，待确认可用底模版本。 |
| F04 | [EditaLive](https://github.com/GVCLab/EditaLive) | 约 56.62 GB（官方脚本筛选的推理配套） | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| R01 | [StreamAvatar](https://streamavatar.github.io/) | 未公布/未确认，无法可靠估算 | 尚未确认完整官方可部署推理包及文件清单；不按论文参数量虚构下载体积。 |

## 容易重复计算的组件

FlashHead Lite 为约 6.11 GB 主权重 + 1.68 GB LTX VAE + 0.378 GB 音频编码器，合计约 8.16 GB。Pro 为约 6.03 + 0.508 + 0.378 GB，合计约 6.92 GB。Lite 文件比 Pro 略大是官方发布文件的实际序列化体积，不代表 Lite 推理更慢或更费显存；不能直接用“1.3B × 2 字节”代替这些文件大小。

若同时准备 Lite/Pro，两者共用一个英文编码器，合计约 **14.70 GB**；并不是把各自独立预算完整相加。只准备 Lite 时不必下载 Pro 与 Wan VAE。Ditto 的 PyTorch、ONNX、预生成 TensorRT 目录是不同后端路线，不应默认全下；Windows TensorRT 重建产物的大小另测。

FlashTalk、fast-flashtalk 可共享原始主权重。部分 SoulX/Wan 项目还能共享相同哈希的 T5、CLIP、VAE、中文音频编码器，跨项目复用必须先核对加载器、精度和实际哈希。运行时 A8W8/FP8 节省显存，不自动减少尚未量化的原始文件体积；若同时保留原始、转换、引擎三套副本，磁盘反而会上升。本表 FlashTalk/LiveAct 采用官方兼容权重组，包含随包 CLIP，未宣称完成源码裁剪后的最小安装。

EchoMimicV3-Flash 只计算选定 Flash-Pro transformer，避免把旧 transformer 和会被替换的 Wan 基础 DiT 一并计入。Hallo-Live 只取官方推理脚本列明的 DiT、T5、Wan2.2 VAE 和两个音频组件，不把 ODE 训练初始化、整套 Wan 5B 或全部 MMAudio 检查点加上。EditaLive 按官方脚本排除重打光/SAM2/独立 xlm-roberta 大包，仍保留姿态 ONNX 的外部张量文件；不能只统计带 .onnx 后缀的入口而漏掉外部数据。

## 原始来源与已知缺口

主要字节来源见[组件清单](avatar-model-storage.json)的官方 revision 链接；估算和不完整项还需结合以下原始说明：

- [github.com/bytedance/LatentSync/blob/main/scripts/inference.py](https://github.com/bytedance/LatentSync/blob/main/scripts/inference.py)
- [github.com/anliyuan/FeatherTalk/blob/main/docs/WEIGHTS.md](https://github.com/anliyuan/FeatherTalk/blob/main/docs/WEIGHTS.md)
- [github.com/anliyuan/FeatherTalk](https://github.com/anliyuan/FeatherTalk)
- [github.com/anliyuan/Ultralight-Digital-Human](https://github.com/anliyuan/Ultralight-Digital-Human)
- [github.com/Rudrabha/Wav2Lip](https://github.com/Rudrabha/Wav2Lip)
- [github.com/OpenTalker/SadTalker/releases/tag/v0.0.2](https://github.com/OpenTalker/SadTalker/releases/tag/v0.0.2)
- [github.com/OpenTalker/SadTalker/releases/tag/v0.0.2-rc](https://github.com/OpenTalker/SadTalker/releases/tag/v0.0.2-rc)
- [github.com/di-osc/fast-flashtalk](https://github.com/di-osc/fast-flashtalk)
- [github.com/deepbrainai-research/float](https://github.com/deepbrainai-research/float)
- [drive.google.com/file/d/1rvWuM12cyvNvBQNCLmG4Fr2L1rpjQBF0/view](https://drive.google.com/file/d/1rvWuM12cyvNvBQNCLmG4Fr2L1rpjQBF0/view)
- [storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task)
- [github.com/NVIDIA/Audio2Face-3D-SDK/blob/main/download_models.bat](https://github.com/NVIDIA/Audio2Face-3D-SDK/blob/main/download_models.bat)
- [github.com/GVCLab/PersonaLive/blob/main/tools/download_weights.py](https://github.com/GVCLab/PersonaLive/blob/main/tools/download_weights.py)
- [streamavatar.github.io/](https://streamavatar.github.io/)

FLOAT 官方主权重位于 Google Drive；本次未取得可靠大小，只有两个编码器约1.64GB可核实。PersonaLive 官方脚本仍指定 lambdalabs 的 UNet/图像编码器，但该仓库当前主分支元数据没有返回这些文件；因此15–17GB仅作工程预算。StreamAvatar 尚未确认完整可部署权重清单，无法给出可靠总量。上述缺口不能通过猜测模型参数量来填补。

本轮仅更新选型文档和磁盘预算。历史测评、原始音视频、正式口型后端、音色与运行参数均未作为本轮测量对象。
