# 4090 原生迁移、运行准备与切换

> Current voice / 当前语音：**O07 OmniVoice 主用，F07 F5-TTS v1 备用**。启动、切换、回退与新版验收以[新版手册](BASELINE_O07_F07.md)为准；本页旧MOSS记录/命令保留历史来源。Historical MOSS measurements are not new-release latency.

**后续执行更新：** 4090已完成原生MOSS模型/vendor、DSH/Humanity和batch8人物部署，并通过A→虚拟网络→B的五段真实交互与重连验收。新的默认方案为[A推理+B直播姬](SPLIT_DEVICE.md)，详见[当次证据](SPLIT_DEVICE_ACCEPTANCE.md)。本页下方的同步前库存保留历史时间语义；正式记忆仍须按一致切换程序迁移。

[4090 目标](../RTX4090.md) · [归档](../archives/2026-10-26-LIVEHIME-HANDOFF.md) · [总部署](../DEPLOYMENT.md) · [直播姬](../platforms/BILIBILI_LIVEHIME.md) · [人格记忆手册](../dsh-humanity/RUNBOOK.md)

## 1. 任务边界与后续默认

自 2026-10-26 起，本方案的主运行目标为 **4090 / REMOTE_4090_HOST**。3080 的 10 GB 共享显存压力、编码和生成等待已经有实测证据；后续运行、性能优化与正式验收以 4090 为准。3080 作为旧版本及回滚参考，不再默认为新功能部署目的地。

本次先完成方案归档、Git 更新、4090 仓库及方案文件同步。保持现有 3080 的公开直播和私有状态，不自动执行公开下播或跨机接管。下面的运行安装、最终记忆迁移和开播步骤有明确先后次序，完成每一步后记实际结果，不能把步骤文字当作已执行回执。

**禁止：** Docker、WSL、虚拟机；复制后直接运行另一台机器的虚拟环境；在目标机重放旧 `.setup/services.json` 的 PID；在两台机器同时维护同一个女A正式记忆库；将 Cookie、API key、推流凭据写入 Git。原生 Python `venv` 允许使用。

## 2. 实机差异与已有内容

| 范围 | 3080 已验证状态 | 4090 同步前实测 | 后续处理 |
|---|---|---|---|
| 显存 | 10 GB，最近本地直播姬测试峰值 9,745 MiB | 总量 49,140 MiB，空闲 39,561 MiB | 重新测量峰值与长期稳定性 |
| 人物 | MuseTalk FP16 batch 4，完整动作 | 旧 GPT-SoVITS 配置 batch 8，人物和动作缓存已在 | 更新适配器；以 batch 8 为起点，不重生素材 |
| 语音 | MOSS 04 NF4/BF16，FP32 CPU codec | 旧 GPT-SoVITS v2 环境；预期 MOSS 目录缺失 | 原生安装 MOSS 依赖和两组模型，校验引用音频 |
| DSH / Humanity | 已安装、有人格和私有场次账本 | 新版服务端口未启动 | 固定版本安装；正式状态在切换时一致迁移 |
| B站客户端 | 官方直播姬 8.11.1.11202 已公开开播 | 本次未安装或登录验收新版客户端 | 官方签名程序准备；主播在目标机登录 |
| ComfyUI | 直播期间不需要参与实时推理 | 8188 运行，检查时队列为空、约 9 GB GPU 常驻 | 保留其他任务；启动本项目之前重新查资源 |
| Python | 人物 3.10、MOSS 使用便携 3.13 | 人物和 TTS 3.10.22、ComfyUI 便携 3.13.14 | 按组件分环境，不改用户 ComfyUI 依赖 |
| 磁盘 | 权重、原始录像不进 Git | 检查时约 399.6 GiB 空闲 | 模型、包缓存及备份预留空间 |

以上资源数据为检查瞬间值。旧配置、旧 PID 和文件夹名都不能证明当前进程可用；本次探测 8010、9880、3091、3092 未监听。首次 Torch 导入的 15 秒检查超时也被保留，随后只核实了解释器版本；没有把超时诊断改记为 GPU 推理通过。

## 3. 目录和版本管理

```text
C:\dev\虚拟数字人直播\
  Ai-Talk-Streamer\              # main 的完整 Git 检出，源码、文档、已验收素材
  assets\ models\ src\         # 现有运行素材、权重与上游源码
  configs\                      # 私有运行配置；不被 git pull 覆盖
  runtime\ tools\               # 原生环境和固定版本程序
  state\ backups\               # 正式状态、删除屏障、一致备份
  operations\migration-4090\    # 同步日志、版本回执、后续运行检查
  .setup\                       # 部署和进程记录，不能沿用旧 PID
```

Git 检出与运行根目录分离：在 `Ai-Talk-Streamer` 执行 `git pull` **不会自动更新运行根的适配器和进程**。部署时从已固定提交复制允许的应用源码和公开素材，备份被替换文件，然后执行安装适配器脚本。严禁把整个仓库以镜像删除模式覆盖旧运行根，否则可能删除权重、私有配置和状态。

目标机 Git 在 `tools\git\cmd\git.exe`，不依赖系统 PATH。同步使用公开 HTTPS origin；维护者在控制端通过原有 SSH origin 推送。4090 不需要保存 GitHub SSH 私钥。

```powershell
$ProjectRoot = 'C:\dev\虚拟数字人直播'
$ProjectGit = Join-Path $ProjectRoot 'tools\git\cmd\git.exe'
$ProjectRepo = Join-Path $ProjectRoot 'Ai-Talk-Streamer'
& $ProjectGit -C $ProjectRepo status --short
& $ProjectGit -C $ProjectRepo pull --ff-only origin main
& $ProjectGit -C $ProjectRepo rev-parse HEAD
```

同步验收至少包含：origin、分支、HEAD、干净工作区、Git 对象检查、全部跟踪文件与索引 blob 一致、关键文档存在、素材清单校验。最终完整提交号放在目标机 `operations\migration-4090\repository-sync.json`，避免将包含自身提交号的回执写入同一提交造成循环引用。

## 4. 素材和模型边界

| 内容 | 分发方式 | 核验 |
|---|---|---|
| 女A身份、人物图、选定场景 | Git `configs/characters`、`assets/vertical`、`output/imagegen`、角色档案 | 角色 ID、图片哈希 |
| 48 类已审定动作与原始生成素材 | Git `outputs/vertical/materials`、`source` | 仓库清单、分辨率/帧数、hash |
| 处理后 PNG、mask、latents、总动作库 | 复用 4090 已有 `src/LiveTalking/data/avatars` | `student_dorm_motion_bank_v3`、动作索引、帧和 mask 同步 |
| MOSS 10 款试听与 04 引用音频 | Git `web/voice-audio`、`assets/voices` | references.json 与指定 WAV hash |
| MuseTalk、Whisper、VAE 等权重 | 原 4090 安装 / `configs/model-files.csv` | 实际文件 hash，不重复下载已有效内容 |
| MOSS-TTSD-v1.0 | 原生模型目录，Git 外 | 原 3080 清单总文件 16,727,053,684 bytes；每文件 SHA-256 |
| MOSS-Audio-Tokenizer | 同上 | 原 3080 清单总文件 7,098,711,111 bytes；每文件 SHA-256 |
| MOSS vendor | 安装固定依赖或经审计迁移纯源码 vendor | 3080 既有 vendor 1,797 文件 / 140,615,028 bytes；排除缓存，记录版本 |
| 官方客户端与 Node | 现有准备脚本下载、校验、项目内解包 | 官方来源、归档 hash、Authenticode |
| 私有渠道、平台配置、记忆 | 单独受控迁移 | 不进入 Git，不打印 key，不复制正在写的数据库 |

两组 MOSS 模型合计约 **22.19 GiB**，不含依赖、缓存和运行内存。上表的大小是迁移源库存信息，**不是 4090 已下载证明**；运行前必须补齐实际文件 hash。模型 Python 代码启用了 `trust_remote_code`，应固定已审核的源码与配置，不能仅保留权重分片。

不要把试听 WAV 当作实时引擎、不要把目录存在当作模型可载入、不要为了迁移重新生成女A身份和动作。当前音色引用 SHA-256 为 `72c38cbcf3e06dd86d8edc5d4167f696b42bdac80b31e9f096fa300c94929fa4`。

## 5. 4090 参数起点

[机器可读示例](../../configs/deployment-target.example.json)记录目标。它是交付清单，不是启动器自动读取的配置；正式运行时写入实际私有文件。

| 文件 | 目标参数 | 说明 |
|---|---|---|
| `configs/livetalking.yaml` | `avatar_id=student_dorm_motion_bank_v3`、`batch_size=8`、`fps=25`、`model=musetalk` | JSON 格式的既有配置；保留 FP16 和完整动作 |
| 同上 | `tts=moss-ttsd`、`TTS_SERVER=http://127.0.0.1:9880`、`MOSS_VOICE_ID=v04` | 使用 activate_moss.py 写入 |
| `configs/moss-live.json` | 使用已有 example，v04、seed 20261026、segment 70、max tokens 800、CPU threads 8 | 路径必须指向目标机真实安装 |
| `configs/hardware-profile.json` | 4090 标记、batch 8、25 FPS、720×1280；启动门槛保守预留 | 门槛只允许尝试启动，不证明峰值安全 |
| `configs/livehime-policy.private.json` | 播放租约 30,000 ms，持续样本＋自然结束仍强制 | 用既有脚本生成；不修改历史策略规范 |
| `configs/platforms.private.json` | B站 `output_mode=livehime`、room 595139 | 不自动填写或导出平台凭据 |
| `configs/channel.env` | 用户已保存的 gpt-6-luna Responses 渠道 | 保留自定义渠道，不切换模型 |

**精度限制：** 当前 MOSS 服务固定 NF4 4-bit、BF16 compute，tokenizer/codec 在 CPU FP32。4090 首轮沿用真实实现，以分辨机器更换的收益。将语音整模改 BF16 或把 codec 移到 CUDA 是独立代码变更，不存在一个已经支持的 JSON 开关；必须先核实上游 dtype/device 行为，再增加配置、测试取消与语音完整性，不能在文档中标成现成能力。

**调参顺序：** 保留素材和 720×1280，先测试 batch 8、清理本项目重复播放器、单独测 GPU 竞争和编码开销；仅在证据表明显存/吞吐不合格时再考虑 batch 4。分开统计云端等待、MOSS 生成、codec、人物准备、播放和编码，不能把所有延迟归因于显存。

## 6. 原生安装顺序（后续执行）

1. 确认 4090 ComfyUI 的 `queue_running` 和 `queue_pending`，读取实际 GPU 进程。保留用户其他任务；若需腾显存，先确认占用归属，不能直接结束所有 Python 或重启所有服务。
2. 固定仓库提交；对运行根里的旧源码和配置做项目内备份。对比上游 LiveTalking 的固定版本和原有安装回执。
3. 按 `DEPLOYMENT.md` 复用人物 3.10 环境和有效模型。以已有准备脚本安装最新 integration，先执行 `deployment/activate_studio.py`，再安装 MOSS adapter 与 DSH hooks。
4. 给 MOSS 准备与目标 Python ABI 匹配的原生依赖；不盲目覆盖 ComfyUI Torch、torchaudio、Transformers。必要时建专用环境。载入前验证 imports 与 `soundfile`、重采样、CUDA、bitsandbytes；记录精确版本。
5. 填写目标 MOSS 安装路径，核验权重分片与引用音频；从运行根执行：

```powershell
Set-Location -LiteralPath 'C:\dev\虚拟数字人直播'
& '.\runtime\livetalking\Scripts\python.exe' -X utf8 -B deployment/activate_studio.py
& '.\runtime\livetalking\Scripts\python.exe' -X utf8 -B deployment/activate_moss.py --voice v04 --batch-size 8
& '.\runtime\livetalking\Scripts\python.exe' -X utf8 -B deployment/deploy_dsh.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deployment/install_dsh.ps1 -ProjectRoot 'C:\dev\虚拟数字人直播' -PythonExe 'C:\dev\虚拟数字人直播\runtime\livetalking\Scripts\python.exe'
```

6. 固定 Node 24.22.1、DSH 0.2.0-rc.2、Humanity 0.1.17，并核验 connector patch 回执。准备原生平台依赖 `scripts/install_platform_runtime.py`；官方直播姬使用 `scripts/prepare_bilibili_livehime.py` 校验签名并项目内解包。
7. 独立验收时使用独立测试状态路径或一致备份的隔离恢复结果，不与 3080 正式场次并行写同一个人格记忆。生成 Livehime 30 秒租约策略，最终切换时应用正式状态。
8. **先启动人物并完成真实特征预热，再加载常驻 MOSS**。使用 `scripts/start_studio.py --no-browser` 的既有顺序，检查日志而非仅检查端口。然后启动 DSH，核对 `/health`、`/api/dsh/status` 与无鉴权页面。不要同时开启旧 GPT-SoVITS 和 MOSS 去争抢 9880。
9. 用 Echo、短长句、打断和重连验证，再验证原云端渠道；测试完成关闭临时浏览器和页面。正式播放端只保留一个租约持有者。

以上步骤不能直接在尚未部署源码的 Git 子目录里执行：它们的 ROOT 是各自脚本上两级所在目录，运行根必须是已完成允许文件部署的 `C:\dev\虚拟数字人直播`。

## 7. 私有配置与记忆迁移

静态源码和音色素材可提前同步；活动记忆必须在最终切换时以一致备份为单位处理。

1. 在旧 3080 的直播姬先结束公开直播，等待结束状态；然后在平台页结束本地互动和采集。
2. DSH 从 LIVE→DRAINING，当前句结算后进入结束状态；检查未完成项、来源水位和静默窗口。不要把 `COMPLETED` 的本地播放确认改成观众端回执。
3. 从记忆管理功能创建一致备份：`VACUUM INTO` 捕获 WAL 状态，flush Humanity 后写 manifest；保存最新独立 deletion ledger、head 和人格版本。禁止只复制活动 `stream.sqlite3` 主文件。
4. 从正式管理状态核对没有本地活动场次后停止旧 DSH。保留旧 GPU、官方客户端或退出它们按实际需求处理；停止必须匹配本项目 exe、脚本、创建时间，不使用跨机 PID。
5. 在 4090 私下迁移渠道文件和平台必要配置，检查目标路径。直播姬登录状态通常是机器绑定内容，不将用户资料目录直接塞进 Git；主播在目标客户端登录。
6. 将一致备份、manifest 与最新删除链放入目标项目 `backups`，按记忆手册执行 `restore prepare`，检查 hash、schema、integrity/foreign_key、删除重放和新的 Humanity home，再在 Bridge 离线时 activate。
7. 4090 初次启动必须检查 `RECOVERING`、新 epoch/generation、投影状态、未知请求和队列。旧在途句保持 UNKNOWN，不自动重播；平台事件持久去重账本随一致状态保留。
8. 只有 4090 开启正式记忆写入与维护。3080 保留只作回滚，不能同时运行 daily/weekly 合并器写回正式数据。

人格 ID 不变：`female-a`、女A、林知夏；平台命名空间、稳定用户 ID 与 viewer 分区不重建，不用昵称猜测合并。不携带旧播放租约、不伪造完成样本、不将过去未播文本写成“已说过”。

## 8. 直播状态和下播整理

迁移不简化既有状态机：直播中依序处理输入和正式播出；完整播出才进入助手历史；下播后等待 120 秒静默再做整理。规则详见[直播状态](../dsh-humanity/LIVE_STATE.md)及[记忆流水线](../dsh-humanity/MEMORY_PIPELINE.md)。

| 时机 | 调度与提交条件 |
|---|---|
| LIVE / PAUSED / RECOVERING | 不执行后台记忆提取写入；前台请求保存一致来源与人格快照 |
| 场次结束＋120秒 | 唯一持久作业，冻结来源水位、revision、删除屏障与分区 |
| 每日 03:30 Asia/Taipei | 补齐未完成已结束场次；按游标增量消费，不全量重扫 |
| 周一 04:10 Asia/Taipei | 按变化的记忆 revision 校验来源/过期与维护导航 |
| 重新开播 | 提高 barrier，撤销维护租约；迟到模型结果不得提交 |
| 故障/重启 | 固定 checkpoint，幂等继续；不能清预算、复活删除、越过投影失败 |

每次接管最多 8 次后台模型调用、本地日最多 20 次，调用前占额；没有 usage 也计次数。单块最多 200 个新事件 / 24 KB、两条只读重叠，事务提交来源、事实、outbox 和消费游标。4090 不加载额外 GPU embedding 模型；公共 Humanity 投影和 viewer 私有事实分开。

## 9. 直播姬目标设置

目标机正式启动后访问 `http://REMOTE_4090_HOST:8010/platforms`。B站设置为 Livehime，房间 `595139`；浏览器源依然使用**目标机器自身回环**：

```text
http://127.0.0.1:8010/output.html?output=platform&renderer=livehime
```

源 720×1280、源音量 100%、声音输出到流；避免桌面/麦克风重复采集。画布 720×1280，NVIDIA H.264、30 FPS、3,000 Kbps、p5 为已测起点；人物仍为 25 FPS。4090 不因显存更大自动开启额外编码效果，先保留变量以便比较。

独立预览静音，不承担正式播放权威；直播姬源加载后关闭不用的 Chrome/Edge 页面。登录和人脸验证由官方客户端要求及账号本人完成，应用本身无鉴权。目标机公开开播只能在旧机下播、单写入者检查与本地验收后进行，仓库同步脚本不会点击开播。

## 10. 4090 验收门槛和回滚

| 阶段 | 必须提供的证据 |
|---|---|
| 仓库同步 | HEAD、origin、branch、干净状态、对象/工作区完整性、文档和素材检查 |
| 模型和环境 | 权重 hash、引擎实际版本、依赖导入、v04 reference hash、GPU 占用归属 |
| 五项本地场景 | 欢迎、去重、讲解、同场暂停恢复、两条连续留言；逐句 COMPLETED 与连续样本自然结束 |
| 云端与记忆 | 原配置兼容探针、跨轮回忆、观众隔离、下播压缩/每日/周作业；原有待验收项不可直接改为通过 |
| 媒体质量 | 真实客户端录制＋ffprobe，音频非静音与完整性、实际呈现 FPS、丢帧、全程显存和等待分项 |
| 真实平台 | 公开房间状态、CDN 解码、另一设备真实新弹幕→单次回复→实际可听，不仅是本地注入 |
| 长期运行 | 连续观察、断网/重连、不重复播报；记录测试时长，不能由十秒片段推断 |

若 4090 未达标，保留实际失败和录像，先排查资源竞争、加载顺序、解码和编码。回滚时 4090 先停止正式写入和公开直播，再生成最终一致备份，验证新事件水位后恢复到3080；不能直接启用较旧3080数据库并丢弃新互动。仅回滚源码时，保持数据库迁移兼容性检查，不倒写历史 schema/hash。

## English handoff

The current task archives the complete architecture and synchronizes the tracked repository to the 48 GB RTX 4090. Runtime activation is a subsequent stage. Keep the existing 3080 broadcast intact until a deliberate cutover; do not copy a live SQLite main file or run two authoritative memory writers.

Reuse the existing portrait motion bank, verify and install the missing MOSS runtime/models, deploy the pinned DSH/Humanity bridge and prepare the signed official Livehime client. Start with MuseTalk FP16 batch 8 and the current MOSS 04 implementation. A full-BF16 speech model or CUDA codec is a future code change, not a supported configuration switch. The final target must pass local speech, actual browser playout, state recovery, memory maintenance and real-account audience tests before being called operational.
