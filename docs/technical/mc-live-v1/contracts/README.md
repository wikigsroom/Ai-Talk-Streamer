# 契约、示例与校验

[技术文档入口](../README.md) · [接口章节](../04-接口与数据.md) · [控制协议](../02-游戏桥与控制协议.md)

- [game.schema.json](game.schema.json)：JSON Schema 2020-12定义，选择`$defs`中的具体类型使用。
- [openapi.json](openapi.json)：OpenAPI 3.1 / 业务版本1.12.0。51项游戏HTTP操作（含完整历史与自然语言建议接口）标为implemented_protocol_tests_only；已有Room仅描述留言换边子集，共52项。实际游戏、视觉推理及完整系统均未验收。
- [examples.json](examples.json)：全部为虚构契约示例，不是运行证据或当前能力发布清单。
- [verification.json](verification.json)：本轮文档/契约检查记录，与V01–V44及C01–C24共68项系统验收分开。
- [build_contracts.py](build_contracts.py)：较早版本的契约生成模板，未包含后续口播/平台/历史等扩展，不能用于重建当前运行契约。它会拒绝覆盖已有的新增定义、路径或示例，只在mc分支执行且不启动服务。

当前运行与构建以这三个已维护的JSON文件为准。编辑定义、示例或接口后同时更新对应章节，并重新运行结构与业务关系检查；历史生成模板须先与完整现行契约对齐，不能覆盖丢失后续功能。verification.json是实际校验结果，不由生成器冒充生成通过。

在项目根目录执行`python -X utf8 -B scripts/mc_check_contracts.py`运行文档、引用、示例/反例、范围与布局一致性检查并更新verification.json；依赖Python的jsonschema。该命令不启动应用服务、游戏或推理。

范围规划保持1.2，当前OpenAPI业务版本1.12.0，游戏WS协议仍为1.0。同一未发布契约包含128个定义、132个虚构示例及17类内部WS消息封套，覆盖世界/任务/视觉、口播/平台字段、自然语言建议与五源完整历史。Task.recovery和disposition只属于A端投影，各自revision独立；B账本任务保留原上下文和权威版本。TaskCreate可附world_goal_ref与suggestion_ref，任务正文不携带A目标或建议元数据。任务取消走控制操作，不作为第六种新动作goal。不同消息方向、幂等数据库、世界一致性和租约仍须运行时校验。

以下关系不能仅靠JSON Schema证明：lease≥3×heartbeat、accept窗口≤stale阈值、序号连续、世界/boot/epoch一致、当前输入所有权、任务幂等、前置/后置条件、evidence实际真实性、当前正式播放源和配置技能已验收交集。投票另需验证option_id唯一、可信身份去重、同房间活动数量、截止冻结、平票选择属于最高票选项、胜出目标与真实task关联；不公开选民身份明细。GameState的age/freshness由服务端重新计算；不能直接相信客户端声称的新鲜度。

OpenAPI本轮检查结构、operationId唯一、路径参数、请求/响应引用和本地JSON Pointer；144个反例与132个有效示例分别校验。未安装完整OpenAPI规范校验器，不能把这些检查称为第三方规范校验通过。实际HTTP/WS/SQLite与Java互通结果见实现进度；真实MC、模型、正式媒体及客户端生成仍须分别验证。

GameState断线可保留最后确认模式用于显示，但automation_ready必须false，界面标明实际模式未确认。Task.succeeded必须有verified效果及至少一条证据；这只是结构条件，实际游戏结果仍由B核验。

RecipeSlot、RecipeChoice与RecipeResult描述当前服务器已接收的静态配方投影，inventory_checked固定false。服务端另核对原请求物品/数量、观测下界、批次数学、形状槽位、唯一排序、歧义/截断及全部未知项；Schema通过不证明这些跨字段关系或真实合成效果。实现与验证边界见[配方查询与DSH对接](../配方查询与DSH对接.md)。

capabilities-survival-fixture等全部示例均为虚构；其true值不能作为执行档已通过的证据。完整交付需要实际支持并验收screenshots、basic_pve、survival_rules与resource_chains，兼容的基础执行档Schema不降低这一完成要求。

036兼容扩展增加可选`journal_maintenance_history`能力与三种维护历史源。声明能力后按五源导入，旧桥保留两源；维护载荷、元数据和摘要分别定义，不借用Task或递送ACK。OpenAPI业务版本增加至1.12.0，HTTP操作仍为52项，A schema4/B schema3及游戏WS1.0保持。汇总按查阅到的内容版本保留，最小防重凭据不作为当前任务执行成功证明。
