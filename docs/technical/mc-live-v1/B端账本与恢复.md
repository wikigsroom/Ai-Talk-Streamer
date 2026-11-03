# B端SQLite账本与恢复约束

分支：mc。数据库schema：3（保留旧schema2备份及明确迁移）。状态：源码、原生Windows构建与CPU协议检查；真实MC、正式部署与完整恢复验收仍待完成。本文细化[完整交付规划](08-完整交付规划.md)的D02/D07/D14，不构成独立缩减交付。035维护实现及恢复约束见[历史保留与离线维护](B端历史保留与离线维护.md)。

## 1. 文件、写入者和运行位置

客户端默认使用受管实例`config/ai-talk-streamer-bridge/`，其中`mc-control.sqlite3`为唯一任务账本，`owner.lock`在打开数据库前取得独占锁。WAL与SHM属于同一账本，不单独迁移。`native/`仅用于本JVM首次加载SQLite JDBC原生库；测试另指定本工程build目录，避免将已加载DLL放进逐例删除的临时目录。

正式B接收器/同机部署仍需将路径解析进该安装的运行锁，不能将此默认开发路径当作已完成部署。B不读写Humanity、观众身份或其他安装的私有state。原始服务器地址、存档私有路径只参与哈希，不进入对外世界ID。

实现入口为[LocalJournal.java](../../../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/LocalJournal.java)和[BridgeCore.java](../../../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/BridgeCore.java)。游戏线程只产生样本和执行已授权动作；查询、事务、备份由I/O或离线维护调用承担。

## 2. 物理结构和持久性

| 表 | 主要约束 | 用途 |
|---|---|---|
| metadata | key唯一 | 稳定instance_id、当前boot/世界上下文、迁移标记 |
| worlds | key_hash主键、world_id唯一 | 私有键的稳定登记；不存原始地址 |
| tasks | world/request联合主键、task_id唯一、正version | 幂等请求哈希与B权威任务JSON |
| task_transitions | task_id/version联合主键，引用tasks | 每次已落盘任务版本及记录时刻 |
| contexts | boot/world联合主键 | 本地会话打开、关闭及原因 |
| streams | boot/world/stream联合主键，acked≤issued | events和task_transitions的独立游标 |
| reliable | 上下文/stream/delivery_seq联合主键，引用streams | 消息载荷、归档原因、实际ACK时刻 |
| journal_retired_tasks | world/request联合主键、task_id唯一 | 退休请求最小证明，拒绝重放；旧备份恢复保留后续凭据 |
| journal_summaries / journal_retention_runs | 摘要键/运行ID唯一 | 确定性统计和事务内维护结果；有界保留、不调用模型 |

采用WAL、synchronous=FULL、2秒busy等待和单一进程内同步入口。收到任务时，tasks、首条task_transitions、首条reliable在同一事务提交；running和终态同样提交后才继续执行/发送。窗口满、SQL失败、唯一键或版本冲突回滚整个事务，不能只更新tasks而丢掉对应消息。任务只允许从未结束状态递增一个版本，原boot、世界、安装、epoch、goal和创建时间不可改写，终态不能复活为running。

可靠消息先持久化，再由现有有界发送队列发送。A持久投影后ACK；B将对应范围标为已确认而保留历史，低于已有ACK的迟到确认不降低游标。ACK不能确认另一boot/世界/流，也不能越过已发行序号。

SQLite JDBC固定为[3.53.4.0](https://github.com/xerial/sqlite-jdbc/releases/tag/3.53.4.0)，使用其SQLite3.53.4原生引擎。该选择包含SQLite官方说明的[WAL-reset修复](https://sqlite.org/wal.html#the_wal_reset_bug)；不使用早期未修复引擎作为新增B账本默认。WAL/FULL的持久性行为依据[SQLite官方PRAGMA说明](https://sqlite.org/pragma.html#pragma_synchronous)，仍须实机故障/磁盘演练验证本部署环境。

## 3. 旧JSON迁移与版本拒写

仅在SQLite没有已版本化业务表时导入旧`journal.json`：先检查schema1和8MiB上限，再按内容SHA256在`backups/legacy-v1-<sha256>.json`保留原始字节并强制落盘。事务内创建当前schema3、导入实例/世界、任务哈希和版本、独立发送游标与全部未确认消息；任务上下文、重复ID、计数越界等错误使建表与导入整体回滚。原JSON保持原样。

SQLite版本化账本一旦提交，以SQLite为权威；更改或回滚历史JSON不会覆盖新账本。未知SQLite版本、未知JSON版本、具有业务表但没有版本的数据库均拒写。未知SQLite版本在切换WAL或恢复任务前拒绝；失败释放owner.lock，后续诊断不会因本次打开失败永久占锁。

这里是旧JSON到当前B schema3的迁移。已有B schema2先保留原版本一致备份，再事务增加维护结构和高水位；A库版本与B库独立。未来B SQLite升级必须先一致备份并增加明确迁移，不能通过调低user_version或更换分支绕过版本检查。

## 4. 重启、换世界和历史消息

B进程重启时，已受理/运行中的任务追加一个failed版本，reason为INTERRUPTED_RESTART、effect_status为unknown，保留原任务boot和世界，不重放动作。任务版本及对应可靠转移同事务写入。历史已结束任务保持原终态。

桥在I/O线程激活当前boot/世界，将旧上下文未确认消息标记归档，并记bridge_restart或world_changed；原上下文的迟到结果直接归档为late_historical_result。归档行不占当前256项未确认窗口，不会借新信封作为新事实发给A。原载荷、序号及原因可通过本地有界archivePage读取，每页最多100条，按原流序号续查。

归档仅证明B保留了历史消息，不能推断A已收到或观众已听见。033补入[完整历史查询、独立投影与后台](游戏完整历史查询与后台.md)：分别读取全部可靠递送行与每个任务版本，保留原boot/世界/序号、ACK及归档原因，分块摘要校验后存入A独立历史库。离线分页与原文不更新实时事件、任务、ACK或口播。当前任务权威终态仍由task_ledger单独核对，历史导入不能替代该闭环。

重启和换世界后仍为PAUSED，新任务须经新鲜状态、无未解决任务、明确AUTO请求和两段授权；恢复账本不会恢复AUTO。当前任务核对missing/conflict保持未知副作用，A已有独立人工处置，完整联合恢复仍待实机证明。

## 5. 容量与保留策略

| 边界 | 当前行为 |
|---|---|
| 单条持久JSON | 最大128KiB；拒绝过大记录 |
| 当前未确认消息 | 最大256条；拒绝新增并停控 |
| 全部可靠历史 | 最大50000条，含已确认/归档；触顶保留证据并停控 |
| 任务 | 最大20000；不静默移除幂等与恢复凭据 |
| 数据库 | 最大65536页，新建默认4KiB页约256MiB；WAL、备份另计 |
| SQLite备份文件 | 最大8份；满额拒绝新增，不自动删除旧副本 |

035已增加[7天事件/30天任务的离线维护](B端历史保留与离线维护.md)，提供依赖/未知/未确认保护、预览与完整摘要核对、先一致备份后事务处理、确定性摘要及防重凭据。A端自动依赖协调/投影维护、Humanity联动、备份总字节预算、磁盘告警及完整后台仍待完成。未确认历史与未知效果所需记录不能作为普通超期数据删除；没有强行清空以继续运行的自动路径。

## 6. 一致备份和离线恢复核心

LocalJournal.backup调用原生SQLite backup接口，生成`backups/snapshot-<uuid>.sqlite3`，包含已提交WAL；随后强制落盘并写SHA256、字节数、schema和时间收据。不能复制仍活动的主文件充当备份。接口依据[SQLite备份规范](https://sqlite.org/backup.html)及[SQLite JDBC原生接口](https://github.com/xerial/sqlite-jdbc/blob/3.53.4.0/src/main/java/org/sqlite/core/DB.java)。

LocalJournal.restore(directory, backupName)只接受本安装backups目录中的snapshot/pre-restore文件名，按以下顺序执行：

1. 在任何数据库访问前取得独占owner.lock，活动桥存在即拒绝；拒绝目录跳转与越出backups的符号链接。
2. 检查收据SHA256/字节数、源与目标schema及quick_check，核对同一instance_id。
3. 通过原生backup保存恢复前pre-restore快照，再用原生restore接口恢复；失败保留恢复前副本与来源文件。
4. 重开桥时仍执行未结束任务→未知终态核对，并激活新boot；不恢复自动输入，不把恢复后的库存当作实际世界库存。

035已有原生preview/apply/status/restore入口。后台维护按钮、原生进程统一停止/启动、A库/MC世界/媒体与模型锁的联合快照尚未接通。恢复重放当前安装后续的退休请求凭据；其他副本时点之后的任务仍可能不在B库，A必须继续核对并保留missing/conflict。不能改request_id重试来掩盖已发生的未知效果。

A端目前为schema4，在schema3的[会话与人工复核](世界会话与后台复核.md)之外增加独立历史表。停控与版本核对后可独立记录未知结果的人工处置，不改B任务状态或效果，不恢复自动输入。旧任务若重新报告为活动则重新拦截；A会话摘要、B历史导入与当前任务核对分别维护。A/B schema编号互不相同，不能互换文件或借Git回退降级。

真实恢复演练还须证明：世界文件与数据库对应、输入已释放、旧任务没有复活、没有重复口播、次日可继续核对。单库测试无法替代这些证据。

## 7. 验证与交付状态

Java检查覆盖单所有者、真实引擎、重开未知效果、任务幂等、游标范围、256/50000边界、迁移精确备份及回滚、更高版本拒写、上下文归档、WAL一致备份、离线恢复、篡改/跨安装拒绝。Java↔Node检查使用真实SQLite和协议核心，GamePort及效果计数明确标注TEST_FIXTURE_ONLY，未加载MC。

最终数量、产物哈希和逐轮失败记录以[实现进度](实现进度.md)及其证据为准。全部68项真实系统验收、4小时完整负载、100段新素材仍保留在同一个完整发布范围内。
