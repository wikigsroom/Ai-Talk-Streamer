# DSH + Humanity 实际实现与验收边界

[总方案](../DSH_HUMANITY.md) · [直播状态](LIVE_STATE.md) · [记忆流水线](MEMORY_PIPELINE.md) · [操作手册](RUNBOOK.md) · [验收定义](OPERATIONS_TESTING.md)

更新日期：2026-10-25。规范规定目标行为，本页记录实际代码和证据。已实现、隔离测试通过、真实渠道通过、真实媒体通过是不同结论。

## 1. 当前交付状态

| 阶段 | 已有实现 | 尚需完成的验收 |
| --- | --- | --- |
| P0 原生兼容宿主 | 固定 Node/npm lock、官方 DSH Agent、Humanity 连接补丁、标准派生预设、minimal 负例、窄工具目录 | 用户真实渠道的 Responses、工具调用、取消与最终回复 |
| P1 状态与播放 | SQLite owner fence、FIFO、独立请求/音频、样本映射、权威租约、自然结束回执、取消屏障；真实 Echo 完整/取消/恢复及两播放器接管通过 | OBS 应用实际混音录制、长时切换与断网录像 |
| P2 持续对话 | 每请求新 Agent、人格/渠道快照、当前场次已播窗口、滚动提取摘要、分区长期检索；受控 HTTP 人格在途快照通过 | 真实模型 20 轮连续对话、跨场召回 |
| P3 后台记忆 | 结束水位、静默窗口、持久作业、日/周调度、分块/预算/退避、原子提交、公共镜像 outbox | 真实渠道下完整整理及 S4；长期资源观察 |
| P4 管理与恢复 | 管理页、身份邀请、事实修订/补偿撤销、删除屏障、WAL 一致备份、隔离恢复与离线切换 | 多浏览器端到端管理与恢复操作验收 |
| P5 发布 | 已有模块测试、原生宿主探针及媒体测试程序 | A01–A40 全部证据、S1–S5 五段实际录像；目前不能宣称整体验收完成 |

3080 新增后端采用原生 Windows 进程，未调用 Docker、WSL 或虚拟机。角色为女A·林知夏，媒体仍使用 MOSS 04、MuseTalk、既有动作库和 720×1280 竖屏。

## 2. 默认继承网页模型连接

唯一渠道真源为项目内 `configs/channel.env`，由原有演播台渠道设置写入。DSH 直接读取，不要求重复填写密钥。

1. 接收请求时校验地址、协议、实际模型 ID、key 和原有 system prompt。
2. 生成 provider_revision；配置对象和 key closure 绑定本轮 Agent 的 launch environment。
3. DSH provider 名是本地路由名，传给渠道的 model 仍是用户指定值。
4. 网页修改后仅新请求读取新快照；在途请求继续使用旧快照。
5. 新 revision 的真实兼容探针未完成前，AI 不 ready。Echo 保留为明确选择的原文播报模式。

2026-10-25 读取到的配置为 `gpt-6-luna` / `responses`。真实渠道请求曾超过 35 秒未返回 HTTP 响应，DSH 兼容请求亦超时，所以当时 `persona_injection_ready=false`。随后以相同已保存渠道再次执行真实 DSH 兼容探针，90.046 秒后返回 500 INTERNAL_ERROR，仍未通过。受控测试端点和 Echo 不证明真实 AI 渠道已恢复。

公开状态只返回 model、protocol、revision、source、has_key，不输出密钥、operator token 或 media token。私有配置、SQLite、运行日志、备份不提交 Git。

## 3. 代码与职责

| 位置 | 实际职责 |
| --- | --- |
| [host.mjs](../../backend/dsh-bridge/host.mjs) | 官方 DSH boot/Agent、Humanity 注入、作用域工具 guard、provider 绑定、调用计量 |
| [channel.mjs](../../backend/dsh-bridge/channel.mjs) | 网页渠道解析、校验、规范 JSON、revision |
| [persona.mjs](../../backend/dsh-bridge/persona.mjs) | 女A 人格及不可自动修改的固定身份 |
| [policy.mjs](../../backend/dsh-bridge/policy.mjs) | 严格策略校验、版本/隔离/存储约束、不可变快照 |
| [state.mjs](../../backend/dsh-bridge/state.mjs) | 直播/请求/utterance、租约、映射与回执 |
| [server.mjs](../../backend/dsh-bridge/server.mjs) | 回环 HTTP、权限、真实渠道探针、媒体调用和管理 API |
| [auth.mjs](../../backend/dsh-bridge/auth.mjs) | 管理登录、稳定观众邀请、匿名场次身份、受限 OBS 凭据 |
| [humanity-port.mjs](../../backend/dsh-bridge/humanity-port.mjs) | 原生人格发布、公共投影、revision 对账、文件 flush |
| [store.mjs](../../backend/memory/store.mjs) | SQLite 迁移 hash、WAL/FULL、唯一 owner、同步事务、写故障锁止 |
| [service.mjs](../../backend/memory/service.mjs) | 来源资格、先分区后排序、上下文、候选规则、合并与镜像 |
| [scheduler.mjs](../../backend/memory/scheduler.mjs) | 持久调度、分块、预算、租约、原子游标与断点恢复 |
| [administration.mjs](../../backend/memory/administration.mjs) | 修订、归档、等值合并、整组补偿、范围重建、删除 ledger、一致备份 |
| [query.mjs](../../backend/memory/query.mjs) / [events.mjs](../../backend/dsh-bridge/events.mjs) | revision 绑定 keyset 分页、持久元数据 SSE、权限过滤和背压 |
| [restore.mjs](../../backend/memory/restore.mjs) | 新目录恢复、删除重放、完整性检查、离线切换 |
| [dsh_bridge.py](../../integration/dsh_bridge.py) | 8010 同源代理、内部媒体认证、OBS 本机凭据 |
| [moss_tts.py](../../integration/moss_tts.py) | 完整 MOSS WAV、有效样本数/hash、请求版本校验 |
| [gpu_worker.py](../../scripts/gpu_worker.py) | 原生 GPU 隔离进程；语音提交前准备现有推理工作区，避免首个有声包承担首次分配延迟 |
| [local_broadcast.py](../../integration/local_broadcast.py) | 映射先持久化后转发、JSON 控制 + PCM/JPEG、取消清队列 |
| [viewer_buffer.py](../../integration/viewer_buffer.py) | 拥塞仅丢 JPEG，保留 PCM/映射，过慢连接重连 |
| [dsh-playback.js](../../web/dsh-playback.js) | AudioContext 样本前缀、自然结束、心跳、取消确认 |
| [memory.html](../../web/memory.html) / [memory.js](../../web/memory.js) | 人格、记忆、来源、作业、预算、邀请和备份管理 |

Humanity 四个适配点由 [patch_humanity.py](../../deployment/patch_humanity.py) 校验固定版本和源码锚点后修改。原文件保存在项目 .setup，安装记录保留文件 hash。Python 不直接编辑 Humanity storage JSON。

DSH 启用后，旧 `/human`、`/humanaudio`、`/set_audiotype`、`/interrupt_talk`、`/record` POST 入口返回 `409 DSH_LEGACY_ROUTE_DISABLED`。播报必须经过有身份、generation 和播放回执的路径；网页录制使用浏览器 MediaRecorder。关闭 DSH 后才恢复旧接口行为。

## 4. 模型实际看到的内容

系统层包含项目规则、已发布 Humanity 人格、允许注入的原生公共记忆和管理员渠道提示词。标准派生预设 `complete=false`，保留插件段；minimal 负例读取固定包中的真实 minimal 人格配置。

服务端筛选的上下文 JSON 作为当前 user 消息中的数据块提交，随后附本轮原文。不依赖预设可能关闭的 runtime-context 段，不注入运行目录、环境或系统工具资料。受控 HTTP 请求探针检查了上下文哨兵确实到达端点。

上下文包含 persona_version、公共/本人长期记忆、当场滚动摘要、最近已确认输入和完整播出话语。其他观众专属资料在 SQL 阶段排除；已由 Humanity 注入的公共条目从 JSON 列表去重。

每轮工具只有 stream_memory_recall、stream_memory_propose；离线整理只有 stream_maintenance_result。编程、Shell、文件编辑、委派插件未挂载，执行 guard 再拒绝目录之外的名称。中间文本和工具思考不送 TTS。

## 5. 当前记忆能力的精确范围

目前自动激活采用完整原句规则，仅覆盖饮品偏好（本人明确喜欢茶/咖啡）和回答风格（以后先结论/详细一些）。含否定、临时日期、他人主体、假设、玩笑等，不能靠截取引用自动激活。

超出规则的有据候选为 proposed，由管理员结合来源明确修订批准；身份候选拒绝。这不是通用语义事实自动审核器。相同键和值合并来源，相反值进入 conflicted，双方均不召回。更正产生 revision，补偿撤销不能覆盖后续修改。

管理员可在网页按分区/状态/事实键分页，并执行带 revision 的归档、同分区等值合并和整组补偿撤销。重建必须指定已结束场次、来源版本、分区及起止事件；不能绕过静默、预算和删除屏障。重复抽取完全相同的证据不再制造修订，归档后的旧证据也不会复活。实际 HTTP 字段和失败处理见[管理契约](ADMINISTRATION.md)。

状态事件以持久 SSE 元数据订阅通知，Python 8010 代理逐块转发并保留 Last-Event-ID；不输出原始事件正文。viewer 看不到其他请求的标识或内容。暂停、恢复、下播必须带当前场次和 expected_revision，旧页面不能取消或结束新场次。

当场摘要采用有界引用提取，保留初始话题、显式约定线索和未得到完整播出回答的问题。模型后台摘要只是导航，不能替代原始证据。跨场当前依靠已激活的长期事实；任意故事、情绪和开放问题的跨场自动续写尚未完成真实模型验收。

## 6. 周期任务的实际语义

| 时机 | 行为 |
| --- | --- |
| 正常下播 | 当前句最多排空 30 秒，结束水位与作业同事务提交 |
| 下播后 120 秒 | 按本场/分区/来源修订/策略唯一 job_key 增量整理 |
| 每 5 秒 | Bridge 查询持久作业，不创建额外 OS 任务或 Codex 定时器 |
| 每日 03:30，Asia/Taipei | 补齐已结束且未完整消费的场次，已有作业优先续跑 |
| 每周一 04:10 | 按变化的 revision 检查来源/过期事实，生成维护摘要；不回扫全量聊天，不自进化人格 |
| 重启 | 补查最近 12 小时 occurrence，唯一键去重 |
| 再次开播 | 提高 barrier、撤销旧租约、取消网络等待，旧结果不得提交 |

单块最多 200 新事件、24,000 UTF-8 字节，前两条旧事件只读重叠。一次接管最多 8 个调用，后台本地日最多 20 次；调用前即占额度，usage 缺失标 USAGE_UNKNOWN。未配置价格时仅报告调用/token，不推算金额。

渠道不可用时 DEFERRED/channel_unavailable，不冒充空摘要成功，不推进游标。镜像不可用时保留主账本，停 PROJECTING；重试投影不重复调用已消费块的抽取模型。

## 7. 证据与剩余门槛

原始输出位于项目私有 outputs/dsh-humanity。模块测试覆盖状态、播放 JS、分区、预算、修订、删除后旧备份恢复和写故障。崩溃测试用真实子进程在 WAL 提交前/后退出；宿主探针使用真实 DSH/Humanity 和受控 HTTP 模型端点。

[真实媒体测试程序](../../tests/dsh-media-smoke.cjs) 明确使用 Echo。2026-10-25 实际原生 Chrome 已通过完整播报、缓冲阶段取消及取消后再播，两条完成请求均收到自然结束回执；最新一轮采样画面约 25.37 FPS、PCM 无丢包，首条人声区间的排程间隙在浮点误差内为零。这证明本地媒体及播放账本的对应范围，未使用云端 LLM，不证明人物理解、跨场回忆或 S1–S5 通过。复验的精确指标以[机器记录](../evidence/dsh-humanity-runtime.json)为准，截图、完整录像和 GIF 见[实机记录](MEDIA.md)。

两次定位到的失败仍保留原因：MOSS 常驻时单独重启人物曾降至约 0.7 FPS；按既有加载顺序重启后，首次有声推理仍曾产生约 2.42 秒排程间隙。修复分别为项目内有序重启，以及在完整 WAV 生成后、音频入队前运行相同精度/批次的准备推理。没有把该等待隐藏成实时出声，也没有为此更换音色或降低画面规格。

[双播放器实机程序](../../tests/dsh-authority-smoke.cjs) 在两个真实 Chrome 页面运行演播台和本机 OBS 浏览器源：普通预览无权抢占、受限 OBS 凭据不能发送聊天，OBS 已播 19,372 个样本后接管，旧句 INTERRUPTED、新句 COMPLETED。另修复了迟到取消消息误用新 lease 及旧 heartbeat 错误撤销新 lease 的竞态。这里没有运行 OBS 应用混音器，不将页面测试等同于最终推流录制。

模块证据包括 40 项 Node 测试、3 项 Python ViewerBuffer 测试、原生 aiohttp CORS/旧入口阻断及 SSE 实时转发检查。隔离管理测试使用真实固定版 DSH/Humanity、HTTP 与 Chrome，完成网页分页、归档、补偿、合并、范围重建和订阅；使用明确测试事实，不修改正式记忆、不调用 LLM/TTS。真实宿主模型探针另使用受控 HTTP 端点，检查 7 次请求中的标准/官方 minimal 正负例、上下文确实入请求、人格在途冻结、投影增删改及重启。两分区各 5000 条合成事实的 20 次检索测得 p95 约 32.62 毫秒；这是短时合成负载，不能外推长时稳定性。

仍阻断完整验收的门槛：真实渠道兼容、真实 20 轮对话、A01–A40 剩余实机证据、S1–S5 五段录像、长时资源观察。测试替身、静态检查、截图和原版本视频不能替代；逐项状态见[验收执行记录](ACCEPTANCE.md)。

## 8. 迁移和回退

数据库已有 v1 基础表及 v2 运行补充表，均有 hash；不得改写已应用迁移。新结构增加新迁移并先备份。连接器版本 stream-humanity-v1，运行策略 dsh-live-v1.0。

新库记录迁移文本 LF 规范化 SHA-256；已有库允许同一精确内容的历史 LF/CRLF hash，避免 Windows 传输或 Git 换行转换造成假损坏。除此之外的内容/hash 差异仍拒绝启动，不修改已记录的旧 hash。已在隔离 SQLite 中验证兼容与内容不匹配拒绝，并在现有 3080 库重启验证。

DSH 故障显示未就绪，不静默走旧无状态 LLM。回退先下播、保留库、验证 schema；旧备份先重放最新独立删除 ledger。激活若会丢失比备份更新的人类互动则拒绝切换。
