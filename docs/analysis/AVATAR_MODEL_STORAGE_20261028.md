# 对口型/面控模型的磁盘增量预算：2026-10-28

[完整22项方案表](LIPSYNC_OPTIONS_20261028.md) · [可排序CSV](lipsync-options.csv) · [方案JSON](lipsync-options.json) · [逐文件大小与版本](avatar-model-storage.json)

## 预算口径

这里统计**模型磁盘空间**，统一为十进制 GB（1 GB = 1,000,000,000 字节）。显存由运行精度、激活、缓存、分辨率和并发共同决定，不能从磁盘体积直接换算。没有下载新权重，也没有将候选方案当成已经完成部署。

假定保留当前 MuseTalk 1.5、O07 OmniVoice 和 F07 F5-TTS；每行是从这个基线单独新增一个候选的预算。L00/L01 为零表示复用已安装权重。其他 ComfyUI 缓存没有逐文件核对，不预先宣称“已有”。兼容的 SD VAE 等组件可在版本/哈希确认后共享，不能只凭文件名相同就删除副本。

不含 Python 环境、Torch/CUDA/TensorRT、编译 engine、下载中间文件、重复缓存、训练视频、动作库和生成结果；这些都可能另占显著空间。可执行测试前应以选定锁定版本的实际清单和磁盘可用量再核算，不把本表当成承诺的完整安装峰值。首次安装大型候选宜只装一项并关闭自动全仓下载，逐组件安排空间。

Hugging Face 文件大小通过公开仓库元数据查询，网络传输使用 hf-mirror.com；组件清单保留官方仓库ID、revision、文件路径、字节数和可获得的LFS SHA256，并链接官方页面。关键目录大小已与官方文件页交叉检查。这不是已下载文件的本地哈希校验。带“估算”的行存在未发布的角色模型、辅助依赖或当前无法核对的外部底模；上下界为空表示未知，不应参与“总量最小”的排序。

## 分项预算

按**首次新增、基础配置的预计模型磁盘大小从小到大**排列，区间取下限；可选Audio2Emotion不计入F02排序，fast-flashtalk按首次54.79GB排序。FLOAT/StreamAvatar总量未知放末尾，保留原编号。质量列描述官方能力与本项目接入后的预期观看效果，**除现有L00链路外未在女A上实测，也未进行统一成片盲评**；不据此赋予星级或画质名次。

表格左列“排序”是本次升序的1–22序号，“原编号”保留用于交叉引用。大小相近项统一显示精度，FlashTalk/fast-flashtalk/LiveAct均显示约54.79GB；内部仍以未格式化的原始数值排序。

| 排序 | 原编号 | 方案 | 预计新增模型磁盘 | 预期成品效果质量 | 构成、共享与边界 |
| --- | --- | --- | --- | --- | --- |
| 1 | **L00** | 当前 [MuseTalk 1.5](https://github.com/TMElyralab/MuseTalk) | 0 GB（已安装） | 保留原片身体、手势与宿舍背景；嘴部256×256重绘，牙齿/唇色/融合边缘是重点检查项，动作仍会循环。 | 现有 MuseTalk、Whisper、VAE 和人脸辅助模型继续保留；不是说模型本身体积为零。 |
| 2 | **L01** | MuseTalk 1.5 参数/融合/调度优化 | 0 GB（复用当前权重） | 预期改善嘴周闪烁、肤色接缝、句尾闭口和动作切换；脸部纹理上限与自由手势能力仍受当前模型/素材约束。 | 仅参数、素材筛选、融合与调度优化；若额外上增强模型应单列，不包含在此行。 |
| 3 | **F01** | [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker) | 约 0.00376 GB（3.76 MB） | 提供眨眼、嘴形与头姿跟踪参数；成品细节取决于后续人物模型/渲染器，单独使用不会生成女A说话视频。 | 官方 face_landmarker.task 的 Content-Length 为 3,758,596 字节；不包含渲染角色或图像生成模型。 |
| 4 | **L07** | [FeatherTalk](https://github.com/anliyuan/FeatherTalk) / [Ultralight](https://github.com/anliyuan/Ultralight-Digital-Human) | FeatherTalk 约 0.04–0.10 GB¹ | 专属训练可贴合固定女A；默认144×144视觉模型的唇纹、牙齿特写细节有限，侧脸/遮嘴效果依赖训练素材。 | 只估部署推理权重：已发布 FeatherHuBERT 13,480,913 字节 + 5.46M 参数视觉模型 FP32 原始参数约 21.84 MB；序列化/缓冲需余量。女A专属视觉模型尚未训练。预处理检测/关键点、训练检查点和数据另计；旧 Ultralight 的 WeNet/HuBERT 分支大小须按所选编码器重算，不能沿用此数字。 |
| 5 | **L08** | [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) | 约 0.53–0.60 GB（估算） | 可保留源片并完成基本口型同步；需留意嘴部偏软、牙齿细节和嘴周拼接，适合作速度/同步对照。 | 约 0.44 GB 主检查点 + 约 0.09 GB SFD 检测模型；不同 GAN/非 GAN 发布版本须逐文件确认。SadTalker 官方历史发布中的 wav2lip.pth 为 435,807,851 字节，仅作同类检查点体积参照；不将其伪称为本项目已安装的原始权重。 |
| 6 | **L05** | [LivePortrait](https://github.com/KlingAIResearch/LivePortrait) + MuseTalk | 约 0.66 GB（人像模式） | 可补充眨眼、微笑和点头，提升倾听表情；大幅转头、遮挡和与MuseTalk同时控制嘴部时需要处理变形/冲突。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 动物权重不计入，当前 MuseTalk 不重复计入。 |
| 7 | **F02** | [NVIDIA Audio2Face-3D SDK](https://github.com/NVIDIA/Audio2Face-3D-SDK) | 约 0.78 GB；含情绪约 2.05 GB³ | 能驱动3D角色的嘴、脸颊和表情；最终写实程度由角色建模、牙齿、材质与灯光决定，需要另建女A的3D资产。 | 选 v3 基础模型包约 0.777 GB，选配 Audio2Emotion ONNX 增加约 1.271 GB；不包含旧 v2 三个人物包、TensorRT engine、3D角色与渲染器。情绪权重需要接受官方访问许可。 |
| 8 | **L10** | [SadTalker](https://github.com/OpenTalker/SadTalker) | 约 1.0–1.5 GB（估算） | 单图能生成说话、眨眼和头动；固定镜头可作整脸动画参考，需检查头颈接缝、表情僵硬和增强后的身份变化。 | 官方 v0.0.2-rc 单个 256/512 检查点均为 725,066,984 字节，选一个；mapping 约 0.156 GB，另计裁脸/可选 GFPGAN。不要把旧版全部检查点和两种分辨率一起相加。 |
| 9 | **L02** | [Ditto](https://github.com/antgroup/ditto-talkinghead) | 约 2.31 GB（PyTorch） | 可把口型、头姿、眨眼作为整体头部运动来生成/控制；细节与侧脸形变待测，身体和手势仍需独立素材。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 ONNX 是另一种约 2.53 GB 的路径；导出/重建 Windows TensorRT engine 会另占磁盘，不能直接复用上游 Linux 构件。 |
| 10 | **L06** | [LatentSync 1.6](https://github.com/bytedance/LatentSync) | 约 5.2–5.6 GB；整包约 10 GB | 512分辨率训练针对嘴部模糊，适合精修唇形与口腔细节；保留原片动作，仍需检查牙齿闪烁和采样失真。 | 推理主权重和 tiny 约 5.15 GB，另计裁脸模型；复用现有同版本 SD VAE 时减少约 0.33 GB。官方整仓含评测/训练辅助权重达 9.64 GB，加单格式 VAE 接近 10 GB，不是最小推理安装量。 |
| 11 | **L04** | [SoulX-FlashHead Pro](https://github.com/Soul-AILab/SoulX-FlashHead) | 约 6.92 GB（Pro + Wan VAE + 音频编码器） | 偏重人像细节与自然表演的候选；本机口型/牙齿尚未横评，官方单4090约10.8FPS，直接直播会有流畅性不足。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| 12 | **L03** | [SoulX-FlashHead Lite](https://github.com/Soul-AILab/SoulX-FlashHead) | 约 8.16 GB（Lite + LTX VAE + 音频编码器） | 可从单图流式生成口型和头部运动，有望减少素材循环感；需实测唇齿、发丝、身份与背景的长时稳定性。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| 13 | **F03** | [PersonaLive](https://github.com/GVCLab/PersonaLive) | 约 15–17 GB（部分估算） | 把驱动者的眉眼、嘴形和头动迁移到角色，适合丰富表情；依赖驱动视频/摄像头，遮挡和跨脸型匹配待测。 | 已核实六个 PersonaLive 核心文件约 10.55 GB；另加 SD 图像变体 UNet、图像编码器和 VAE。上游下载脚本指向的 lambdalabs 主分支当前没有返回所需权重，外部底模不能声称已逐文件核实；15–17 GB 只作预算，待确认可用底模版本。 |
| 14 | **L09** | [EchoMimicV3-Flash](https://github.com/antgroup/echomimic_v3) | 约 20.75 GB（Flash-Pro + Wan 配套编码器/VAE） | 可生成头部及身体动画，适合制作配套表演素材；少步加速下需检查口型、牙齿、手指和跨段连贯性。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| 15 | **L15** | [Hallo-Live](https://github.com/fudan-generative-vision/Hallo-Live) | 约 38.64 GB（推理必需权重组） | 语音与人物联合生成，有利于统一表演节奏；原生流程会改变O07/F07音色链路，单4090观看流畅度未验证。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| 16 | **L14** | [Alibaba-Quark LiveAvatar](https://github.com/Alibaba-Quark/LiveAvatar) | 约 47.08 GB（基础 S2V + LoRA） | 面向长时连续人物生成，预期减少短动作反复播放；需核对脸、衣服、手部与背景漂移，单4090流畅度未知。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| 17 | **L11** | [SoulX-FlashTalk](https://github.com/Soul-AILab/SoulX-FlashTalk) | 约 54.79 GB（官方兼容权重组） | 可统一生成流式人物表演，适合观察口型与头肩动作协调；脸部细节待同源对比，单4090供帧是主要落地门槛。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| 18 | **L12** | [fast-flashtalk](https://github.com/di-osc/fast-flashtalk) | 首次约 54.79 GB；复用 L11 约 0 GB² | 延续FlashTalk的表演能力；量化后的唇齿细节、肤质、运动与首帧需对照原版，不能预设加速后画质不变。 | 这是独立采用本方案的首次原始权重预算；若已下载 L11 且路径共用，新增原始权重约零。A8W8 是运行时量化路径，不自动缩小原始下载文件；若另存量化权重/编译缓存，须追加实测占用。 |
| 19 | **L13** | [SoulX-LiveAct](https://github.com/Soul-AILab/SoulX-LiveAct) | 约 54.79 GB（官方兼容权重组） | 支持动作/情绪编辑与长时人物表演，适合扩充姿态素材；需验证手部、身份和动作切换，单4090实时性不足以确认。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| 20 | **F04** | [EditaLive](https://github.com/GVCLab/EditaLive) | 约 56.62 GB（官方脚本筛选的推理配套） | 支持角色、服装与全身动作编辑，适合扩展形象素材；需重点检查手指、遮挡、衣纹，当前在线横屏须适配竖屏。 | 按所列组件的公开文件大小求和；小型配置/tokenizer 另有少量开销，未经安装验证。 |
| 21 | **L16** | [FLOAT](https://github.com/deepbrainai-research/float) | 已知编码器约 1.64 GB + 主模型待核实 | 单图可生成带情绪的脸部和头部运动；适合正脸表演参考，非正面、头身贴合与手势仍需另行处理。 | 编码器合计约 1.64 GB 是已知部分，不是总量。float.pth 的官方 Google Drive 入口可确认，但本次没有取得可靠文件大小；总量上下界保留空值，避免编造。 |
| 22 | **R01** | [StreamAvatar](https://streamavatar.github.io/) | 未公布/未确认，无法可靠估算 | 研究展示包含说话、倾听和手势，符合双向互动目标；发布完整性尚未确认，当前不能承诺女A成品质量。 | 尚未确认完整官方可部署推理包及文件清单；不按论文参数量虚构下载体积。 |

## 成品效果质量的具体边界

这里的“质量”分为口型/口腔细节、身份与肤质、表情/头姿、身体/手势、背景稳定及时间连续性。推理能输出画面、最终合成720×1280，或官方展示短片，都不能直接证明在女A直播中这些维度同时达标。生成模型支持某动作也不保证每个手指和遮挡都正确。

下列是安装前的预期与检查重点；来源为官方能力/版本说明及当前代码链路的工程推断，本轮没有重新生成或观看候选测试成片。性能和quality_score原始字段保持原值，不把这些描述转成已实测分数。画质潜力与实播流畅度要一起验收，不能用大模型或文件体积替代画质结论。

**L00**：当前人物链路已接入，最近验收验证了25FPS级节目连续性，但没有给出统一口型盲评得分。真实感主要依赖源视频：身体、衣服、手部和背景随素材保留；模型负责嘴部区域，不能根据每句话自由产生手势。720×1280输出不会把嘴部原生生成分辨率提升为720p。

依据：[来源1](https://github.com/TMElyralab/MuseTalk)。

**L01**：效果目标是让现有画面更连贯：减少嘴周色差和跳动、改善停顿闭口、避免说话/倾听切片突兀。它不产生新的模型分辨率，也不创造训练中不存在的牙齿细节或任意肢体动作。收益需要逐素材A/B测试，本轮没有宣称已完成这些优化。

依据：[来源1](https://github.com/TMElyralab/MuseTalk)。

**F01**：适合把真人表情输入、自动唇形检查和可视化控制接入后台。它输出关键点、blendshape和变换矩阵，最终的皮肤、牙齿、发丝和光照由接收这些参数的模型或3D角色决定；跟踪速度不能当作人物成品质量或视频生成FPS。

依据：[来源1](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker)。

**L07**：预期适合固定机位、固定人物和较小人脸画幅的连续口型，身体和背景可沿用原片。默认FeatherTalk视觉输入为144×144，不能把轻量速度等同于高清面部细节；未见姿态和手遮嘴场景尤其依赖专属训练数据。女A尚未训练，旧Ultralight不同编码器/视觉分支也不能直接沿用同一质量结论。

依据：[来源1](https://github.com/anliyuan/FeatherTalk) · [来源2](https://github.com/anliyuan/Ultralight-Digital-Human)。

**L08**：原始开放版本侧重音画同步。成品的头身和背景沿用输入视频，嘴部区域重新生成；高清特写应检查嘴唇纹理、牙齿连续性、下巴边界和脸部检测抖动。GAN/非GAN权重在视觉效果和同步之间存在取舍，不将商业HD版效果套到原始开放权重。

依据：[来源1](https://github.com/Rudrabha/Wav2Lip)。

**L05**：通过驱动视频或表情模板让眼睛、眉毛和头姿发生变化，适合当前女A先离线补齐表情片段，再交由MuseTalk生成音频口型。保留身份与表情幅度之间需要权衡；大转头、张嘴和头身边缘应逐段检查。实时级联时必须划定嘴部控制权，避免两套模型重绘同一区域。

依据：[来源1](https://github.com/KlingAIResearch/LivePortrait)。

**F02**：适合可控的3D直播人物：音频转换为面部动画，配合可选情绪组件形成表演。参数可控不意味着成品天然达到真人照片质感，尤其牙齿/舌头、口腔、眼神、皮肤材质和灯光需要完整3D制作。当前照片/视频人物不能仅替换SDK就得到同样外观。

依据：[来源1](https://github.com/NVIDIA/Audio2Face-3D-SDK)。

**L10**：音频先驱动3D运动系数，再生成人像，适合从单图得到基础头部表演。身体/宿舍场景没有因此获得自由动作；大动作贴回原图时要看头颈和发际边界。GFPGAN等增强可能改变身份纹理，应保留未增强对照，不能只看锐化后的单帧。

依据：[来源1](https://github.com/OpenTalker/SadTalker)。

**L02**：通过运动空间生成和控制头部表演，预期可减少只动嘴的静态感，支持将有界头姿/表情控制接入DSH。它的优势应从唇形、眼神、运动连续性和身份保持一起评估，不能只凭运动自然就判定牙齿/肤质超过MuseTalk。女A及宿舍原片的头身合成、遮挡和长时稳定性尚未测试。

依据：[来源1](https://github.com/antgroup/ditto-talkinghead)。

**L06**：官方1.6改用512×512训练来缓解模糊，1.5已引入时间层并改善中文视频。预期适合作为当前素材的离线口型质量参照；提高采样步数会增加耗时，提高guidance可能改善同步但带来抖动或失真。它不会替女A自动生成新的身体动作，原片的侧转和遮挡仍决定难度。

依据：[来源1](https://github.com/bytedance/LatentSync)。

**L04**：Pro应作为脸部细节、唇形和头部运动的画质参照，是否优于Lite必须用同图同音频盲评。本项目尚未验证其身份保持、长时漂移或牙齿细节。现有官方单4090吞吐约10.8FPS，低于节目25FPS；即使单帧更好看，直接实播仍可能因供帧不足而失去可观看性，不能用插帧后的输出参数冒充原生实时。

依据：[来源1](https://github.com/Soul-AILab/SoulX-FlashHead) · [来源2](https://soul-ailab.github.io/soulx-flashhead/)。

**L03**：Lite面向消费卡流式说话人像，预期适合检验口型与头部运动共同生成的观看效果。本项目没有证据证明其嘴部细节必然优于当前MuseTalk，也未验证它能完整替代现有48段手势素材。验收应覆盖眨眼、句末闭口、肤质/牙齿连续性、头身关系、背景稳定和10分钟身份保持。官方吞吐只表明实时潜力。

依据：[来源1](https://github.com/Soul-AILab/SoulX-FlashHead) · [来源2](https://soul-ailab.github.io/soulx-flashhead/)。

**F03**：观看效果重点是富有表现力的整脸迁移：驱动者的表情和头动可赋给目标角色，适合演员面捕或表情素材生产。它不是直接消费O07语音的口型后端；没有驱动信号时不能自动得到这套表演。大表情、头部遮挡、驱动/角色脸型差异和身份细节是需要验证的质量边界；外部底模也尚待确认。

依据：[来源1](https://github.com/GVCLab/PersonaLive)。

**L09**：多模态/多任务人像动画提供比局部嘴部替换更多的动作生成可能，适合制作坐播动作、头肩表演和短片。最终效果依赖音频、文本、参考条件与采样设置；官方提示音频CFG和视觉质量存在取舍。Flash快速输出不等于每个手部动作都正确，需分别核对头/身体设置、手指遮挡和长段衔接。

依据：[来源1](https://github.com/antgroup/echomimic_v3)。

**L15**：成品侧重点是文字到联合音视频表演，将语音节奏和人物动作一起生成。它不直接等同于“给定O07声音后只改口型”，所以音色一致性与可控性也须重新验收。官方多卡示例不是本机连续直播证据，单帧质量、声画同步和供帧稳定需要同时测量。

依据：[来源1](https://github.com/fudan-generative-vision/Hallo-Live)。

**L14**：通过流式分块生成持续的人物视频，适合观察整个人物的口型、头肩和时间连续性。官方长时生成目标不能替代女A宿舍的10分钟验证；手势准确性、服装纹理、背景稳定和跨块动作衔接都可能影响真实感。容量可行不证明单4090加O07/F07后能够稳定25FPS。

依据：[来源1](https://github.com/Alibaba-Quark/LiveAvatar)。

**L11**：14B流式生成路线适合评估人物整体动态、口型、身份保持与长时连续性，不能只比较一帧清晰度。没有本角色证据证明它自动优于更小模型；尤其单4090使用CPU卸载时，视频块若不能及时生成，实际直播可能卡顿。手部和宿舍背景必须另做相同输入、相同时长的实测。

依据：[来源1](https://github.com/Soul-AILab/SoulX-FlashTalk)。

**L12**：它是同一基础模型的推理优化路线，不应当作另一种完全独立的画质风格。A8W8、注意力后端和卸载策略可能改变数值及供帧节奏，需要与原始精度在相同音频/种子/设置下对照嘴部、纹理闪烁、身份和动作。社区相对加速声明不能直接说明当前节目能稳定25FPS，优化后的本机成品尚未验证。

依据：[来源1](https://github.com/di-osc/fast-flashtalk) · [来源2](https://github.com/Soul-AILab/SoulX-FlashTalk)。

**L13**：预期成品优势是语句之外的动作/情绪控制和较长时间的连续人物表演，适合离线丰富女A坐播素材。并非任意自然语言动作都能保证手指正确、头身协调；官方还提示FP8 KV缓存可能稍影响质量。消费卡卸载模式的吞吐不足以证明本项目连续25FPS，素材生成和实时直播应分别验收。

依据：[来源1](https://github.com/Soul-AILab/SoulX-LiveAct)。

**F04**：比仅驱动嘴部更偏向驱动视频上的角色与身体编辑，可用于生成不同姿态、服装和动作素材。成品质感需要同时关注人脸身份、手部结构、衣纹连续性和背景边界；驱动遮挡越复杂，越需要逐段审核。当前在线版本横屏限制和单4090性能使其不能直接当作现有9:16音频口型后端替换。

依据：[来源1](https://github.com/GVCLab/EditaLive)。

**L16**：FLOAT提供音频驱动的运动latent和情绪控制，预期适合正脸头部表演、表情变化和情绪素材。官方明确训练数据以正脸姿态为主，非正面图像可能表现较差；不据此推定其在侧脸、手遮嘴或当前宿舍半身构图上都稳定。主权重大小尚未核实，也没有本机成片评分。

依据：[来源1](https://github.com/deepbrainai-research/float)。

**R01**：研究方向同时利用用户/Agent音频来驱动说话与倾听行为，目标是让人物在对话状态之间形成连续动作。项目展示只能说明研究能力，不能证明可在当前原生Windows、单4090、既定音色和9:16宿舍场景复现。没有完整官方部署清单和本角色评测前，只列观察项，不授予质量等级。

依据：[来源1](https://streamavatar.github.io/)。

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
