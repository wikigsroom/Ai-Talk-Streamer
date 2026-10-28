# K02 口型定稿 / Selected K02 lip-sync baseline

**2026-10-29 用户决定：正式口型选用 K02。** 发布号
`split-a4090-b3080-v1.2.1-k02`。

[发布清单](../../configs/releases/split-a4090-b3080-k02-v1.2.1.json) ·
[本次验收状态](../evidence/lipsync-k02-selection-20261029.json) ·
[原始五组横评及完整媒体](../analysis/lipsync-k01-k05-20261028/ARCHIVE.md) ·
[O07/F07 语音基线](BASELINE_O07_F07.md) ·
[直播间后台手册](../live-room/RUNBOOK.md)

## 当前交付状态

K02 已选定，本地接入代码与 21 项 CPU 检查通过。**4090 实际部署和
K03～K05 模型删除尚未执行**：解锁后 Windows-MCP 仍报告
`unavailable / generation 1196`。用户要求等待其通知再重试；此期间不继续
访问远程控制通道、不重启其他项目、不加载模型。

“选定版本”“部署成功”“释放磁盘”“实播验收”分别记录。下方命令为恢复
控制后的执行程序，不能据此认定已在 4090 执行。磁盘实际释放量必须来自
远端清理回执，不能使用历史权重大小代替。

## 固定成品

| 环节 | 定稿值 |
|---|---|
| A 推理 | 4090 48GB / 64GB RAM；原生 Windows |
| B 输出 | 3080 轻量接收器＋官方哔哩哔哩直播姬 |
| 人物和背景 | 女A / 林知夏；原日光宿舍，720×1280、25 FPS |
| 动作 | 完整 48 类动作库，脸部预测与身体使用同一源帧索引 |
| 口型网络 | MuseTalk 1.5、FP16、batch 8 |
| 嘴周融合 | K02 下半脸椭圆软融合＋有限中位数色差修正＋静音淡出 |
| 语音 | O07 / OmniVoice 主用；F07 / F5-TTS v1 备用 |
| 对话、记忆 | 已配置云端 LLM＋本地 DSH/Humanity，A 为唯一状态写入者 |
| 管理与包装 | 原 `/admin`、BGM、滤镜、弹幕姬、留言姬和私聊 |
| 新增模型 | **0 字节**；K01 与 K02 共享现有 MuseTalk、Whisper、VAE |

K01 的网络权重不能独立删除，否则 K02 同时失效。原 Pillow 融合函数保留
为兼容代码，它不占用另一套模型。四个此前要求保留的 TTS 模型——Kokoro
PyTorch、MeloTTS Chinese、F5-TTS v1、OmniVoice——均不在删除范围。

## K02 算法与实时接入

固定参数位于 [integration/lipsync_k02.py](../../integration/lipsync_k02.py)
的 `PROFILE`。部署写入的 `configs/lipsync.json` 是审计快照；当前实现不提供
运行时热调参数，修改需要重新测试及部署，避免配置文字与实际算法不一致。

| 参数 | 值及含义 |
|---|---|
| 融合中心 | 脸框宽高的 `(0.50, 0.73)` |
| 椭圆半径 | 脸框宽高的 `(0.43, 0.29)` |
| 软边 | `clip((1-distance²)*5, 0, 1)` |
| 色差采样环 | `0.75 < distance² < 1.30`；样本超过 10 点才修正 |
| 色差限幅 | BGR 各通道中位数修正不超过 ±18 |
| 音频 | 每幅画面消费配套的两块 320 样本 PCM；16kHz，40ms |
| 静音阈值 | RMS `<0.0015` 时目标强度为 0，否则为 1 |
| 平滑 | 首帧直接采用目标；后续 `0.65×上帧 + 0.35×本帧目标` |

连续 12 帧静音约 480ms 后，原先为 1 的强度降至约 0.00569。算法逐步
回到当前素材原帧；不额外生成“强制闭嘴”图，源素材本身的表情仍会保留。

`BaseAvatar.process_frames` 从队列同时取出预测脸、音频和动作索引后，再推进
该实例的 gate；`MuseReal.paste_back_frame` 使用它融合当前源帧。
**不在异步推理线程提前计算并共享一个 gate**，避免排队时音频与画面错位。
静音帧也推进状态。输出独占一份图像内存，不修改动作库缓存；几何 mask
最多缓存 8 种尺寸，不创建 CUDA 张量、不增加模型下载。

## 远端启用程序

1. 收到用户的重试通知后，用 remote-4090 技能重新检查控制和桌面状态。
   盘点当前项目进程、端口、GPU、磁盘及已部署提交。保留其他 MCP 项目。
2. 确认本项目已下播、媒体任务已停。若人物或 TTS 正在运行，先按既有
   注册信息核实进程归属并停止本项目媒体；不按进程名全局结束 Python。
   不创建第二个 DSH 写入者，不更改状态数据库、云端密钥或 B 端源地址。
3. 将本次审核源码按允许文件同步到 **运行根**；`git pull` 只更新检出目录，
   不等于部署。新增文件为 `integration/lipsync_k02.py`、
   `deployment/activate_k02.py`、`scripts/cleanup_lipsync_candidates.py`。
4. 在既有原生环境执行：

```powershell
Set-Location -LiteralPath 'C:\dev\虚拟数字人直播'
.\runtime\livetalking\Scripts\python.exe -X utf8 -B deployment\activate_k02.py
.\runtime\livetalking\Scripts\python.exe -X utf8 -B scripts\cleanup_lipsync_candidates.py
```

激活器校验 MuseTalk、batch 8、25 FPS，检查 8010/9880/9881/9882 已关闭，
并验证固定上游的函数契约。先备份再替换两个上游文件和一个 server helper；
旧私有 `livetalking.yaml` 保持原样。激活器不加载 Torch、不启动任何服务。
检查 `.setup/k02/activation.json` 和 `.setup/k02/cleanup-plan.json`。

5. 在需要的最小窗口做 K02 实机冒烟验证：实际动作帧与相应语音、句中停顿、
   静音尾部、动作切换、缓存源帧不变，以及 O07/F07 配置保持。CPU 测试不
   等同于这项 GPU/实时验证。依用户此前要求，验证后停止本任务进程并释放
   所加载模型，不自动公开开播。
6. 确认清理计划后，执行已经获得用户授权的删除：

```powershell
.\runtime\livetalking\Scripts\python.exe -X utf8 -B scripts\cleanup_lipsync_candidates.py --apply
```

7. 独立确认目标均不存在、共用权重及保留 TTS 完整，核对历史测评指纹和
   磁盘净增量。新增部署/清理回执和独立验收状态，再同步仓库。不要改写旧
   测评的成绩、音频、视频、模型库存或当时运行环境记录。

## 删除边界与回执

| 范围 | 处理 |
|---|---|
| `models/lipsync-benchmark/feather` | 删除 K03 身份、推理及续训权重 |
| `models/lipsync-benchmark/wav2lip` | 删除 K04 GAN 权重 |
| `models/lipsync-benchmark/latent` | 删除 K05 UNet、tiny Whisper 等专用文件 |
| `runtime/lipsync-benchmark/feather`、`latent` | 删除候选专用环境；不跟随 `.pth` 读取共享安装 |
| `cache/lipsync-benchmark` | 删除本次候选专用下载、包缓存与训练 VGG 权重 |
| Feather 源码中的 3 个指定权重 | 删除 `feather_hubert.pth`、`checkpoint_epoch_335.pth.tar`、`scrfd_2.5g_kps.onnx` |
| MuseTalk / 主 Whisper / sd-vae | 保留，K02 仍依赖 |
| TTS、人物图、动作库、DSH、其他项目 | 保留 |
| K01～K05 历史测评与归档实验源码 | 保留；历史代码不代表候选仍可直接运行 |

清理器仅接受代码中的精确 allowlist；拒绝越界路径、junction、符号链接及
其他 reparse point。先盘点所有目录；发现活动候选任务即终止，不擅自杀进程。
实际删除前再次核对文件清单，历史目录元数据和选定原始音视频哈希前后比对。

回执在 `.setup/k02/cleanup-{plan,progress,result}.json`。
`logical_bytes` 为删除文件逻辑大小；`disk_free_delta` 为清理窗口磁盘净变化，
会受同机其他任务影响，两者不能混称为精确物理回收量。

## 验收边界

本地 21 项检查包括：冻结测评算法逐像素一致、缓存源帧不变、嘴周范围、
两块音频共同决定 gate、静音收敛、实例隔离、无效音频契约、真实固定上游
源码的幂等 patch、执行 patch 后的队列消费方法、清理越界/reparse/活动进程
保护、重复清理，以及原融合与动作调度回归。

原 K02 的 60 秒测评渲染耗时约 **140.62 秒**，对应共享负载下的离线流程，
**不能作为 25 FPS 直播已验收的证据**。本次没有重新宣称 GPU 吞吐改善，
也没有改动模型精度。公开弹幕/礼物、新版观众端 CDN 时延及既有记忆维护
验收边界继续保留于原发布清单。

## English

The user selected **K02** on 2026-10-29. It uses the retained MuseTalk 1.5
FP16/batch-8 network with a lower-face ellipse, bounded median color matching,
and a smoothed PCM energy gate. **No additional model weights are required.**
The gate advances on the frame consumer using the two actual 20 ms chunks
dequeued with that image; state is per avatar. Cached source frames are never
modified by the compositor. The fixed parameters reproduce the original K02
benchmark pixels.

Twenty-one native CPU checks pass. **Remote activation, GPU/real-time acceptance
and deletion remain pending** because the A4090 control service still reports
unavailable. The user requested no further remote retries until notified.
No remote disk recovery is claimed. The skill requires stopping unavailable
desktop operations; restarting the MCP backend was an operational suggestion,
not an explicit instruction in the skill.

After control recovery, deploy only the reviewed files into the existing runtime
root, run `deployment/activate_k02.py`, inspect the cleanup inventory, perform
the minimal real-machine validation, and run
`scripts/cleanup_lipsync_candidates.py --apply`. Both tools use native Windows
Python. Activation leaves services stopped; cleanup never kills processes or
downloads anything. Verify receipts under `.setup/k02` before declaring success.

Remove only the dedicated K03/K04/K05 weights, environments and cache. Keep
shared K01/K02 MuseTalk/Whisper/VAE, all four previously retained TTS models,
female-A and the full motion bank, DSH/Humanity state, the room console and
historical benchmark media/data. The historical 140.62-second offline K02 run
does not establish live playback speed. Public-broadcast and audience-latency
gates remain separate.
