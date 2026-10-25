# 原生部署、直播和离线记忆操作手册

[总方案](../DSH_HUMANITY.md) · [实际实现](IMPLEMENTATION.md) · [状态规则](LIVE_STATE.md) · [记忆算法](MEMORY_PIPELINE.md) · [验收门槛](OPERATIONS_TESTING.md)

相对路径均以项目根目录为起点。3080 部署根目录 `C:\dev\虚拟数字人直播`；开发仓库 `E:\dev\sandbox\虚拟数字人直播\Ai-Talk-Streamer`。依赖、缓存、证据、备份在项目内，使用原生 Windows；不调用 Docker、WSL、虚拟机。

## 1. 文件和端口

| 位置 / 端口 | 用途 | 范围 |
| --- | --- | --- |
| 8010 | 演播台、人物、同源 `/api/dsh/*`、`/memory` | 沿用当前可信网络 |
| 127.0.0.1:3092 | Bridge 业务及内部媒体 API | 仅回环 |
| 127.0.0.1:3091 | 跳转到同源管理页 | 仅回环 |
| 9880 | 当前 MOSS 服务 | 沿用本地媒体配置 |
| tools/node、tools/dsh | 固定 Node 和 npm 运行时 | 本地文件 |
| state/female-a/stream.sqlite3 | 账本、作业、来源、修订、预算 | 私有，不入 Git |
| state/female-a/dsh-home | 专用 DSH/Humanity home | 私有，不与别的角色共享 |
| state/deletion-ledger.jsonl 及 head | 独立删除屏障和 hash 链 | 必须与旧快照分开保留 |
| configs/channel.env | 原网页渠道真源 | 私有 |
| configs/dsh-operator.token | 首次管理员登录凭据 | 仅本地读取 |
| configs/dsh-media.token | Python→Node 内部认证 | 不交给普通浏览器 |
| backups、state/restores | 一致备份、隔离恢复 | 私有，不入 Git |

后台 token 首次启动生成，数据库只保存 hash。Windows 文件 ACL 应沿用项目私有权限；代码中的 mode 参数不能代替 Windows ACL 管理。

## 2. 安装与启动

前提是原 LiveTalking、MOSS 和人物素材已准备。DSH 安装不会重新安装 ComfyUI，也不切换 GPU 模型或音色。

```powershell
Set-Location -LiteralPath 'C:\dev\虚拟数字人直播'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deployment/install_dsh.ps1 -ProjectRoot 'C:\dev\虚拟数字人直播'
python deployment/deploy_dsh.py
python scripts/dsh_control.py start
python scripts/dsh_control.py status
```

用机器已有原生解释器替代示例 python。3080 媒体操作使用 runtime/livetalking/Scripts/python.exe；MOSS 使用 configs/moss-live.json 中的解释器。不要混装到同一系统环境。

安装器锁 Node 24.22.1、核对官方归档 hash，npm ci 使用仓库 lockfile。补丁检查 Humanity 0.1.17 和源码锚点，保留原文件并输出安装 receipt；失败不能跳过版本校验。deploy_dsh.py 保存被替换媒体代码后安装适配器、网页及启用开关，不会自动重启 GPU。

迁移文件视为不可变源码。新库使用 LF 规范化文本 hash；旧库仅兼容同一内容的 LF/CRLF 历史 hash，不自动改写旧记录。出现 STORE_MIGRATION_HASH 时核对版本和源文件，不能把任意新 hash 写入数据库来绕过校验。

### GPU 加载顺序

3080 10 GB 的已验证顺序是先人物初始化和真实特征预热、释放启动缓存，再加载 MOSS。MOSS 常驻时单独重启人物可能产生极慢推理；端口可连接不足以证明性能正常。

先在管理页下播，确认 status.broadcast=null，再执行：

```powershell
& '.\runtime\livetalking\Scripts\python.exe' deployment/restart_avatar_for_dsh.py --ordered-media
```

脚本只匹配本项目登记的 MOSS 与已验证的 8010 人物树；拒绝正在直播、陌生端口或外部子程序。未带 ordered-media 而 MOSS 常驻时拒绝单独重启。加载可持续数分钟，不重复启动副本。

仅改 Node 后端时，下播后 dsh_control.py stop，确认退出再 start，无需重载 GPU。

## 3. 网页首次启用

1. 打开演播台 `/`，进入 `/memory`。
2. 本地读取 operator token，粘贴管理页密码框登录；不要放入 URL、Git 或截图。
3. 核对来源 studio_channel_env，model/protocol 与原网页设置一致。
4. AI 模式先完成真实渠道兼容探针；仅提示词中出现人格不算模型可用。
5. 回演播台连接预览。预览不自动产生正式播出记录。
6. 选择 Echo 或 AI，点“网页测试开播”由当前网页负责确认；“OBS 开播”等待本机 OBS 源获权。

OBS 源使用 `http://127.0.0.1:8010/obs.html`，由本机回环入口取得仅能确认播放的凭据，不获得管理权限。同场只有一个权威端；普通预览可看，但不确认完成。显式“接管播放确认”会清旧在途句并换 epoch，不拼不同端的样本前缀。

接管后的旧句先保守结算 UNKNOWN；原权威在十秒取消窗口内提供有效的冻结前缀时，可以结算为 INTERRUPTED，仍不能变成 COMPLETED。该状态细化不把两个端的进度相加。

## 4. 在线行为规则

| 操作 | 结果 |
| --- | --- |
| 普通发送 | 幂等键 + FIFO，不抢占上一句 |
| 同键同内容重试 | 原 request，不重复生成/合成 |
| 同键异内容 | 409 IDEMPOTENCY_CONFLICT |
| 一活跃 + 四待处理 | 新请求 429 QUEUE_FULL，不静默丢旧项 |
| 排队超过 180 秒 | EXPIRED，不再调用模型 |
| 暂停 | 当前句取消屏障失效，保留场次，停止激活 |
| 恢复 | 同场新 epoch/generation，重新取得租约 |
| 停止 | 清服务端和浏览器缓冲；保留确认样本，不推断精确已说台词 |
| 预览断开 | 不自动下播；权威端断开则租约到期，当前句 UNKNOWN |
| 进程重启 | 活动场 RECOVERING，未完成句 UNKNOWN，不自动重播 |

最终文本默认最多 160 字，完整 MOSS WAV 生成后登记样本/hash。映射先持久化，再发送 PCM；浏览器依据 AudioContext 样本时钟和自然结束确认。stop() 引发的 ended 不算自然完成。页面“语音已发送”不能替代 COMPLETED；进入助手已播历史的唯一正式事件为 playback.completed。

## 5. 一次正常下播的完整时间线

示例：22:00:00 点下播，本句还剩 8 秒。

1. 22:00:00：LIVE→DRAINING，停止新请求、取消排队项，当前句排空。
2. 22:00:08：连续全部样本自然播完，产生 playback.completed；若超过 30 秒仍未完成则取消，按 INTERRUPTED/UNKNOWN 结算。
3. 同一结束事务：broadcast.ended、ended_event_seq、source_revision、consolidation_not_before 和各分区唯一作业一起提交。
4. 到 22:02:08：等待 120 秒静默窗口。迟到取消确认可提高 source_revision，使旧作业失效并安排新版本；不把后续普通事件偷偷加进旧截止水位。
5. 轮询器取得唯一租约，固定本场合格来源 manifest，取 200 新事件/24 KB 以内及两条只读重叠。
6. 独立 DSH 整理 Agent 返回严格结果；校验 schema、来源 ID、原文连续引用、分区、证据种类和完整原句语义。
7. 一个 SQLite 事务提交候选、事实 revision、来源、块摘要、outbox、job_chunk 和 consumed_through_seq；任一写失败全部回滚。
8. 事务后同步公共投影；失败停 PROJECTING，保留事实和水位，不再次抽取同块。
9. 块全部消费且投影验证一致，写本场导航摘要和 COMPLETED。观众事实不复制到 Humanity 全局库。

若 22:02:10 再开播，先提高 maintenance_barrier、撤销旧 lease_generation、取消网络等待。即使旧模型 22:02:20 才回，也不能提交；下次安全空闲接管时重验来源，再从已提交游标继续。

## 6. 日/周任务、预算和失败

网页新增的分页、归档、等值合并、补偿撤销、事件订阅及“指定范围重新整理”见[管理操作手册](ADMINISTRATION.md)。API 控制暂停、恢复、下播时必须提供当前 broadcast_id 与 expected_revision；旧版脚本省略版本会被拒绝。归档保留来源，删除则清除相关正文，二者不能混用。

Asia/Taipei 每日 03:30 补齐未完整消费场次；周一 04:10 按变化的 memory_revision 检查来源/过期状态、生成维护导航。周维护不回扫全量原始聊天，不自进化人格。Bridge 每 5 秒轮询，重启补查最近 12 小时 occurrence，schedule/date/policy 唯一键去重。

一次接管最多 8 次模型调用，后台本地日最多 20 次，发送前占额。usage 缺失仍计次数，标 USAGE_UNKNOWN。午夜仅新增额度，不改昨日账；取消/重试/手动恢复不清费用账本。前台对话单独计量，不使用后台限额。

| 原因 | 持久状态 | 后续 |
| --- | --- | --- |
| 正在直播 | PAUSED / DEFERRED | 等下播，重新租约校验 |
| 静默窗口 | DEFERRED / quiet_window | 到 not_before |
| 渠道兼容未通过 | DEFERRED / channel_unavailable | 修复渠道后探针；不消耗实际调用额度 |
| 调用预算耗尽 | DEFERRED / budget | 保留 checkpoint，下一可用额度续跑 |
| 超时/非法结果/429 | RETRY_WAIT | 5 秒起指数退避，上限 300 秒，最多 5 次失败 |
| 来源被删除/修订 | CANCELLED | 旧作业不得强行恢复，以新来源版本新建 |
| 投影未完成 | PROJECTING / projection_lag | 只补镜像，不重做模型提取 |

## 7. 人格、事实和观众管理

- 人格：发布允许的 mutableLayer，带 expected_version；固定身份不能由弹幕/整理改写。在途请求继续旧人格快照。
- 更正：先查来源和完整播出资格，带 expected_revision、operation_id 修订；原版本保留审计。
- 冲突：无明确管理更正时不按时间较新自动覆盖，双方停止召回。
- 撤销：创建补偿 revision；后续已有修改则拒绝旧撤销。
- 稳定观众：同一邀请多次登录保留 viewer_id；同名邀请仍是不同分区。
- 匿名：每场独立，下场不按昵称自动合并。

首版自动批准仅覆盖两种受控偏好事实族。其他有据候选 proposed 必须审核；不能把候选列表当成已经生效的长期记忆。

## 8. 删除传播

删除需写主体/来源 fence、提高 deletion_generation/source_revision，清原文与引用、事实及历史 revision 正文、候选和旧 outbox，令有关摘要/context 失效。旧提取与 job 租约失效，迟到结果不能复活内容。

删除控制写入独立 ledger 并 fsync，维护 hash 链/head；未同步保留 pending 状态。关闭/清除可能含原文的 DSH 持久会话缓存，重挂宿主并对账公共镜像后再允许注入。不是只在列表隐藏一行。

旧备份仍含历史正文，需私有管理；恢复时先应用最新 ledger。缺 ledger/head 或链不合法，拒绝恢复。外部分发的视频/导出不可能靠数据库操作追溯清除，需单独管理发布副本。

## 9. 备份与隔离恢复

下播后从管理页创建备份。VACUUM INTO 捕获 WAL 一致状态；flush 插件后记录 manifest/hash，不直接复制活动主文件。

```powershell
node backend/memory/restore.mjs prepare 'C:\dev\虚拟数字人直播' 'backups/<backup-id>'
# 核查 prepare 返回的 restore-receipt.json，再在下播后停止 Bridge。
python scripts/dsh_control.py stop
node backend/memory/restore.mjs activate 'C:\dev\虚拟数字人直播' 'state/restores/<restore-id>/restore-receipt.json'
python scripts/dsh_control.py start
```

prepare 写全新目录，验证 hash/schema/删除链，重放最新删除、执行 integrity_check/foreign_key_check、清旧 owner/租约、生成全新 Humanity home 并安排投影重建。旧生产目录保留。

activate 要求 Bridge 离线，删除 ledger 及生产水位自 prepare 后未变；若备份会丢失新的人类输入/完整播出互动则拒绝。成功只切项目内策略指针，保留旧指针和旧库。重新启动后先检查 RECOVERING、epoch 和投影，再显式恢复。

## 10. 排查与复跑验证

| 症状 | 核查及处置 |
| --- | --- |
| 8010 可看、AI 不可用 | channel revision、真实 HTTP/兼容探针；修复原渠道，不静默换模型 |
| 人格不 ready | dsh.stderr.log、固定版本、connector probe；保全主库，不建空库绕过 |
| WAV 完整而未完成 | manifest 最终样本、租约、played_samples；缺证据不记已播 |
| 人物约 1 FPS | gpu-worker 日志、加载顺序、显存；下播 ordered-media 重启本项目 |
| job 不动 | state/reason/not_before、直播、静默、预算、渠道；不删除游标清队列 |
| Humanity 旧值 | outbox lag、operation_id、mirror_revision；禁旧镜像注入，主库回退读取并修复 |
| 数据库满/不可写 | 锁止写入与模型提交；修复存储后重启，不另建空库 |

```powershell
node --test tests/dsh-state.test.mjs tests/dsh-playback.test.mjs tests/dsh-maintenance.test.mjs tests/dsh-auth.test.mjs
python -m unittest discover -s tests -p test_dsh_viewer_buffer.py
node tests/dsh-host-probe.mjs <project-root> <project-root>/tools/dsh
python tests/dsh_routes_probe.py
node tests/dsh-media-smoke.cjs <project-root>
node tests/dsh-authority-smoke.cjs <project-root>
```

宿主探针使用真实 DSH/Humanity、独立测试 home 和受控 HTTP 端点，不算用户真实渠道通过。媒体程序需要项目内 Playwright 与原生 Chrome，明确测 Echo，结束关闭自己创建的全部页面/context。最后按 A01–A40/S1–S5 执行真实渠道和视频验收，不能以截图或旧版本视频替代。
