# B端历史保留与离线维护

适用`mc`分支，B端账本schema3。这里落实完整交付D07的一项原生能力，不构成独立交付版本；真实MC、跨A/B/MC备份及长期负载仍待验收。原始失败和历史工程证据不在清理范围内。

## 1. 入口与运行条件

实现为[LocalJournal](../../../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/LocalJournal.java)、[保留策略](../../../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/JournalRetention.java)及[原生维护入口](../../../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/JournalMaintenanceCli.java)。JDK21直接运行账本工具，不启动Minecraft、人物、TTS、视觉、DSH或官方直播姬，不申请AUTO或发送游戏动作。

先正常停止MC客户端并确认输入已释放，再使用该安装实际登记的账本目录。工具取得与桥相同的`owner.lock`；桥仍占用时拒绝。仅接受已存在且有明确版本的数据库，不创建新的业务账本。维护打开不执行常规启动的`recoverUnfinished`，所以预览不会把running任务改成重启失败。

源码环境可使用现有原生Gradle8.14.3和JDK21；依赖必须已准备，命令使用`--offline`。以下路径是占位说明，必须换成实际账本目录，不得据此生成设备来源凭据：

```powershell
.\game-adapters\minecraft\fabric\gradlew.bat --offline --no-daemon -p game-adapters/minecraft/fabric journalMaintenance --project-prop "journalDir=C:\实际安装\config\ai-talk-streamer-bridge" --project-prop maintenanceAction=status --console plain
```

`journalMaintenance`只调用维护主类。完整运行安装包及无需源码的统一后台接线仍在D01/D08待办中；此处不宣称当前生存工程候选已能安装启动。

## 2. 保留规则

| 对象 | 可处理条件 | 保护条件 |
|---|---|---|
| 事件原文 | 创建/事件发生/ACK均早于7天截止，原上下文已关闭且超过截止 | 未确认（包括已归档未确认）、当前或未确认关闭的上下文、近期记录、旧格式/坏日期、恢复任务依赖 |
| 任务原文及版本/递送 | 终态且副作用明确为`verified`或`none`；创建/更新/每个版本/ACK均早于30天；原上下文已关闭且超过截止 | accepted/running、unknown/缺失副作用、近期版本/ACK、任何未确认递送、显式保护任务、近期引用及无法解析的依赖 |
| 请求防重凭据 | 原任务处理时写入永久退休记录 | 保留world/request/task标识、请求摘要和最小终态证明；达到容量限制时拒绝继续维护 |
| 确定性摘要 | 按UTC日、世界会话、事件类型/任务终态合并计数与起止时间 | 不保留事件正文，不调用模型，不向Humanity写入 |

年龄使用明确的正时间戳，恰好位于截止线的记录继续保留；最近ACK仍需要保留观察期。上下文关闭、递送确认与任务效果分别判断，归档不等同确认。缺失时间、缺失关联或无法识别的旧格式保守保留并计数，不猜测其安全性；无法读取的数据库条目会使维护拒绝，不尝试擦除。

`task_id`引用从有界JSON递归读取；无法安全解析依赖时保护相关任务集合。可另提供本安装的显式保护文件：

```json
{"game_instance_id":"mc-实际实例标识","task_ids":["需要保留的任务ID"]}
```

直接使用本B工具时，该文件只表达操作者补充的保护集合，不能冒充跨库一致性证明。037新增[A/B历史维护协调](A-B历史维护协调.md)，从实际已停止A数据库自动生成依赖，在A写入围栏内绑定A/B计划、A安全备份及B提交结果；优先沿该入口维护。Humanity和MC存档、A自身历史保留及联合恢复仍未纳入此离线协调。036已接通摘要和维护资料的只读历史查询。

## 3. 预览、核对、执行

先设置`--project-prop maintenanceAction=preview`，必要时加入`--project-prop "protectedTasks=C:\实际保护文件.json"`。Windows脚本调用使用分离的`--project-prop`参数，避免盘符冒号被拆分。预览输出计划文件名、文件SHA256、过期时刻、拟处理数量、保护原因和是否提供额外保护。不会输出事件正文，也不删除业务数据。

计划写入本账本的`maintenance/retention-<uuid>.json`，明确记录候选、保护集合、策略时间和完整业务快照摘要。操作者核对后，使用原计划文件和输出摘要执行：

```powershell
.\game-adapters\minecraft\fabric\gradlew.bat --offline --no-daemon -p game-adapters/minecraft/fabric journalMaintenance --project-prop "journalDir=C:\实际安装\config\ai-talk-streamer-bridge" --project-prop maintenanceAction=apply --project-prop maintenancePlan=retention-实际UUID.json --project-prop maintenanceSha256=实际64位摘要 --console plain
```

计划有效期10分钟。执行重新计算全部候选与快照；修改原文、ACK、任务、世界/上下文、保护或计划内容都会拒绝，不能只核对条数。文件摘要与逻辑计划均核验。无候选时不执行、不消耗备份和维护运行名额。

先通过SQLite原生backup保存一致快照和摘要凭据，包含已提交WAL；随后在一个SQL事务中写入摘要/防重凭据、删除候选、推进维护代数及保存实际结果。SQL错误整体回滚；此前生成的安全备份保留。备份失败不开始删除。

同一计划执行成功后可重试，返回原结果，不再创建备份、重复汇总或删除。计划陈旧或失败后重新检查实际账本，不覆盖首次计划及失败记录。工具不自动删除旧计划、备份、摘要或防重凭据来腾空间。

037增加`maintenanceAction=result`，使用与apply相同的计划文件名和SHA256，只查询当前账本是否保存该计划的提交结果，不调用apply或创建新备份。结果含实际实例、run_id及原计划文件摘要。未找到不证明历史上从未执行，尤其不能据旧备份恢复后的缺失记录自动重试。A协调器将丢失输出记录为unknown，再由显式reconcile保存独立查询观察。

## 4. 防重复、历史游标与恢复

任务退休后，`find/accept`对原world/request和task_id拒绝`GAME_TASK_HISTORY_EXPIRED`。账本查询对没有完整原任务的记录仍返回missing，不将最小摘要包装成已核验的Task；A必须保持未知/人工处置语义。换ID、换目标、恢复进程均不能绕过原请求防重。

可靠记录及任务版本使用持久的高水位分配rowid。即使最后一条历史也被处理，新增ID仍递增，避免旧分页游标误认后来记录。离线维护期间桥不能同时查询历史；维护后重新连接按新boot/会话重新核对，旧导入作业不得作为实时状态恢复。

恢复入口使用`-PmaintenanceAction=restore`、`-PmaintenanceBackup=已核对的备份文件名`和`-PmaintenanceSha256=备份凭据中的64位摘要`；不接受任意外部路径。它沿用`LocalJournal.restore`的一致备份校验和恢复前安全副本。若当前安装已有退休凭据，恢复较旧的同安装备份时，从恢复前副本重放这些凭据，并移除备份中对应的旧完整任务/版本/递送，保持其不可重新执行。请求身份冲突或重放失败会尝试恢复到恢复前副本，并保留原始异常及回滚异常。

历史事件与摘要/维护运行记录按照所选备份版本恢复；原始内容仍在各备份中。恢复不会授予AUTO，也不恢复按键或调用游戏端。单B账本恢复不能代替A/B/MC/Humanity的一致恢复。

## 5. schema2兼容与边界

新建账本为schema3。已有schema2先保留`schema-v2-<uuid>.sqlite3`一致备份及实际schema2摘要凭据，再事务增加退休任务、摘要、维护结果和高水位；原任务、流、实例和世界不改写。迁移失败回滚，保留安全副本。旧JSON schema1仍先保留原字节，再导入当前版本；未知数据库/JSON版本或无版本业务表仍拒绝。

恢复校验实际备份版本与凭据，允许已支持的2/3版本；恢复后的退休保护与高水位保持。不能手调user_version把未知结构冒充支持版本。

| 项目 | 上限/行为 |
|---|---|
| 活跃完整任务/可靠历史 | 维持20000/50000条和256条未确认窗口 |
| 退休请求凭据 | 100000条；满额拒绝进一步退休 |
| 摘要组/维护结果 | 20000组/512次；满额拒绝，不静默遗忘 |
| 显式保护 | 最多20000个唯一有界ID；实例必须匹配 |
| 计划文件 | 最多16份，单份32MiB，总计128MiB |
| 一致SQLite备份 | 维持8份；schema2迁移及恢复前副本共同计数 |

删除行只释放SQLite内部页，不声称已收回磁盘字节；没有自动VACUUM、删除备份或扩大数据库上限。满盘、真实Windows文件系统、长期容量与跨进程负载仍需实际验收。

## 6. 验证与未完成范围

专项使用真实SQLite/JDBC、事务、操作系统文件锁、备份/恢复及原生Java子进程，覆盖截止线、保护依赖、计划篡改/陈旧、限额、故障回滚、防重、旧版本及旧备份。最终执行结果以[实现进度](实现进度.md)和[035证据](../../evidence/mc-runtime-round-035.json)为准，不预填通过数量。

037已在原生离线协调中落实A自动保护集合、A一致安全副本、计划关联、提交查证、合计备份字节预算与磁盘预留；实际范围见[A/B说明](A-B历史维护协调.md)。A历史投影/导入作业保留、完整维护执行后台与统一停启、长期容量/告警、真实MC及A/B/MC/Humanity一致恢复继续保留在D07/D08/D14/D15。真实完整验收仍为0/68，新人物仍为0/100。

## 7. 维护后的后台查阅

036将全部保留汇总、任务防重凭据和维护运行结果接入[完整历史查询与后台](游戏完整历史查询与后台.md)。重新启动桥并形成新鲜、已暂停且输入释放的连接后，导播可显式导入全部五源，按类型分页并离线查阅原文。037协调器补入离线执行的A依赖和提交查证；完整维护执行后台及统一停启仍须接线，历史查阅页不代替维护执行入口。汇总按内容版本留档，不同版本不累加；恢复旧备份后，A旧投影仍是已查阅的历史，不冒充当前B状态。
