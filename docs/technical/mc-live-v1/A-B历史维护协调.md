# A/B历史维护协调

适用`mc`分支，A GameStore schema1–4、B账本schema3。属于同一个完整交付版本的D07/D08实现路径；当前落实原生离线协调及[独立历史维护台](原生历史维护台.md)，统一停启、A自身保留及A/B/MC/Humanity一致恢复仍须完成。真实完整验收0/68，新人物0/100。

## 1. 实现入口与实际范围

| 入口 | 实际职责 |
|---|---|
| [命令入口](../../../scripts/mc_maintenance.py) | dependencies/status/preview/apply/reconcile及serve维护台；读取当前安装profile及源码来源，固定推导A数据库 |
| [A依赖扫描](../../../scripts/mc_maintenance_dependencies.py) | 已停止A的SQLite写入围栏、已知结构检查、完整逻辑快照、恢复依赖集合 |
| [维护协调](../../../scripts/mc_maintenance_core.py) | 实际原生运行文件核对、A/B计划关联、A一致备份、执行与提交结果查证 |
| [B原生命令](../../../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/JournalMaintenanceCli.java) | 既有保留策略、B一致备份与事务维护；新增result只查已提交结果 |
| [B保留策略说明](B端历史保留与离线维护.md) | 7天事件、30天任务、确定性摘要、退休防重及B独立恢复 |

本工具不启动或停止A、MC、DSH、人物、TTS、视觉和官方客户端。操作者须先正常停播、释放输入并停止A及MC；A进程仍活着时，即使租约已过期也拒绝维护。Windows通过进程句柄查询存活状态，不发送终止信号。B仍取得桥使用的同一文件锁，桥占用时拒绝。

A数据库来自当前安装profile中的`state/female-a-3080-k02/game/game.sqlite3`，不接受另传任意A路径。B目录由操作者明确指定，必须已存在；A/B实例必须一致。profile、当前完整源码摘要、安装根、A/B路径和实际原生运行摘要共同绑定计划。此绑定不是设备准备凭据，不改写deployment-origin，也不授予AUTO。

## 2. 原生运行配置

复制[配置示例](../../../configs/mc-maintenance-runtime.example.json)为安装私有的`configs/mc-maintenance.private.json`，填写实际JDK21与维护JAR及依赖的绝对路径、SHA256。示例全零摘要和占位路径不可执行，不能作为已准备或已安装证明。私有文件已排除Git。

命令使用参数数组调用固定`JournalMaintenanceCli`，不通过shell拼接。逐次检查配置和所有显式运行文件；classpath允许已审查JAR，开发检查也可使用有界classes/resources目录，目录摘要为相对路径到文件SHA256映射的规范JSON摘要。目录内重解析点、符号链接、重复路径、摘要变化或非JDK21均拒绝。每次调用前后核对运行文件；最多32个classpath条目、每目录3000个文件。正式可安装运行包及完整JDK/依赖锁仍归D01，不以开发classes目录代替交付包。

SQLite JDBC临时文件只进入本次调用自建目录，结束后释放；Java输出独立留档，40秒调用期限、512KiB日志和512MiB堆上限。超时只终止本次直接创建的Java进程并等待退出，不操作其他应用或GPU任务。

## 3. A依赖规则与扫描约束

在已存在A数据库上取得`BEGIN IMMEDIATE`，阻止并发写入和另一A启动，直到当前命令结束。工具不迁移A、不恢复任务、不删除A行；成功或失败都回滚围栏事务并关闭连接。识别连续schema1–4的精确表集合，未知版本、表、视图、触发器、对象种类、坏JSON或孤立目标关联拒绝，不静默略过。

| A实际记录 | 保护规则 |
|---|---|
| 现场任务 | 非终态或副作用未verified的任务及其关联 |
| 恢复与人工处置 | 未verified恢复记录、全部处置记录及引用；A任务投影缺失也保护明确task_id |
| 世界目标 | 未completed/archived目标、全部关联步骤；已完成的早期步骤在目标仍活动时继续保护 |
| 世界、基地、检查点 | 其明确任务引用及嵌套已知任务标识 |
| 操作、建议、投票 | 未结束操作、未明确拒绝/过期/取消建议、投票关联；已转换建议及关闭投票保守保留，等待A自身保留规则关闭依赖 |
| 口播 | 未明确结束的任务结果口播，包括unknown和合并source_ids；不能提前删除待播依据 |
| 其他已知对象与元数据 | 有界递归扫描明确`task_id/task_ids`及嵌套已知任务ID；格式错误拒绝 |
| 历史投影、旧转移、事件、审计 | 参与完整逻辑快照，但不据只读历史重新固定B原文 |
| 未结束历史导入、部分分块 | 拒绝维护，要求先清洁结束导入 |

扫描全部业务逻辑行和结构形成SHA256，排除仅表示进程所有权的game_owner和SQLite内部表。上限500000行/512MiB逻辑输入、单行4MiB、20000个唯一任务ID、32层引用；达到限制拒绝，不截断保护集合。已知旧schema可只读识别不等于全部旧数据形态已验收。

## 4. 预览、核对与提交

```mermaid
flowchart LR
    Stop[正常停止A与MC] --> Fence[A进程核对与SQLite写围栏]
    Fence --> Dependencies[完整A快照与保护集合]
    Dependencies --> Preview[B实际预览与A封存计划]
    Preview --> Review[核对A计划名和文件摘要]
    Review --> Recheck[重取围栏并核对A/B/运行文件]
    Recheck --> Previous[查询B是否已有该计划提交]
    Previous --> Backup[未提交时先做A一致备份]
    Backup --> Apply[B一致备份及原子维护]
    Apply --> Readback[独立查询B实际提交结果]
```

预览在A围栏内从实际数据生成保护文件，再调用B预览，核对B原计划文件SHA、实例、保护集合、数量和过期时间。最后写入A的`game/maintenance/plans/maintenance-<uuid>.json`，返回其文件名及SHA256；这是操作者核对的A协调计划，与B的`retention-<uuid>.json`不同。B计划期限仍为10分钟。

执行重新校验安装/源码/运行摘要、A计划、保护文件和B原计划的内容关联；修改后自行重算A文件摘要不能绕过A/B保护集合一致性。首先只查B原提交：已有结果则返回当前账本确认及duplicate，不再次备份或发送apply。否则要求A的完整逻辑快照及依赖与预览完全相同、计划未过期且确有候选。

实际删除前先创建不可覆盖的attempt开始记录；在保持A写入围栏时，用独立只读连接执行SQLite一致备份，包含已提交WAL，核验完整性和文件摘要。再重查A，发送B apply，由B执行既有一致备份和单事务维护。最后另发result读取实际已提交运行记录。Java退出码或标准输出本身不能当作跨端完成证明。

A安全备份只覆盖A的game.sqlite3，不包含Humanity、MC存档、平台删除账本；这里没有实现联合恢复，也不自动恢复A或B。B独立恢复仍遵循原说明和退休防重保护。

## 5. 不确定结果及容量

开始记录、结果记录、只读查证记录均采用独立文件及排他创建，不覆盖首次结果。B apply发出后如输出丢失、进程失败或提交查证失败，A记录unknown，保留备份和日志。结果记录自身无法写入或仅留下部分文件时，返回`MC_MAINTENANCE_OUTCOME_UNRECORDED`并继续携带unknown；保留部分文件原字节，不能降为not_dispatched。不会自动再次apply，不将“失败退出”解释为“没有删除”。

`reconcile`只查B当前账本及原计划身份，可在A业务记录已经改变后执行，但仍要求同一安装、源码、运行锁与实例。已找到返回`confirmed_in_current_b_ledger`；没有找到返回`not_found_in_current_b_ledger`。后者可能来自旧B备份恢复，不能证明历史上从未执行。查询记录另存，不改写此前unknown。B忙或当前运行记录不可读时继续不确定。

| 项目 | 固定上限及满额行为 |
|---|---|
| A协调计划 | 16组；每组原计划和保护文件，单文件4MiB，目录字节也受限 |
| 维护尝试/查证 | 开始记录最多64次、查证记录最多64次，满额拒绝 |
| 原生日志 | 128份，每份512KiB；满额拒绝 |
| A安全副本 | 8份SQLite副本，失败时保留已有文件 |
| 备份总字节 | A+B既有备份及本次预估的两个副本合计不超过2GiB；包含B已提交WAL预留 |
| 可用磁盘 | 保留512MiB；同一卷同时预留两个新副本，分卷分别核对 |
| B账本本身 | 沿用原计划/摘要/退休凭据/结果及备份条数上限 |

工具不自动删除计划、日志、备份、退休凭据或原始失败，不自动VACUUM，不声称删行已归还文件系统空间。长期容量、磁盘告警、人工归档流程和整机负载仍待完善；有限预算拒绝不是完整长期运维方案。

## 6. 操作者命令

以下从实际安装根执行，路径和摘要须替换为现场核对值。首次只读导出不需要Java配置；其他命令读取上述私有运行配置，也可明确`--runtime`。

```powershell
python scripts/mc_maintenance.py dependencies
python scripts/mc_maintenance.py status --journal "C:\实际安装\config\ai-talk-streamer-bridge"
python scripts/mc_maintenance.py preview --journal "C:\实际安装\config\ai-talk-streamer-bridge"
python scripts/mc_maintenance.py apply --journal "C:\实际安装\config\ai-talk-streamer-bridge" --plan maintenance-实际UUID.json --sha256 实际A计划64位摘要
python scripts/mc_maintenance.py reconcile --journal "C:\实际安装\config\ai-talk-streamer-bridge" --plan maintenance-实际UUID.json --sha256 实际A计划64位摘要
```

dependencies只输出实例、快照、保护任务标识/原因和扫描数量，不输出任务正文。preview返回拟处理数量且applied=false。apply/reconcile显示当前账本查证状态、是否发送apply及实际结果，不表示游戏或模型已启动。完成维护后重新启动仍须既有来源/设备/模型预检和显式AUTO许可。

## 7. 验证及完整交付待办

实际检查使用原生Windows、JDK21/JDBC/SQLite和Node GameStore；测试数据库独立于设备状态。验证A恢复任务保护与另一旧任务退休、A已提交WAL备份、A/B改变及保护文件篡改拒绝、真实A/B所有者排他、结果丢失后的只读查证、重复执行不增备份、过期和磁盘/合计预算。测试原始失败和最终数量以[实现进度](实现进度.md)及当轮证据为准，重复专项不累计成绩。

这些是合成数据库与原生子进程验证，不是实际Minecraft、DSH/人物推理、官方直播姬或真实观众验收。038独立维护台接入持久串行作业、计划核对执行及不确定结果查证，详见专项和当轮证据。完整A保留、旧格式覆盖、平台/Room和Humanity运维、统一停启及全后台联动、完整维护运行包、联合备份恢复及次日实机继续保留D01/D07/D08/D14/D15；单一完整版本交付标准不变。
