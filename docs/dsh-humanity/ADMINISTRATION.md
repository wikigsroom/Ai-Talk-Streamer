# 管理操作、分页、事件订阅与范围重建

[总方案](../DSH_HUMANITY.md) · [接口契约](CONTRACTS.md) · [记忆流水线](MEMORY_PIPELINE.md) · [运行手册](RUNBOOK.md)

本文规定已实现的管理行为。所有示例均为本项目 `/api/dsh/*` 接口，不能当作 DSH/Humanity 上游 API。管理页为演播台同源 `/memory`。浏览器使用 HttpOnly 登录 cookie；自动化可以使用本地管理员 bearer token，不能把 token 写入 URL、截图或提交仓库。

## 1. 权限与写入边界

| 操作 | 权限 | 是否允许直播中执行 | 事务及副作用 |
| --- | --- | --- | --- |
| 查询记忆、来源、任务、场次 | operator | 是 | 只读主账本；不访问其他服务的原始会话文件 |
| 更正、归档、等值合并、补偿撤销 | operator | 是 | 同步主账本事务；新请求读新 revision，已冻结请求快照不改写 |
| 删除 | operator | 是 | 取消活动请求、清除相关正文、提高删除屏障、重启私有宿主、重新投影 |
| 指定范围重建 | operator | 否 | 只创建持久作业；依然等待下播静默、来源封口和预算 |
| 一致备份与关闭 Bridge | operator | 否 | 活动场次未结束时拒绝；备份需宿主无在途请求 |
| 持久事件订阅 | operator / viewer | 是 | 只读事件元数据；viewer 只接收公开生命周期与自己请求的元数据 |

管理页显示出来不等于拥有写权限。最终权限在服务端校验，playback/OBS 凭据不能编辑记忆、发布人格或创建重建任务。不同登录会话的请求可见性按 principal_id 判断，稳定观众的记忆归属则按服务端 viewer_id 判断。

删除和备份运行期间 `MemoryAdministration.locked` 阻止其他事实写入、重建及前台接纳。主账本更新为同步事务，中间没有网络 await。Humanity 更新走 outbox，不能把“主账本已提交”解释为“另一个存储也同时原子提交”。

## 2. 分页查询

```http
GET /api/dsh/memory?limit=50&subject_key=public&state=active&fact_key=preference.drink
```

`subject_key`、`state` 和 `fact_key` 均为精确匹配，可以省略。默认每页 50，允许 1–200；超出返回 `400 MEMORY_PAGE_LIMIT`，不静默截断。状态为 active、proposed、conflicted、superseded、retracted、archived、deleted。查询先限定本实例 character_id/room_id，再应用筛选。

返回示意：

```json
{
  "entries": [],
  "revision": 12,
  "next_cursor": null,
  "limit": 50,
  "filters": {"subject_key":"public","state":"active","fact_key":"preference.drink"}
}
```

实际非末页的 `next_cursor` 是不透明 continuation。下一页原样携带 cursor，并保留原筛选和 limit。排序为 `updated_at DESC, memory_id DESC`，使用 keyset 条件处理相同时间戳，避免 OFFSET 在新事实插入时移动窗口。

cursor 绑定 character/room、筛选、页长和主账本 memory_revision。期间任何事实提交提高 revision，旧 continuation 返回 `409 MEMORY_PAGE_CHANGED`。客户端必须提示刷新并从第一页重新开始，不能把新旧快照拼成一份“完整列表”。这是有界 continuation，不是长期保留的历史数据库快照。

管理页提供精确筛选、前后翻页和每页 50 条；筛选/刷新清空选择。合并只接受当前选中的 2–20 条；需要处理更多事实时分批操作。分页不自动滚动加载全库。来源接口目前返回单条事实的完整修订链；高修订量来源链和任务列表仍是独立的后续分页扩展范围。

## 3. 归档

```json
{
  "operation_id":"archive-demo-unique-001",
  "memory_id":"mem-example",
  "expected_revision":3,
  "reason":"保留历史来源，停止默认召回"
}
```

提交到 `POST /api/dsh/memory/archive`。必须读取当前 revision；reason 为 1–300 字符，operation_id 为调用方保存的唯一键。原事实不能已删除、被取代或撤回。事务中生成新 revision、state=archived、审计事件和公共投影 ARCHIVE 意图；原文来源不因归档删除。

归档后的事实不参与主账本 active 召回，Humanity 公共镜像也不作为 active 注入。镜像落后时关闭原生镜像注入，使用主账本受控回退，不能继续注入旧 active 内容。

相同操作键及输入重试返回第一次结果；同键不同输入返回 `409 OPERATION_ID_CONFLICT`。新的操作键不是自动重试的替代品。界面成功后显示操作 ID，操作者可复制到补偿撤销表单。

压缩/范围重建遇到已归档事实的同一批证据，返回 `existing_evidence_no_change:archived`，不创建新 revision、不把旧来源重导为 active。未来新增来源仍经过候选规则和冲突审核；归档不等于永久删除该观众所有未来陈述。

## 4. 等值合并

```json
{
  "operation_id":"merge-demo-unique-001",
  "target_memory_id":"mem-keep",
  "inputs":[
    {"memory_id":"mem-keep","expected_revision":3},
    {"memory_id":"mem-other","expected_revision":1}
  ],
  "reason":"人工对照原始来源，确认是同一个事实"
}
```

提交到 `POST /api/dsh/memory/merge`。必须满足：

1. 输入 2–20 条，ID 不重复，目标包含在输入中；所有输入 revision 与当前值一致。
2. character、room、subject_key、visibility、fact_key 完全一致，不能跨观众或跨公共/私有分区合并。
3. JSON 规范值等价，polarity、valid_from、valid_until 相同。字符串只做 NFKC 和两端空白规范化，JSON 对象按规范键序比较；没有同义词或模型语义猜测。
4. 所有来源仍可校验，未被删除、未越过删除 fence；固定身份键不能经事实合并修改。
5. 同键在输入集合之外不能存在另一个 active 事实。

不同值的“茶”和“咖啡”会返回 `422 MERGE_NOT_EQUIVALENT`，应该查看来源并更正，不使用合并决定谁对。跨分区返回 `422 MERGE_SCOPE_MISMATCH`。来源失效返回 `422 MERGE_SOURCE_INVALID`，不部分提交。

事务先把非目标输入写为 superseded，再写目标 active 新修订，避免短暂违反“同分区同键最多一个 active”的唯一约束。目标来源按 event_seq 去重取并集。每个输入保存 prior_revision / result_revision，操作回执和 `memory.merged` 事件同事务写入。只要主账本事务失败，所有输入一起回滚；公共投影可随后独立重试。

合并不会直接覆盖或删除历史行。界面默认以选中的第一条作为目标，可在弹窗中切换。成功必须回读服务端列表，而不是先在前端删掉其他行。

## 5. 补偿撤销

```json
{
  "operation_id":"merge-demo-unique-001",
  "undo_operation_id":"undo-demo-unique-001"
}
```

提交到 `POST /api/dsh/memory/undo`。operation_id 指原始更正、归档或合并；undo_operation_id 指本次撤销的新幂等键。兼容旧调用省略后者时，服务端使用稳定 `undo:<原始键>`，不会每次重试创造一个撤销。

普通撤销读取原操作前一修订的快照和来源，检查当前 revision 恰好等于原操作结果、来源仍有效、没有另一个新 active 事实，再创建补偿 revision。合并撤销逐条核验整个输入组，恢复目标和各输入的先前状态与来源，每条仍产生新 revision。

任一输入已有后续编辑，整组返回 `409 UNDO_HAS_LATER_REVISION`；不能只恢复部分输入。删除后的来源、空白的脱敏快照或 deletion fence 使撤销失败。输入集合之外的新 active 事实触发 `UNDO_WOULD_OVERWRITE_NEW_FACT`。这些失败不能用“回到更老 revision”绕过。

成功撤销同样写审计事件与公共投影意图，保存 operation_results 回执。重复请求返回已保存回执。撤销不删旧操作、不回退数据库全局 memory_revision，也不撤销调用成本和已经发生的播放事实。

## 6. 指定范围重建

先 `GET /api/dsh/broadcasts` 取得最近 50 个场次的状态、source_revision、source_start_seq、ended_event_seq 和静默截止时间。管理页只列其中 ENDED 场次。API 可以指定另一个已知历史场次 ID，但不会默认列出全部历史。

```json
{
  "operation_id":"rebuild-demo-unique-001",
  "broadcast_id":"bc-example",
  "expected_source_revision":1,
  "partition_key":"public",
  "source_start_seq":102,
  "source_end_seq":350,
  "reason":"修复该分区这一段的候选处理"
}
```

提交到 `POST /api/dsh/jobs/rebuild`，接纳返回 202 与 job_id。**202 仅表示持久作业已入账**，不表示模型已处理或长期事实已生成。

服务端约束：

- 当前没有 STARTING/LIVE/PAUSED/RECOVERING/DRAINING 场次，管理锁未占用；暂停直播仍然不能重建。
- 目标场次已 ENDED，source_revision 与调用方读取的版本相同。
- 起止为整数，范围非空，不能早于该场首个事件或晚于封口 ended_event_seq。
- partition_key 必须为 public，或确实在目标场次输入载荷中出现的分区；不能凭随意填写一个观众 ID 扩大来源范围。
- reason 必填；操作键重试幂等。同键改范围/分区/版本/原因冲突。

新作业冻结 character/room、场次、分区、策略版本、source_revision、起止水位、当前 maintenance_barrier 和 deletion_generation。起始 consumed_through_seq=start-1。job_id 从包含操作键的 job_key 派生，不与自动下播整理混淆。

`not_before=max(当前时间, 该场 consolidation_not_before)`，因此“手动重建”不能跳过下播静默 120 秒。调度器仍串行抢占租约，以 200 新事件/24 KB 分块，最多 2 条只读重叠；源选择仍只接受合格 input.accepted 和 playback.completed。范围中其他状态事件不是模型事实来源。

重建复用既有候选验证、预算预占、原子事实/摘要/来源/outbox/游标提交及投影恢复。没有特殊“管理员模式”跳过来源核验：

- 渠道不兼容或未就绪：等待/延期，不生成伪造空摘要、不前进游标。
- 模型超时、429、格式错误：按既有重试和预算规则保留失败原因；usage 不明仍入账。
- 再次开播：提高 barrier、撤销作业租约并终止等待，迟到结果不能提交。
- 来源删除：删除屏障或 manifest 不匹配使结果失效；不能重建已擦除正文。
- 同一事实和同一来源：不增加行/修订；新证据并集合并，相反值保留为冲突，proposed 不因重复扫描自行升为 active。
- 公共镜像失败：保留已提交 checkpoint，只重试投影，不重新向模型发送已消费块。

默认操作不是重新发布人格、重置预算或完整回扫所有直播。若要采用新的策略语义，应先发布新策略版本并执行版本迁移评估，不能仅修改 job 参数冒充政策升级。

## 7. 持久事件订阅

```http
GET /api/dsh/events?after=350
Accept: text/event-stream
```

响应示意：

```text
retry: 2000

id: 351
event: state
data: {"event_seq":351,"event_type":"broadcast.ended","broadcast_id":"bc-example","request_id":null,"utterance_id":null,"runtime_epoch":4,"generation":8,"received_at":"2026-10-25T00:00:00.000Z"}

id: 351
event: checkpoint
data: {}

: heartbeat

```

规范行为：

1. SQLite 已提交事件是唯一真源。内存 EventEmitter 只负责唤醒；从数据库 `event_seq > cursor ORDER BY event_seq` 每次读取最多 128 行。
2. 默认 after=0；只接受非负安全整数，超过当前全局水位返回 `400 EVENT_CURSOR_AHEAD`。浏览器重连使用 Last-Event-ID，优先于 URL 中的初始 after。
3. state 仅返回事件序号、类型、场次/请求/话语 ID、epoch、generation、received_at。**不返回 event_payloads、原文、actor_id、API key、记忆正文或删除来源。** 元数据通知后按权限 GET 对应资源。
4. operator 可见本 character/room 的元数据。viewer 只可见 broadcast.*、runtime.started 和 principal_id 属于自己的请求事件。不可见行仍推进扫描水位，checkpoint 通知续读位置；序号不连续属于正常过滤结果。
5. 客户端按 event_seq 去重；checkpoint 只更新游标，不触发业务动作。连接重建不自动重复更正、合并、播放或模型调用。
6. 每 15 秒发送 SSE 注释心跳，不持久化为事实。每次推送和心跳复核凭据，撤销身份后关闭连接；数据库故障也关闭。
7. 全实例最多 24 个订阅，同一 principal 最多 4 个，超额返回 429。写入遇到背压立即停止读取，不把全部历史堆进内存，drain 后从已扫描游标继续。
8. 浏览器退出、客户端取消、Bridge shutdown 都释放计时器和连接。Bridge 关闭订阅后才能等待 HTTP server.close，不能因长连接无限卡住关闭。

8010 Python 同源代理对该精确 GET 路径使用 StreamResponse，逐块转发，不 `await result.read()` 等待连接结束。总时限关闭，连接超时 3 秒、读间隔超时 45 秒，正常 15 秒心跳能维持连接。代理转发 Last-Event-ID；其他 JSON 请求继续保留原 100 秒限制。

管理页使用事件触发有界防抖刷新，状态另有 15 秒轮询兜底，任务列表保留 10 秒刷新。记忆分页不随事件静默重排；需要操作者刷新，以保护正在选择和编辑的 revision。

## 8. 直播控制的旧页面防护

`broadcast/ready`、`broadcast/pause`、`broadcast/end` 的 HTTP 请求必须同时提供 broadcast_id 和 expected_revision；遗漏返回 400。服务端核验当前活动场次及 revision，冲突返回 `409 BROADCAST_REVISION_CONFLICT`。ready 在依赖检查等待后进入事务时再次核验。

暂停必须先核验目标，再取消活动请求；不能拿一张旧页面的暂停指令去取消新场次的回复。下播也不能对旧场次 ID 省略核验并操作“当前那一场”。内核单元测试可直接调用状态方法用于构造场景；正式 HTTP 管理入口不接受省略版本的旧调用。

网页与测试程序必须一起升级：已打开的旧版页面应刷新后再操作。恢复/重新开播时 runtime_epoch 的规则继续由[直播状态协议](LIVE_STATE.md)规定，CAS 不能替代 epoch、generation 或播放租约校验。

## 9. 故障排查与验收证据

| 现象 / 错误 | 处理 |
| --- | --- |
| MEMORY_PAGE_CHANGED | 刷新到第一页，重新选择并读取 revision |
| MEMORY_REVISION_CONFLICT | 查看来源和最新内容，重新作出决定；不自动把 expected_revision 改成最新重试 |
| MERGE_NOT_EQUIVALENT | 保留独立事实，使用更正/冲突审核，而非猜测等价 |
| UNDO_HAS_LATER_REVISION | 查看后续修订，显式创建新的更正；不强制回退 |
| REBUILD_REQUIRES_OFFAIR | 正式下播并排空；PAUSED 仍属于有活动场次 |
| REBUILD_SOURCE_CHANGED | 重新核查场次封口和版本，避免沿用旧 manifest |
| EVENT_SUBSCRIPTION_LIMIT | 关闭不用的管理标签页，客户端不可绕过上限反复新建身份 |
| 代理只有连接、没有首个事件 | 检查使用 StreamResponse、转发 Last-Event-ID，以及中间网络是否缓冲 SSE |

测试分三层：

- `tests/dsh-maintenance.test.mjs` 使用真实 SQLite 验证补偿修订、合并整组撤销、跨分区拒绝、范围冻结、相同时间戳分页、旧场次保护及真实 HTTP SSE 断线续读/撤销身份。
- `tests/dsh_routes_probe.py` 在原生 aiohttp 安装环境中验证事件流在上游连接结束前到达、Last-Event-ID 转发和旧媒体绕过阻断。
- `tests/dsh-management-smoke.mjs` 启动隔离的真实固定版 DSH/Humanity、HTTP 和 Chrome，验证管理页分页/归档/撤销/合并/重建。事实由明确标记的测试来源生成，不修改正式记忆，不调用云端 LLM/TTS；截图不得当作真实 AI 回忆证据。

精确结果和限制见[实施记录](IMPLEMENTATION.md)、[验收表](ACCEPTANCE.md)及[机器证据](../evidence/dsh-humanity-runtime.json)。管理功能通过不代表真实云端对话、20 轮记忆、五场景录像或 OBS 应用混音器已通过。
