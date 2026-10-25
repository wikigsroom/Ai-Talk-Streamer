# 数据、接口与插件连接契约

[总方案](../DSH_HUMANITY.md) · [直播状态](LIVE_STATE.md) · [记忆流水线](MEMORY_PIPELINE.md) · [部署与验收](OPERATIONS_TESTING.md)

本文定义项目业务契约。所有 `/v1/*`、stream_* 工具、HumanityPort 和数据库表是项目设计，不是上游 DSH 公共接口。首轮原生实现采用下述 `/api/dsh/*` 绑定；后文 `/v1/*` 表达目标语义，不能直接当作当前可调用地址。未落地能力仍列为验收门槛。

## 当前原生实现的 HTTP 绑定

浏览器经 8010 同源代理，内部服务直连 3092。当前错误为 `{error:"CODE"}`，模型错误额外含布尔 retryable，请求返回 status 字段；后文统一对象错误信封仍为目标语义。身份从 cookie/bearer 解析，正文中的 principal/viewer_id 不授予权限。已实现的分页、持久事件订阅和管理写操作详见[管理契约](ADMINISTRATION.md)。

### 当前模型故障码

以下是已实现的桥接码，分类依据固定适配器的 failure.code 或取消信号，不把上游原文当作可公开错误消息。

| HTTP | error | retryable | 原因 |
| --- | --- | --- | --- |
| 504 | MODEL_TIMEOUT | true | 截止时间/流空闲/适配器超时 |
| 409 | MODEL_CANCELLED | false | 明确主动取消；不与超时混用 |
| 429 | MODEL_RATE_LIMIT | true | 上游限流 |
| 502 | MODEL_AUTH_FAILED | false | 上游鉴权/凭据失败；不表示本地管理身份失效 |
| 502 | MODEL_QUOTA_EXHAUSTED | false | 上游账户额度不足 |
| 502 | MODEL_UPSTREAM_UNAVAILABLE | true | 上游服务端故障 |
| 502 | MODEL_TRANSPORT_FAILED | true | 连接或流提前关闭 |
| 502 | MODEL_RESPONSE_INVALID | false | 非法响应/空输出 |
| 502 | MODEL_REQUEST_REJECTED / MODEL_CONTEXT_EXCEEDED | false | 上游请求或上下文限制 |
| 502 | DSH_GENERATION_FAILED | false | 不能安全细分的宿主失败 |

retryable 是调用方提示，不授权自动重发前台播报。SDK/Harness 自动重试为零；后台整理仍受独立的租约、次数、退避和预算控制。兼容探针单飞，重复在途探测返回 PROBE_IN_PROGRESS；失败探针保存 passed=false、当前 provider_revision、错误码和用时，不能沿用旧成功记录维持 AI 就绪。

| 实际路径 | 方法 / 输入 | 权限与含义 |
| --- | --- | --- |
| /api/dsh/status | GET | 受限状态；不含其他观众输入/密钥 |
| /api/dsh/session | POST {} | 当前场次匿名身份，跨场不关联 |
| /api/dsh/login | POST {token} | operator 或稳定观众邀请换 HttpOnly cookie |
| /api/dsh/probe | POST {} | 管理员执行真实渠道人格/工具兼容探针 |
| /api/dsh/broadcast/start | POST {} | 管理员创建唯一活动场 |
| /api/dsh/broadcast/ready | POST {broadcast_id,expected_revision,mode} | STARTING/RECOVERING/PAUSED→LIVE；mode=echo/chat，校验依赖、租约和 CAS |
| /api/dsh/broadcast/pause、/end | POST {broadcast_id,expected_revision} | 管理员暂停/排空下播；旧场次或版本拒绝 |
| /api/dsh/requests | POST {text,mode,idempotency_key,public_input?} | 自己分区输入，只有管理员可声明公共输入 |
| /api/dsh/requests/{id} | GET | 管理员或该请求主体查询 |
| /api/dsh/cancel | POST {request_id?} | 管理员停止当前/指定请求 |
| /api/dsh/playback/claim | POST {broadcast_id,consumer_id,replace?} | 管理员显式换权；OBS 受限凭据不能 replace |
| /api/dsh/playback/heartbeat、/receipt、/cancel-ack | POST | 校验 consumer、lease、epoch、样本、序号和取消窗口 |
| /api/dsh/persona | GET / POST {document,expected_version} | 管理员读取/发布；具体允许字段见实现 |
| /api/dsh/memory | GET ?limit&cursor&subject_key&state&fact_key | 管理员 keyset 分页，默认 50、最多 200；修改后旧 cursor 返回 409 |
| /api/dsh/memory/source?memory_id=... | GET | 管理员查看来源和 revision |
| /api/dsh/memory/correct、/undo、/delete | POST | 管理员带 operation_id/revision 修订、补偿或删除 |
| /api/dsh/memory/archive、/merge | POST | 管理员带操作键、输入 revisions、reason；归档或同分区等值合并 |
| /api/dsh/events | GET ?after=seq，Last-Event-ID | 已登录 operator/viewer 的持久 SSE 元数据订阅；正文不进入流 |
| /api/dsh/broadcasts | GET | 管理员读取最近 50 场状态、来源版本和封口水位 |
| /api/dsh/jobs | GET | 管理员读取任务、调用账与调度 occurrence |
| /api/dsh/jobs/rebuild | POST | 管理员明确选择已结束场次/分区/起止水位/来源版本/reason，202 入队 |
| /api/dsh/jobs/resume、/cancel | POST {job_id} | checkpoint 重试/取消，不清预算 |
| /api/dsh/viewers | POST {label} | 管理员创建稳定邀请，只首次返回邀请凭据 |
| /api/dsh/backup | POST {} | 管理员下播一致备份 |
| /api/dsh/shutdown | POST {} | 管理员；活动场未结束时拒绝 |
| /internal/audio-ready、/media-map、/failed | POST | 内部 media token；不暴露给普通网页 |

管理页使用持久 SSE 通知与 GET 回读，保留轮询兜底。上述归档、合并、补偿、分页和有界范围重建均已落地；它们不授予自动推断通用事实或修改人格身份的权限。任务列表/单条事实的完整修订链当前仍未通用分页。当前 SQLite 迁移是 backend/memory/migrations 中的 v1/v2；下面示例 SQL 是基础设计，不应由操作者手工在生产库重复执行。

## 1. 配置与版本真源

| 文件 | 性质 | 使用方式 |
| --- | --- | --- |
| [bridge-policy.example.json](examples/bridge-policy.example.json) | 本项目策略格式 | 默认由 policy loader 读取并删除 example_only；自定义运行文件必须严格校验 |
| [humanity-config.example.json](examples/humanity-config.example.json) | Humanity 0.1.17 配置对象 | 由版本适配器映射到插件配置；不是整份 cordis.patch.yml |
| [event-envelope.schema.json](examples/event-envelope.schema.json) | 项目存储事件 JSON Schema | 先检查信封，再按 event_type 检查载荷和权限 |
| [state-schema.sql](examples/state-schema.sql) | SQLite v1 结构设计 | 实际由已实现迁移 runner 应用固定 hash 的 v1/v2 迁移 |

配置至少记录 policy_version、prompt_version、connector_version、persona_version、provider_revision 和 schema_version。热更新只影响新请求；在途请求继续携带原快照，不能中途换模型、人格或判断规则。

Humanity 配置启用 persona 与 balanced memory，但仅启用 longTerm 公共投影，关闭 work/session 自动层、decay、evolution、dream、vector。原生记忆工具仍须 guard；仅设置这些开关不能实现观众隔离或来源审计。

多个角色或多个房间不能共享同一份未分区的 Humanity 长期库。首版只绑定 female-a / room-main 的一个 DSH_HOME；扩展时每个 character/room 使用独立 home，或先实现经过测试的严格投影隔离。只更换工作目录不会隔离原生长期层。

## 2. 标识与版本字典

| 字段 | 生成者 | 规则 |
| --- | --- | --- |
| character_id | 发布的角色档案 | 不从显示姓名推导；女A为 female-a |
| room_id | 服务端直播间配置 | 可映射平台房间；不是浏览器 tab ID |
| broadcast_id | Bridge | 每次正式开播新建；显式恢复同场时保留 |
| principal_id | 服务端身份解析 | 区分 operator、已验证 viewer、匿名 viewer、内部服务 |
| viewer_id / subject_key | 身份解析服务 | 对平台稳定 UID 做房间范围映射；不使用昵称 |
| request_id | Bridge | UUID 等足够强的唯一 ID；不只使用毫秒时间 |
| utterance_id | Bridge | 绑定 request_id 与 segment_index |
| runtime_epoch | room owner | 进程接管、恢复或更换播出权威时递增 |
| generation | room dispatcher | 激活/取消/抢占时递增，普通入队不递增 |
| event_seq | SQLite | 全局递增提交序号，决定本地事实顺序 |
| source_revision | 来源控制服务 | 迟到证据、更正、删除导致来源资格变化时递增 |
| memory_revision | 主账本 | 每次事实变更事务递增；不因普通检索而增长 |
| lease_generation | 作业调度器 | 每次任务接管递增，阻止旧 worker 迟到提交 |
| deletion_generation | 删除服务 | 删除/撤销控制水位；缓存与恢复必须验证 |

稳定观众映射须使用服务端拥有的不可伪造凭据或平台连接证据。可用 HMAC 将平台 UID 映射为项目内部 ID，映射密钥仅本地保存；未经验证的页面 JSON 不能声明自己是另一个 viewer_id。

anonymous viewer 不具备跨场身份，不能后台自动把两次匿名访问合并。身份关联、拆分与迁移均是独立管理操作，有来源与审计事件。

## 3. 事件信封与载荷注册

存储信封参考 JSON Schema。`occurred_at` 是生产者声称的发生时间，`received_at` 是 Bridge 接收时间；状态顺序使用 event_seq。所有持久时间采用 UTC ISO 8601，调度显示可转换为 Asia/Taipei。

payload_sha256 对规范化 JSON 字节计算：UTF-8、键稳定排序、固定分隔符、不依赖平台换行。canonicalization_version 必须固定在实现中并记录版本。哈希只能证明内容一致性，不能替代身份与授权验证。

| event_type | 必须具有的载荷 | 允许生产者 |
| --- | --- | --- |
| broadcast.start_requested / started | persona_version、依赖状态、epoch | operator → Bridge |
| broadcast.paused / resumed | 原因、旧/新 generation、版本 | operator → Bridge |
| broadcast.end_requested / ended | 排空策略、截止水位、source_revision | Bridge |
| broadcast.recovered | 旧 owner、新 epoch、恢复选择 | operator → Bridge |
| input.accepted | 原文或正文引用、mode、principal、去重键 | 经验证的输入适配器 |
| request.activated / cancelled / failed | 请求状态、generation、原因、barrier_id? | Bridge |
| assistant.text_ready | final_speech、文本 hash、DSH session_id | DSH adapter，经 Bridge 验证 |
| tts.audio_ready | utterance_id、WAV hash、有效样本数、采样率 | Python 媒体适配器 |
| media.mapping_committed | transport instance、映射版本、样本/包范围 hash | Python → Bridge |
| utterance.playback_started / completed | 权威身份、观察版本、连续样本与确认等级 | Bridge 从回执归纳 |
| utterance.interrupted / unknown | 最后可信前缀、缺失证据、取消屏障 | Bridge |
| memory.proposed / revised / merged | 分区、候选/事实版本、来源与决策 | 经验证的工具或整理器 |
| memory.deleted / source.redacted | 删除范围、generation、失效对象 | 管理服务 |
| job.created / checkpointed / completed | job_key、输入水位、块、租约代数、统计 | 调度器 |

媒体包映射可压缩并批量持久化，不必每 40 ms 写一条完整事件。在线回执只在其依赖的映射已持久后提交为可信进度；尚未落盘的回执暂存并等待。最终完成事件必须引用最终映射 hash，崩溃后不能靠丢失的内存映射补证。

事件元数据 append-only；正文存 `event_payloads`，删除时可置为 redacted。读取被清除正文返回明确 redacted 状态，不把 null 当成一条空白但有效原文。删除必须覆盖摘要、候选、历史 revision、outbox、缓存与导出中相关正文，不能只清 event_payloads。

## 4. 内部 API 的传输原则

Bridge 使用原生回环 HTTP，默认 `127.0.0.1:3092`；DSH 管理端默认 `127.0.0.1:3091`。这些端口为方案分配，部署前确认无冲突。现有 8010 演播台通过受控代理调用 Bridge，浏览器不直接获得内部 bearer token。

全部写 API 必须有内部认证、幂等键和服务器派生的作用域。operator 管理操作额外校验控制身份；同源检查本身不足以证明管理员身份。播放端凭据只允许对应租约的心跳/回执，不能创建作业或编辑人格。

普通状态接口只返回角色显示名、状态和匿名指标；不能暴露云端密钥、Bridge token、其他观众原文或绝对个人目录。服务部署仍限于用户已配置的可信网络访问范围，未实现身份控制前不能扩大管理端访问面。

### 4.1 直播控制与请求

| 方法与路径 | 输入 | 成功结果 | 幂等/版本 |
| --- | --- | --- | --- |
| GET `/v1/health` | 无 | schema、connector、依赖状态、注入探针结果 | 无敏感配置 |
| POST `/v1/rooms/{room}/broadcasts` | character_id、persona_version、控制身份 | 202：broadcast_id、STARTING、epoch | Idempotency-Key |
| POST `/v1/broadcasts/{id}/pause` | expected_revision、reason | 新 revision 与 PAUSED | 版本 CAS |
| POST `/v1/broadcasts/{id}/resume` | expected_revision、authority 准备状态 | LIVE 或 RECOVERING | 版本 CAS |
| POST `/v1/broadcasts/{id}/end` | expected_revision、drain/immediate | DRAINING、随后 job_id | 重试复用原下播动作 |
| GET `/v1/broadcasts/{id}` | 管理或受限读身份 | 状态、epoch、health、队列、权威与整理状态 | 返回 revision |
| POST `/v1/broadcasts/{id}/requests` | input、mode、queue_policy；身份由服务端注入 | 202：request_id、QUEUED | 同键同 hash 复用；异 hash 409 |
| GET `/v1/requests/{id}` | 所属访问范围 | 阶段、终态、确认等级、已播前缀 | 不把生成稿显示成已播稿 |
| POST `/v1/requests/{id}/cancel` | expected_revision、reason | barrier_id 与取消中状态 | 同 barrier 不重复取消 |
| GET `/v1/events?after={seq}` | 已授权 room scope | SSE：持久状态事件与游标 | 断线从 after 恢复，心跳不入事实日志 |

202 表示接纳，不表示已完成。状态变更由事件订阅或 GET 查询获取。请求失败不得返回 200 加一句“成功”但只在日志里写错误。

### 4.2 播放端 API

| 路径 | 用途 | 必须检查 |
| --- | --- | --- |
| POST `/v1/broadcasts/{id}/authority` | 管理员授予或切换 authority | 权限、旧租约清理、epoch 更新 |
| POST `/v1/playback/heartbeat` | 续租 | consumer、lease、authority_epoch 与房间绑定 |
| POST `/v1/playback/progress` | 样本前缀回执 | 租约、已映射范围、单调序号、输出状态 |
| POST `/v1/playback/cancel-ack` | 取消屏障的最后结算 | barrier、冻结样本前缀、取消窗口 |
| POST `/v1/media/events` | Python 推送阶段与映射 | 内部身份、request、epoch、generation、事件幂等 |

普通演播台预览仅查询指标，不自动获得 authority。首版明确一条记录可以只有一个权威租约；换权威后不拼接不同租约的音频进度。

### 4.3 记忆、人格和作业 API

| 路径 | 用途 | 约束 |
| --- | --- | --- |
| GET `/v1/memory` | 按分区、状态和 fact_key 分页 | 服务端决定可访问的 subject_key |
| GET `/v1/memory/{id}/sources` | 查看来源、播放状态与修订链 | 不把其他观众正文泄露给普通观看者 |
| POST `/v1/memory/proposals` | 管理或工具暂存候选 | 原文来源和实际主体强校验 |
| PATCH `/v1/memory/{id}` | 更正事实 | expected_revision + reason；产生新 revision |
| POST `/v1/memory/{id}/archive` | 停止默认召回 | 主账本和投影同步意图同事务 |
| POST `/v1/memory/merge` | 受控合并 | 同分区、明确关系、输入 revisions |
| POST `/v1/memory/merges/{id}/undo` | 补偿式撤销 | 不覆盖后续合法修订 |
| POST `/v1/memory/delete-subject` | 删除和阻止再导入 | tombstone、正文清除、摘要失效与 outbox |
| GET `/v1/persona` | 查看已发布与待发布人格 | 返回版本、hash、来源 |
| POST `/v1/persona/proposals` | 表达层变更建议 | 不直接作用于在途直播 |
| POST `/v1/persona/publish` | 管理员发布新版本 | diff、expected_version、固定身份核验 |
| GET `/v1/jobs` | 作业、预算、进度 | 错误和等待原因必须可见 |
| POST `/v1/jobs/rebuild` | 选择范围重建 | 指定关闭场次、策略和分区，不默认全库 |
| POST `/v1/jobs/{id}/retry` | 重试失败作业 | 复用 checkpoint；不能重置预算记账 |
| POST `/v1/jobs/{id}/cancel` | 取消后台任务 | 失效 lease；已提交块保留 |

## 5. 请求与错误示例

以下是 Bridge 内部收到的请求示例。viewer_id 由 Python/平台适配器验证身份后附加，浏览器不能任意填写这个字段。

```json
{
  "mode": "chat",
  "input": "下次能先给结论吗？",
  "queue_policy": "enqueue",
  "principal": {"principal_id": "viewer-principal-01", "viewer_id": "viewer-01"},
  "expected_runtime_epoch": 12
}
```

```json
{
  "accepted": true,
  "request_id": "req-01",
  "broadcast_id": "bc-01",
  "state": "QUEUED",
  "queue_position": 1,
  "revision": 1
}
```

错误统一含 error.code、error.message、retryable、correlation_id，不回显密钥或原始上游请求头。

| HTTP | code | 行为 |
| --- | --- | --- |
| 400 | invalid_payload / unknown_field | 不接纳，不产生模型费用 |
| 401/403 | unauthenticated / scope_denied | 不相信客户端提供的主体 |
| 409 | revision_conflict / idempotency_conflict / stale_epoch | 返回当前 revision 或重取状态指引 |
| 409 | broadcast_not_live / authority_unavailable | 不启动新 AI 或媒体请求 |
| 429 | queue_full / budget_exhausted | 显示排队/预算原因；遵守退避 |
| 503 | dependency_unavailable / state_store_unavailable | 不悄悄切无记忆后端 |
| 422 | source_invalid / memory_conflict | 候选保留为拒绝/待处置，不激活 |

## 6. DSH 与 Humanity 连接端口

### 6.1 DshSessionPort

项目 wrapper 提供 `createStandardTurn`、`observeFinal`、`cancelTurn`、`inspectTurn`、`probePromptInjection`。wrapper 是本项目接口名；内部映射到固定 DSH 版本实际支持的 Agent/Session API，不能假造上游方法名。

```typescript
interface DshSessionPort {
  createStandardTurn(input: {
    sessionId: string;
    requestId: string;
    contextSnapshotId: string;
    promptSections: readonly ProjectPromptSection[];
    allowedTools: readonly string[];
    modelRouteRevision: string;
    abortSignal: AbortSignal;
  }): Promise<TurnHandle>;
  observeFinal(handle: TurnHandle): AsyncIterable<ProjectTurnEvent>;
  cancelTurn(handle: TurnHandle, barrierId: string): Promise<CancelReceipt>;
  inspectTurn(sessionId: string): Promise<ProjectTurnStatus>;
  probePromptInjection(): Promise<InjectionProbe>;
}
```

ProjectPromptSection、TurnHandle 等为待实现项目类型，例子只规定边界。adapter 必须过滤工具中间文本，只在终轮提取最终回答。取消回执不能解释成供应商确定停止计费。

一轮 Agent 完成后通过官方 disposer 释放活实例；持久日志保留。不能每条消息新建 Web UI、浏览器 tab 或长驻子进程。后台整理可复用一个受限 provider 客户端，但其会话与预算独立。

### 6.2 HumanityPort

Humanity 连接补丁提供以下窄接口，由同一 Node 宿主调用，不开放任意文件读写。必须为每个操作附加 operation_id 与 revision，持久保存去重结果；实现可以基于固定插件公开面，若公开面不足则使用受维护的小补丁并记录其 diff/hash。

```typescript
interface HumanityPort {
  probe(): Promise<HumanityCapabilities>;
  readPersona(): Promise<PersonaSnapshot>;
  publishPersona(input: ApprovedPersonaPublication): Promise<PersonaReceipt>;
  setNativeMemoryInjection(input: { enabled: boolean; expectedMirrorRevision: number }): Promise<void>;
  applyPublicProjection(input: PublicProjectionOperation): Promise<ProjectionReceipt>;
  inspectProjection(memoryId: string): Promise<ProjectionSnapshot | null>;
  routeWorkbenchIntent(input: AuditedWorkbenchIntent): Promise<IntentReceipt>;
}
```

PublicProjectionOperation 不接受 viewer 数据；Bridge 与 connector 双方都校验。ProjectionReceipt 只有目标内容 hash、版本与 entry mapping 均核对后才返回 applied。原生 dedupeKey 因正文改变时，适配器负责处理旧 entry，不能留下旧值继续召回。

启动 probe 至少验证：人格 section 真正进入请求、原生 mutation tools 被拦截、公共投影隔离、过期投影注入可禁用、工作台修改不能绕开主账本。只检测包已安装或页面返回 200 不通过。

连接补丁还须改写原生记忆引导语与相关工具说明，避免指向已禁止的原生工具。白名单同时作用于模型可见 schema 和实际执行 guard；只隐藏按钮或只在 prompt 中要求“不要调用”不满足约束。原生自进化/梦境开关在本项目生产 profile 中不能被通用设置页重新启用。

### 6.3 直播工具白名单

| 工具 | 输入 | 输出 | 可执行副作用 |
| --- | --- | --- | --- |
| stream_memory_recall | query、受限 limit | 本请求身份可访问的事实与来源摘要 | 更新本地使用统计；不改变事实 revision |
| stream_memory_propose | fact_key、value、来源引用 | proposed / accepted_pending_validation / rejected | 暂存候选；不直接改人格或公共投影 |

工具没有 subject_key、任意文件路径、shell、浏览器、发消息或执行工作流参数。主体从请求绑定上下文获取。后台结构化提取不开放工具，减少错误循环和无法控制的开销。

原生 `humanity_remember` / `humanity_recall` 的 guard 必须覆盖别名和恢复会话；插件发现不兼容时不默默移除 guard 继续直播。原生人格更新/技能工具同样禁用。管理员通过受控管理 API 修改，与观众对话工具分开。

## 7. 主账本与事务边界

[state-schema.sql](examples/state-schema.sql) 是基础表结构，不声称单靠 CHECK 已实现完整状态机。身份、跨表来源资格、时间范围、冲突关系、租约和所有状态转移仍由单一业务服务验证；迁移与应用验证不可省略。

| 表组 | 用途 |
| --- | --- |
| rooms / broadcasts | epoch、maintenance barrier、直播生命周期、水位与角色版本 |
| stream_events / event_payloads | append-only 元数据及可清除正文 |
| requests / utterances / media_manifests | 幂等输入、单活跃槽、文本/音频 hash、持久样本映射、样本确认与终态 |
| playback_leases / playback_receipts | 权威租约和去重回执；旧租约历史可从事件重建 |
| memory_entries / memory_revisions / memory_sources | 当前事实、历史版本、原始证据 |
| summary_versions | 摘要内容、覆盖范围、输入 hash 与有效状态 |
| compaction_jobs / job_chunks / memory_candidates | 持久任务、块状态与候选结论 |
| mirror_outbox | 至少一次投影投递、幂等操作与映射 |
| model_attempts | 调用预算预留、实际 usage 与不确定费用 |
| deletion_fences / schedule_occurrences | 禁止历史复活与周期去重 |

补充的媒体区间、上下文快照和输入 manifest 可采用独立表或规范化 JSON 字段，但必须迁移并加入恢复测试，不能仅保存在内存。跨场 daily/weekly 作业的 source_manifest 保存每个来源场次的 revision；job 行 source_revision 表示该快照代数，不替代逐场校验。

所有数据库连接启用 foreign_keys，主写连接使用 WAL、synchronous=FULL 与有界 busy timeout。数据库在原生本地文件系统，只有 Bridge 业务写入口。内置 CHECK 与唯一索引先挡住基础错误，CAS 保证并发转移；网络等待在事务之外。

### 7.1 必须原子提交的组合

- 接纳输入、去重请求与 input.accepted。
- 激活当前请求、递增 generation 与占用唯一 active slot。
- 播放完成、观察版本与 completion event。
- 下播封口、截止水位、来源版本与 post_broadcast job。
- chunk 摘要、候选决策、记忆版本、来源、outbox 与消费水位。
- 删除屏障、正文失效、缓存版本与投影移除意图。

SQLite COMMIT 不能覆盖外部模型调用或 Humanity 文件写入。后者通过 outbox 与对账达到一致；关键读取以主账本为准。不得在日志里把外部超时写成“事务回滚所以没有发生任何副作用”。

## 8. 幂等、顺序与缓存键

幂等键命名至少包括租户作用域和操作类型。相同键、相同规范化 payload hash 返回原结果；相同键、不同 payload 返回 409。保留去重记录的期限必须长于平台可能重投和作业恢复窗口；首版不自动清理。

SSE 按 event_seq 排序，客户端处理重复事件不重复弹出动作或更新计数。媒体进度序号只在对应租约内有序，不能拿它比较不同租约。迟到事件不能通过更晚的 received_at 获得更高业务权力。

上下文缓存键包含 character、room、viewer/anonymous scope、persona_version、memory_revision、delivery_context_revision、source_revision、deletion_generation 和 policy_version。任一项变化即不复用旧快照。日志只输出 hash 与计数，不默认打印全部观众记忆。

## 9. 管理页要求

演播台至少增加“直播状态”“记忆”“后台整理”三个区域，或提供等价页面。页面文案使用用户可判断的状态，不展示内部工具栈替代解释。

直播状态显示：是否正式开播、当前权威端、当前回复阶段、是否已完整播放、排队条数。停止按钮显示取消中与最终结算，不能点击后立即把音频状态改成“已完成”。

记忆页按公共/指定观众分区查看，展示事实、来源时间、原文可见范围、状态与修订。更正、合并、撤销和删除必须回读服务端 revision，处理 409；不能页面先删掉条目就宣称后台已完成。

整理页显示本场任务、周期计划、静默等待、开播暂停、预算耗尽、失败、已提交块与投影落后。手动“立即整理”也遵守未直播、来源封口与预算检查，不能成为绕过约束的后门。

## 10. 契约变更策略

新增字段优先可选并带 schema 版本；收紧行为、改变身份或记忆范围需要新 policy_version。旧事件保留解释器与迁移测试。不可让未知新事件被旧版本当成普通输入提炼；不支持的版本应明确拒绝并保持只读恢复。

连接器升级至少对比人格注入内容、工具目录、公共投影快照与原生工作台写入路径。依赖升级不能只验证服务能启动；必须重复来源隔离、打断和镜像对账的验收。
