# MC游戏服务

最新执行方向为[Agent＋Mindcraft自主游玩](../../docs/technical/mc-live-v1/Agent与Mindcraft自主游玩.md)：使用当前NAIMEI原生NeoForge角色，Mindcraft实际物品依赖求解器与Agent共同推进，日常不依赖人工接管。近敌撤离优先于普通规划，已知失败在清理及同租约核对后返回新观测；任意未知副作用不重放。下列测试命令只在3080的原生Windows环境执行，本机仅编辑、打包与核对证据。

这是完整MC系统的服务端实现目录，整体交付状态见[实现进度](../../docs/technical/mc-live-v1/实现进度.md)。当前协议客户端测试不能替代真实MC、人物、视觉或平台验收。

069新增[主播目标接续与弹幕同游](../../docs/technical/mc-live-v1/MC主播目标接续与弹幕同游.md)：已批准世界目标的下一步直接经过当前游戏前置核验和原批准修订绑定，逐步等待实际任务与观测证据；固定步骤不占用文字模型，公开回应仍走既有独立链。[原生运行管理页面](../../docs/technical/mc-live-v1/MC原生运行管理页面.md)接入后台启停与持久作业；MC/视觉/官方端生命周期及真实验收仍待完成。

完整交付阅读[实施总纲](../../docs/technical/mc-live-v1/13-完整方案实施总纲.md)。自然语言观众建议见[理解与澄清](../../docs/technical/mc-live-v1/观众自然语言建议与澄清.md)：默认关闭，受理实际Room来源，DSH只读理解可生成待审核建议或澄清；同账号补充、CAS人工补全、删除/失效及临时模型会话清理复用现有审核、控制和正式口播链，不授予AUTO。

038[原生历史维护台](../../docs/technical/mc-live-v1/原生历史维护台.md)由独立Python进程提供；`/mc-control`侧栏经8010的`/mc-maintenance`跳到配置中的维护地址，A停止后直接页面仍可查询。固定操作经持久串行作业调用既有A/B协调，GameManager不在持有业务数据库时自行删库。统一停启及A/B/MC/Humanity联合恢复仍须完成。

## 安装与接入

在`backend/game`目录执行`npm ci --ignore-scripts`安装锁定的纯JavaScript依赖。此步骤不安装或启动Java、模型、Docker、WSL或虚拟机。正式DSH仍遵循既有Node24.22.1运行锁，不能因模块支持更低Node版本而修改整个DSH的版本。

已有DSH宿主通过`loadGame()`按需加载本服务，并把HTTP及游戏WebSocket交给GameManager。8010上的`integration/dsh_bridge.py`转发固定的游戏WS和SSE，8020沿用接收器代理。此处没有另开第二个DSH/Humanity写入者。

默认关闭游戏、规划和视觉；配置模板是[mc-game.example.json](../../configs/mc-game.example.json)。`configs/mc-game.json`是可选的本地初始配置，不进Git；首次载入后配置及CAS revision进入当前设备state root下的`game/game.sqlite3`。配置启用不授予AUTO，不启动游戏或推理；AUTO还需真实桥握手、新鲜快照、显式操作和两段租约确认。

当前`mc`已有受约束的原生3080应用profile和准备入口，但本机完整运行环境及实机业务尚未验收。不能修改来源收据或绕过预检启动人物运行时。[Fabric桥工程](../../game-adapters/minecraft/fabric/README.md)已能原生构建；桥的实机输入/完整技能、完整媒体和正式发布仍需完成。

## 模块

| 模块 | 职责 |
|---|---|
| protocol/config | 从文档权威Schema校验消息和请求，拒绝类型转换与未知字段，检查配置交叉关系 |
| state | 用本地单调时钟计算新鲜度，处理序号缺口、世界和控制代数 |
| store | WAL事务、唯一进程所有者、请求hash、任务转移、可靠消息确认与互动数据；v1→v2→v3→v4一致备份迁移 |
| history | B全部递送行与各任务版本的分块校验、独立持久历史、后台导入/取消、离线摘要分页和原文；不更新实时任务/事件/ACK/口播 |
| worlds | 稳定世界、标签CAS、实际观测基地、活动基地双版本选择、归档、回基地目标/修订解析与不可变检查点 |
| continuity | 实际会话观测历史、有界世界目标、步骤/任务关联、后置条件证明及断线后重新复核 |
| manager/tasks | HTTP、WS、SSE、模式操作、两段租约、任务幂等、取消、权威版本与重启只读核对 |
| recipes | 当前世界配方结果的请求关联、形状/批次/材料选项和截断核验；通过DSH工具读取，保留库存/组件/动态配方未知，见[专项说明](../../docs/technical/mc-live-v1/配方查询与DSH对接.md) |
| suggestions/votes | 所选B站房间、固定格式归并、CAS审核、异步前置核验、事务关联、真实反馈、稳定身份计票/冻结/平票 |
| planner及DSH game-tools | 同一宿主内独立游戏规划、工具白名单、前置查询和用途约束 |
| narration | 持久候选、公平有界调度、来源/世界/事实复核、重启和取消、既有DSH/媒体链及正式完成证明；见[专项说明](../../docs/technical/mc-live-v1/任务结果与公开口播.md) |
| narration-scheduler | 来源合并、等待权重/同毫秒FIFO、主题间隔、严重事件取消策略与后台配置；见[调度专项](../../docs/technical/mc-live-v1/回应调度与严重事件打断.md) |
| frames及解码工作线程 | 当前观察绑定、4MiB真实JPEG解码、最多两帧/30秒缓存和无像素SSE |
| vision | 本地文件/运行锁、llama.cpp HTTP适配、单并发/期限/未知与取消；真实模型未准备 |

SQLite schema为4，以`objects`集合保存任务/操作/建议/投票，辅以独立幂等、事件、转移、选票和所有者表，world_registry/world_bases/world_checkpoints/task_recovery、schema3会话/目标/处置表，以及schema4独立bridge_history/history_partial。已有版本迁移各自先VACUUM INTO一致备份，再事务建表；更高版本在认领写入者前拒绝。世界由实际观测登记；基地只能登记当前新鲜位置，检查点只保存停控后的观测和引用，不能充当MC存档备份或恢复动作。

回基地的BaseTarget由A当前登记生成，检查、DSH/弹幕任务及B后续位置核验使用同一份不可变目标；公开请求只能指定编号及可选BaseRef。任务更新/恢复不可改写目标，A重启未连接时也使用持久实例查找幂等任务，不重发副作用。见[回基地专项](../../docs/technical/mc-live-v1/回基地目标绑定与到达核验.md)。

断线与重启保留B最后确认的任务版本，A端另附recovery元数据；B端task_ledger每次只读一个已知任务，验证原安装、boot、世界、request、epoch和goal后可补齐遗漏终态。自动核对有次数与间隔上限，missing/conflict保持未知且阻止AUTO；不盲目重发动作。旧版A自行产生的中断failed投影会恢复到最后B版本并保留修复审计。现有DSH只读工具和规划上下文包含世界/基地/历史检查点及核对来源，没有另建人格写入者。

A端schema3已接入世界会话观测历史、最多16步骤的世界目标、跨场重新批准，以及独立人工未知结果处置；schema4增加[完整历史导入与后台](../../docs/technical/mc-live-v1/游戏完整历史查询与后台.md)。管理页`/mc-control`经8010同源API/SSE操作，不新增人格、模型或音视频播放器。详见[世界会话与后台复核](../../docs/technical/mc-live-v1/世界会话与后台复核.md)。保留清理/摘要、Humanity删除联动、统一运行备份和真实跨场恢复仍待完成。B桥核心见[B端账本与恢复](../../docs/technical/mc-live-v1/B端账本与恢复.md)；CPU证据不代替真实MC和次日恢复。

建议/投票使用PlatformManager实际保存的B站room_id，与DSH人物会话分离。已过滤的固定格式建议按相同goal归并，后台审核后仍需AUTO及check_action；任务与建议/投票关联同事务提交后再发送给B。管理页已增加审核、投票编辑/关闭/平票和任务反馈；新增game_get_audience只读工具，反馈不自动口播。具体容量、幂等、未知效果与尚缺的SC/角色/删除全链路见[观众互动](../../docs/technical/mc-live-v1/观众建议投票与任务闭环.md)。

## 本地验证

`node --test --test-concurrency=1 tests/game-core.test.mjs tests/game-world-recovery.test.mjs tests/game-host.test.mjs tests/game-world-context.test.mjs tests/game-continuity.test.mjs tests/game-audience.test.mjs`检查真实HTTP/WS/SSE与SQLite上的协议客户端，覆盖控制、互动、迁移、世界/基地/检查点、会话/目标、未知处置与任务核对及模拟模型上下文；原生Java/Node进程重启检查由Fabric构建入口运行。`python -X utf8 -B -m unittest discover -s tests -p test_game_proxy.py -v`检查原生代理及管理页资源。测试目录在本项目outputs下，关闭自己的连接与数据库后才清理。

这些命令不启动Minecraft、文字模型、人物/TTS或公开直播。另行执行`node --test --test-concurrency=1 tests/mc-control-ui.test.mjs tests/mc-audience-ui.test.mjs tests/mc-world-directory-ui.test.mjs`会启动本地无界面Chrome检查实际管理页；只请求测试服务，测试结束关闭全部自建浏览器资源，不加载媒体。MC_UI_EVIDENCE_ROOT可指定本轮证据目录，避免覆盖历史截图。所有V01–V44及C01–C24仍须按实际完整链路逐项验收。

世界目录与实际MC世界分开，主动历史选择按标签页保留；稳定world_id任务过滤不会混入其他世界。基地选择仅改账本，检查点只读详情不提供存档恢复。历史页、离线、版本冲突及迟到成功/失败返回的处理见[世界目录与基地检查点后台](../../docs/technical/mc-live-v1/世界目录与基地检查点后台.md)。

视觉源码和CPU检查见[原始帧与视觉适配](../../docs/technical/mc-live-v1/原始帧与视觉适配.md)。`node --test tests/game-vision.test.mjs`和`python -X utf8 -B -m unittest discover -s tests -p test_game_frame_proxy.py -v`使用原生HTTP、实际JPEG及明确的模型替身；不会启动llama.cpp或下载模型。
# 自主水中恢复与短暂观测停止

Mindcraft 原生规划优先处理 `hazards.in_water`：只选择新鲜、当前位置绑定的原生岸边候选，先检查再提交精确导航。原生端只接受本地八格、完整可达、终点为干燥可站立地面的水路；仍由同一输入所有者执行普通移动和跳跃浮水，最多160个水中tick。不写速度、位置、生命、物品或世界数据；到岸后仍需实际落地、停稳和后续位置核验。采集不允许在水中直接开始，无可达岸边仍是失败，编译或替身通过不代表实机游泳成功。

未发布单人世界中，已确认输入释放的 `LEASE_EXPIRED` / `GAME_CLIENT_TICK_STALLED` 可以重新等待新鲜观测、延迟及新控制握手。重试保留次数预算，不解除此前明确停止或物理停止；普通界面阻塞、旧客户端、已发布世界及未知原因不自动恢复。此前记录的两次普通重生只证明生命恢复子项，完整长期生存和补给仍需实证。

096起独立规划上下文增加`recent_task_results`：只读当前实例、原生桥、世界、世界会话与控制代次内最近五分钟的原生任务终态，最多三项；保留最近失败及非导航完成，避免被连续短导航淹没。任务必须逐字匹配已保存的原生转移记录；未确认投影与核对冲突不注入。结果保留`effect_status`及历史标记，不代表当前库存，不改写任务，不新增执行或人格记忆写入者。实际任务失败后的重新规划能力仍须原世界验证。

097自主补给使用实际持有的多种原生食物计算储备，优先检查新鲜成熟作物和掉落食物；每步仍需原生准入和服务端库存确认。缺粮探索优先较高候选，不把候选当作安全或可达承诺。返回工作台失败不证明工作台消失，历史失效须确认到达并收到附近缺失观测。原世界完整脱困、食物链和生存效果须另行实证。

098支持原生观测中的相邻向上一格挖阶候选，最多四个方向、每步最多三处身体净空挖掘。候选尚未形成可走路线，仍检查地面支撑、危险、流体、可挖方块、当前租约和服务端清除回执，之后才重新检查身体碰撞和移动。探索每片地形最多提交16个目的地，只有实际落地移动到新的地形区域才补充预算，时间流逝、跳跃和回到旧区域不能刷新。规划读取历史事件时只投影有界的事件身份与严重度，完整原文留在账本；无游标读取返回当前世界最近一页，显式游标保持增量顺序。以上接口与原世界最终脱困、食物链的实机结果分别记录。

099仅在仍有未满足的工具或工作站制作里程碑时，优先尝试返回历史工作台；只有缺粮时继续采食物及探索，不因工作台历史坐标打断。历史记录仍保留，实际制作缺工作台时仍可使用。

100把原生食物观察扩至已加载、实际视线可见的16格/上下6格，保留采样原点和时间，最多8个来源；原6格记录仍兼容。先检查采集；远处来源暂不能采集时，可检查并靠近到2格范围后重新观测。同一来源一分钟最多两次靠近，真实位置至少前进2格才补充预算，导航完成不算食物获取。成熟小麦和干草块列为面包原料，干草须通过原生合成及背包回执拆成小麦，再制作面包；两者不计入可食储备。实际生产、生存及节目效果单独实测。


100连续三次已核验的局部寻粮移动仍缺食物时，原生引导交回一次外接模型规划，传递食物缺口、失败检查及已有视觉摘要；模型仍须使用固定技能和原生准入。接收任务或仅预测路线不增加计数，不能把持续短导航当作食物产出。
