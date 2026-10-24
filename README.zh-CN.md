# AI Talk Streamer · 写实数字人直播

[English](README.md) · [简体中文](README.zh-CN.md) · [完整文档](docs/README.md)

一套运行在 **原生 Windows** 上的 **9:16 写实数字人演播台**：输入播报稿，或通过你自己的云端 LLM 渠道提问，由本机生成语音、实时口型和融合画面，并把同一个人物会话送到网页与 OBS。

当前角色档案编号为 **女A**，正式姓名 **林知夏**，配套场景为 **知夏的日光宿舍**。她是**虚构的 22 岁中国女大学生**，沿用白天宿舍、长发、浅蓝卫衣的形象。[角色与素材归档](docs/CHARACTERS.md)提供分类目录、可校验清单和归档包。参考运行环境为 **RTX 4090 48 GB 显存＋64 GB 内存**。

已增加 **RTX 3080 10 GB／64 GB 内存**实测版本，保留原始 batch 8、FP16 模型、完整动作库和 720×1280 输出。网页现统计视频实际呈现的帧率，慢连接积压时保留排队的音频。参见 [3080 部署与实测](docs/RTX3080.md) 和 [播放卡顿排查与修正](docs/PLAYBACK.md)。

![实际说话中的演播台](docs/media/studio-speaking.png)

**女A音色选型：** [MOSS 10 款、SoulX 10 款同号对比与 FireRed 01 对照](docs/VOICES.md)，由 3080 实际生成。运行中演播台的 `/voices.html?v=2` 默认展示 MOSS，可切换模型、保存候选及下载；页面选型不会自动修改直播引擎。

五款夜间封闭室内人物方案见[夜间角色选型](docs/CHARACTER_CAMERA_V3.md)。V3 将 01–03 重做为手机聊天近景、正面桌播与**暮蝶 / Clove 真人 Cos** 展示，包含原图、平台机位参考、提示词和可离线打开的对比页面。

## 先看实际效果

以下素材来自真实运行服务和 OBS 录像，不是界面设计稿。GIF 为原速无声片段；MP4 测试视频保留本地合成的声音。

| 招手欢迎 | 摊掌讲解 |
| --- | --- |
| ![招手欢迎](docs/media/welcome.gif) | ![摊掌讲解](docs/media/explanation.gif) |

![网页实际响应过程](docs/media/browser-response.gif)

[观看网页操作录屏](docs/media/browser-interaction.mp4) · [观看带声音的欢迎测试](docs/media/s01_welcome.mp4) · [查看五段测试](docs/TESTING.md#scenario-recordings)

网页操作录屏不带音轨，五段 OBS 场景视频带声音。

GitHub 对仓库 MP4 链接可能提供下载而非内嵌播放器，README 中的 GIF 可直接观看。[截图与视频画廊](docs/GALLERY.md)收录全部演示文件及来源说明。

## 具体采用的方案

| 环节 | 实现 | 运行位置 |
| --- | --- | --- |
| 逻辑、推理、文字对话 | 用户指定的 OpenAI 兼容渠道，支持 Chat Completions / Responses | 可选云端 LLM |
| 中文语音合成 | GPT-SoVITS v2 | 本地 GPU |
| 音频特征 | MuseTalk 使用 Whisper tiny 提取特征，不是观众语音识别 | 本地 GPU |
| 实时口型与融合 | MuseTalk 1.5、VAE、人脸跟踪与嘴部紧凑遮罩 | 本地 GPU / CPU |
| 手部、肢体和宿舍画面 | 本地 H3 生成并审核的动作视频 | 准备阶段本地生成，直播时复用 |
| 动作编排 | 根据说话状态和手动选择播放完整片段 | 本地程序 |
| 网页播放与录制 | WebSocket JPEG＋PCM、Canvas、Web Audio、MediaRecorder | 本地服务与观看端浏览器 |
| 录制与推流输出 | 便携 OBS，720×1280、目标 25 FPS | 本机 |
| 参考图制作 | 携带原图，调用选定的图片编辑渠道 | 准备阶段；成品已随仓库提供 |

**原文播报不需要云端 LLM。**「AI 回复」只把文字发送到你配置的渠道；直播中的语音、口型与画面不调用云端数字人、语音或视频接口。安装阶段需要下载程序与模型，常规媒体推理使用本地资产。

## 工作逻辑

```mermaid
flowchart LR
    A[输入文字] --> B{原文或 AI}
    B -->|原文| D[本地 GPT-SoVITS]
    B -->|AI| C[用户云端 LLM]
    C -->|分句输出| D
    D --> E[本地音频特征]
    E --> F[MuseTalk 实时口型]
    G[审核后的身体动作库] --> F
    H[说话状态和手动选择] --> G
    F --> I[共用 JPEG / PCM 广播]
    I --> J[网页预览与录制]
    I --> K[OBS 浏览器源]
```

素材准备是另一条链路：参考图 → 本地 H3 视频 → 人工复核 → 720×1280 / 25 FPS 编码 → 人脸坐标、融合遮罩和潜变量 → 动作库装配。直播时，**身体帧、人脸潜变量和遮罩使用相同帧索引**，切换发生在片段边界，避免把手势切到一半。

这是一套「预制身体动作＋实时语音口型」方案，尚未实现按每个词的含义实时生成任意全身动作。详细进程与数据流见[架构文档](docs/ARCHITECTURE.md)。

## 随仓库提供的素材

| 类别 | 新增片段 | 时长 | 示例 |
| --- | ---: | ---: | --- |
| 欢迎互动 | 8 | 64 秒 | 左右招手、双手迎接、致意 |
| 摊手讲解 | 8 | 64 秒 | 摊掌、小弧线示意、侧边展示 |
| 强调认可 | 8 | 64 秒 | 轻压安抚、贴胸口、双掌强调 |
| 思考倾听 | 8 | 64 秒 | 倾头、回应、前倾、搭手 |
| 坐姿与肢体 | 8 | 64 秒 | 放松肩膀、整理袖口、坐姿调整 |
| 转场收尾 | 8 | 64 秒 | 挥手、致谢、回到待机 |
| **新增合计** | **48** | **384 秒** | **相对两段、16 秒基础版为 24 倍** |

加上两段基础动作，运行库共有 **50 段、400 秒、10,000 帧**。另有 **28 张独立生成的动作参考照**、人物/背景参考图、48 张封面、48 张关键帧、提示词、便携 H3 工作流和审核后的执行记录。左右侧及表演变体按独立片段计算，不声称是 48 种完全不同的手势；视频抽帧、同一照片的不同尺寸不算新增生成。

入选源素材按普通 Git 文件提供，克隆会下载数百 MB 媒体。模型权重、安装后的程序、Python 环境、密钥、原始长录屏和体积很大的解码角色帧不入库。可直接用随仓库视频重建角色，**无需重新生成 H3 视频**。见[素材文档](docs/MATERIALS.md)。

## 安装与启动

准备原生 Windows x64、Git、用于引导安装的 Python 3.10+、支持 CUDA 12.8 PyTorch 的 NVIDIA 驱动及足够磁盘空间。脚本会创建两套原生 Python 3.10 环境，分别运行语音和人物。全程不使用 Docker、WSL 或虚拟机。

```powershell
git clone git@github.com:wikigsroom/Ai-Talk-Streamer.git
cd Ai-Talk-Streamer
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup-Streamer.ps1 -PrepareAvatar
.\Start-Streamer.cmd
```

RTX 3080 安装时增加 `-HardwareProfile rtx3080-original`，随后使用 `.\Start-3080.cmd`。已有完整角色的迁移及显式降级步骤见 [3080 专项文档](docs/RTX3080.md)。

完整安装会下载依赖与模型、应用集成改造、检查本地语音资源，并预处理已提供的视频。预处理占用 GPU，可能持续较长时间并生成大量图像；建议预留 **100 GB 以上空闲磁盘作为规划余量**，这不是实测最低需求。预处理时释放其他 GPU 生成任务，已有完整角色不会被无条件覆盖。

本机访问 **http://127.0.0.1:8010/**；其他设备通过可信局域网或 VPN 访问 `http://<工作站地址>:8010/`。仓库本身不提供公网托管演示，截图来自参考部署。

已用源码版本固定在 [sources.lock.json](configs/sources.lock.json)，模型下载及哈希见 [model-files.csv](configs/model-files.csv)。参考部署经过真实运行验证；发布时另做源码语法、素材哈希、文档链接和媒体检查。本次整理没有为发布再次完整下载并重装全部模型；新机器按[部署文档](docs/DEPLOYMENT.md)逐阶段检查。

## 网页使用顺序

1. 点击 **连接预览与声音**，允许页面建立音视频流。
2. 选 **原文播报**，输入 20–100 字作为初次测试，点击 **发送播报**。
3. 点击 **停止说话**可打断；发送新内容也会使前一轮语音失效。
4. 选择动作并点 **播放一次**，或使用 **自动编排／安静倾听**。手动动作会等当前片段完成，通常等待不超过剩余八秒加画面缓冲；连续选择时保留最新待播请求。
5. 点击 **录制并下载**，结束后保存带声音的 WebM。

使用云端文字模型时，展开 **渠道设置**，填写接口地址、API Key、渠道的**实际模型 ID**及协议，保存后切换 **AI 回复**。例如“GPT 6 Luna”只是显示名称时，不能据此猜测 model ID。变量模板见 `configs/channel.env.example`，真实 `configs/channel.env` 被 Git 忽略；保存时密钥留空会保留原值。

启动 OBS：

```powershell
.\Avatar.cmd -Action start-obs
.\runtime\livetalking\Scripts\python.exe -X utf8 scripts\configure_vertical_obs.py
```

便携 OBS 的配置/场景集合为 `Avatar Local`，节目场景 `Avatar`，浏览器源为 `http://127.0.0.1:8010/obs.html?v=vertical-1`。源尺寸、画布、输出均为 720×1280、25 FPS。录制程序等待 OBS 确认文件关闭，再转封装为 MP4。正式直播时在 OBS 填写平台推流信息。[完整操作与 HTTP 示例](docs/USAGE.md)。

## 实测结果与边界

| 项目 | 观察结果 | 含义 |
| --- | --- | --- |
| 画面输出目标 | 720×1280、25 FPS | 不代表所有机器与时刻都固定达到 |
| 五种情境实测 | 合计 217.24 秒 | 验证声音、动作、停止和恢复 |
| 全动作巡检 | 48 项、407.68 秒 | 30 张说话截图、18 张静默截图 |
| 原文发送至开口 | 网页一次 5.281 秒；另一 OBS 测试 14.734 秒 | 已预热的单次测量，不是延迟分布 |
| 一次云端对话 | 首段文字 14.723 秒；开口 16.541 秒 | 包含渠道与本地合成等待 |
| 生成/验证采样峰值 | 显存 43.90 GiB、整机内存 58.84 GiB | 每 10 秒采样，包含整机其他占用 |
| 最终空闲直播快照 | 显存约 12.28 GiB、整机内存 15.97 GiB | 已释放生成模型的一次快照 |

口唇和牙齿细节可能比原图柔和，受 MuseTalk 256 像素生成区域影响。当前没有持久多轮对话记忆、观众麦克风 ASR、平台弹幕自动接入、多人物会话隔离、用户登录或直播自动运营。动作按状态和手动请求编排，不做逐词语义手势生成。演播台用于可信工作站网络，尚不适合未经访问控制直接暴露公网。具体证据与限制见[测试文档](docs/TESTING.md)。

## 文档与维护

| 文档 | 说明 |
| --- | --- |
| [文档索引](docs/README.md) | 中英阅读路线 |
| [RTX 3080](docs/RTX3080.md) | 10 GB 显卡实测、优化、迁移和降级顺序 |
| [部署](docs/DEPLOYMENT.md) | 原生环境、安装步骤、断点恢复 |
| [使用](docs/USAGE.md) | 播报、渠道、动作、OBS、API |
| [架构](docs/ARCHITECTURE.md) | 准备与直播的数据流、打断逻辑 |
| [素材](docs/MATERIALS.md) | 资产结构、重建角色、可选 H3 生成 |
| [测试](docs/TESTING.md) | 五段实录、验收范围与数据 |
| [截图/录屏/GIF](docs/GALLERY.md) | 完整演示内容与来源 |
| [排障](docs/TROUBLESHOOTING.md) | 首次加载、声音、口型、内存与 OBS |
| [第三方声明](THIRD_PARTY_NOTICES.md) | 开源代码、模型与示范声音来源 |

```powershell
python -X utf8 devtools/verify-repository.py
python -m unittest discover -s tests -v
npm ci
$env:AVATAR_BASE_URL='http://127.0.0.1:8010'
npm run capture
```

录制文档使用已安装的 Chrome，单独创建浏览器上下文，实际发送一段本地播报并操作动作，结束时通过 `finally` 关闭自己的页面和上下文。可用 `CHROME_PATH` 指定浏览器位置。贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

本项目集成与文档采用 [Apache-2.0](LICENSE)；上游代码、下载模型及示范声音仍遵循各自许可，不因本仓库许可而被重新授权。见 [NOTICE](NOTICE) 与[第三方声明](THIRD_PARTY_NOTICES.md)。
