# AltoClef候选源接口核对与完整接入约束

第008轮于2026-10-30核对MiranCZ/altoclef，固定源提交`1f8e038befeaed44b8a053402c69127866c46a4e`。第008轮仅做候选源码观察，当轮未构建/安装执行器。第009轮已有[固定源码、原生构建与任务入口](完整生存执行档构建与任务入口.md)，产物仍不可安装；未启动MC或授权自动输入。完整运行锁仍需由同一玩家的兼容实测定值；[源文件审计记录](../../../configs/mc-executor-source-audit.json)不是部署许可。

## 1. 已核对事实

| 编号 | 源码事实 | 对本项目的实际含义 |
|---|---|---|
| A01 | 官方说明提供Fabric1.21.1；配套Baritone内置，不要求另放一份 | 原生1.21.1/JDK21研究基线可继续，整套兼容尚不能标通过；拒绝重复Baritone |
| A02 | `AltoClef.runUserTask(Task, Runnable)`把任务交给UserTaskChain | 外部五类Goal必须映射为固定Java对象，不能拼接聊天指令或透传观众文本 |
| A03 | TaskRunner选择最高优先TaskChain；食物、防御等与UserTaskChain共用调度 | 保留其内部子任务协调，但所有链都必须受同一个Permit约束 |
| A04 | InputControls可直接按键与写yaw/pitch，PlayerExtraController可直接attackEntity | 仅调用Baritone.cancelEverything不能证明停键、停视角和停攻击 |
| A05 | UserTaskChain取消时也可能走onTaskFinish；完成回调本身不是后置证据 | 取消不能被回调改报成功；需要任务对象身份、原epoch及真实状态变化共同核验 |
| A06 | 设置装载及任务结束可触发idle命令，另有命令/Butler入口 | 禁止候选在未授权时自启idle/任务，不能只在GameManager入口限制 |
| A07 | GetToBlockTask可以创建跨维度子任务；TaskCatalogue的getItemTask表示获取资源 | 导航须约束允许维度与加载边界；获取资源不能冒充指定的合成操作 |
| A08 | 本项目当前对非gameplay界面统一停控，而资源合成可能主动开容器 | 接入需增加有任务身份/期限的预期GUI状态，不能把所有菜单泛化为允许 |

依据：[官方README](https://github.com/MiranCZ/altoclef/blob/1f8e038befeaed44b8a053402c69127866c46a4e/README.md)、[构建定义](https://github.com/MiranCZ/altoclef/blob/1f8e038befeaed44b8a053402c69127866c46a4e/build.gradle)、[AltoClef入口](https://github.com/MiranCZ/altoclef/blob/1f8e038befeaed44b8a053402c69127866c46a4e/src/main/java/adris/altoclef/AltoClef.java)、[TaskRunner](https://github.com/MiranCZ/altoclef/blob/1f8e038befeaed44b8a053402c69127866c46a4e/src/main/java/adris/altoclef/tasksystem/TaskRunner.java)、[UserTaskChain](https://github.com/MiranCZ/altoclef/blob/1f8e038befeaed44b8a053402c69127866c46a4e/src/main/java/adris/altoclef/chains/UserTaskChain.java)。输入、攻击、导航及资源接口分别在审计记录中固定URL与文件哈希。

## 2. 五类目标与取消的接入要求

| 外部操作 | 候选内部接口 | 实现及成功证据约束 |
|---|---|---|
| navigate | GetToBlockTask/配套Baritone目标 | 原世界、目标维度、位置及radius；只在新观测落入半径后成功 |
| gather | Registry Item + TaskCatalogue.taskExists/getItemTask | 支持项目显式列出，清楚定义目标库存数量与实际增加量，保留资源链及失败原因 |
| craft | 确定配方与CraftInInventory/工作台任务 | 当前真实配方、材料、GUI归属和craft_result；不得直接用通用getItemTask冒充合成 |
| use_item | 当前原生eat；其余equip/activate分别适配 | 各purpose独立声明支持项与效果核验，不能因为可选择物品就标成功 |
| return_base | 当前世界有效基地坐标 → 同一导航任务 | 基地引用必须匹配当前世界/修订；不读取旧世界同名基地，位置后置核验 |
| cancel | 整个任务树、所有链、配套寻路、输入/视角、GUI操作 | 先本地撤权，再完整停止/释放；迟到回调只归档，不复活任务或自动防御 |

PvE、补给、着火/水下/危险路径、工具与食物资源链为本次完整交付必需，不拆成用户交付批次。支持项清单必须绑定实际执行器构建、规则、装备、地形和难度，保留成功/失败/退出证据；任务预算到期必须停下并交还控制。

## 3. 唯一输入链的完整接入路径

1. 固定候选源提交、Loader/API/映射、内置Baritone及全部嵌套JAR哈希与许可，记录唯一游戏实例；原生Windows构建，不执行上游虚拟化构建示例。
2. 在源适配层覆盖TaskRunner/所有TaskChain入口、命令/idle/Butler自启及配套寻路事件；只允许当前受理任务树在原Permit内执行。
3. 列尽按键、输入覆盖、yaw/pitch、直接攻击/方块/物品交互、热栏/背包/槽位点击与容器关闭的实际写入。每个写点转为有界仲裁动作，保留物理输入所有权；不得把后台寻路线程直接变成输入写入者。
4. 预期GUI必须带任务/epoch/容器身份与短期限。人工打开其他界面仍先接管；GUI异常、死亡、失焦、断线、换世界、进度停顿、租约到期和panic均完整停树。
5. 完成回调仅请求核验；独立采样实际位置、库存、合成/使用/战斗效果，按任务版本发布结果。晚到旧回调不能覆盖终态。
6. 将支持项、配方、规则与执行档投影到capabilities及后台。先完成真实注入、同一玩家、基础技能、普通生存和20次接管，再进行全系统68项/4小时/次日验收。

第008轮已把本项目原生执行路径改为[固定Permit、进度看门狗及按epoch释放](本地输入许可与停顿处理.md)。第009轮已构建不可安装的候选并落实部分中央写点与任务入口，尚未完成上述全部改造，因此其自动化能力继续关闭；不会因本次源码研究把`basic_pve`、`survival_rules`或`resource_chains`标为true。
