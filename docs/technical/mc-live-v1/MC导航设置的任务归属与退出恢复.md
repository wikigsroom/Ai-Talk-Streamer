# MC导航设置的任务归属与退出恢复

第070轮，mc分支。对应完整方案D03/D04，不改变完整交付范围或已冻结横屏设计。

## 1. 修复的实际执行路径

固定版本AltoClef通过OptionsVer写入自动跳跃和亮度，通过BotBehaviour.State.applyState写入失焦暂停。固定版本Baritone在PathingBehavior的PlayerUpdate前后暂改自动跳跃。此前这些设置变化没有独立登记原任务、实际原值和退出恢复。导航在前后两次回调之间被取消时，不能依赖后一次回调一定执行。

构建期将这5处调用转为SurvivalOptions的两个强类型入口：AltoClef三处，Baritone两处。GatePolicy仅接受SimpleOption.setValue(Object)和GameOptions.pauseOnLostFocus的固定签名，并通过现有Yarn映射生成intermediary路径。转换报告、实际类文件、嵌套Baritone包和最终重映射包继续接受原构建检查。

## 2. 任务内写入

实际变化必须在原SurvivalAuthority.Session中，由原ControlArbiter Permit逐次授权。要求Minecraft主线程、同一个GameOptions对象、当前玩家和世界存在、窗口聚焦且未暂停。只允许当前客户端的getAutoJump布尔值、getGamma的有限0至1浮点值，以及pauseOnLostFocus布尔值；其他SimpleOption对象和类型不接受。

SettingLease首次实际变化时读取并保存原值，setter之后再读取实际结果，支持原生设置校验和截断。重复请求同值不会取得该值的修改归属，也不会触发setter。多次导航前后变化共用原记录，不把中间值当成原值。

ControlledAltoClefDriver每tick在上游任务树之前调用checkpoint。已登记值被其他操作改动、GameOptions替换或上下文变化，会中止继续使用旧设置记录。只比较实际观测值，不能区分两个操作写入相同值的来源；这不是对全部人工设置入口的拦截。

## 3. 退出、接管和失败

设置记录在首次写入前注册到原根的清理列表。任务完成、取消、许可撤回后，原根清理只恢复仍与本任务最后实际写入值一致的设置；后续不同的人工值保留。GameOptions对象整体替换时，旧记录不写入新对象。旧Session再次关闭不能清理新Session的记录。

上游stop/pop在撤回原根的清理作用域中不再套用其内部旧设置；恢复统一交给已登记记录。恢复要求原客户端主线程，但允许失焦、暂停或已离开世界，以便真实退出路径可收尾。恢复不获取新控制许可，也不执行游戏动作或发出游戏包。

setter可能修改值后在回调中报错。实现会尝试观察实际值并保存原异常；清理同样报错时保留原根，阻止新根跨过未处理的恢复。下次清理若读到原值，可确认恢复，不重复触发同一个设置回调。无法读取实际结果或恢复结果不等于原值时，保留明确失败，不盲写未知状态。

上游初始化会重复套用已读到的失焦暂停值。无任务时仅允许这种相同值的无效果调用；实际改值仍拒绝。

## 4. 实现与检查

| 编号 | 文件 | 内容 |
|---|---|---|
| O01 | game-adapters/minecraft/survival/src/main/java/dev/aitalkstreamer/mc/survival/SettingLease.java | 实际原值、写后观测、外部改值保留与可重试恢复 |
| O02 | game-adapters/minecraft/survival/src/main/java/dev/aitalkstreamer/mc/survival/SurvivalOptions.java | 三项设置、原任务许可、对象身份和主线程约束 |
| O03 | game-adapters/minecraft/survival/src/main/java/dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver.java | 上游tick之前复查设置归属 |
| O04 | game-adapters/minecraft/survival/gate-policy.json及src/audit中的GatePolicy、BytecodeGate | 固定写入签名和两种命名空间的构建转换 |
| O05 | scripts/mc_check_survival_build.py | 检查5处路线、实际类、嵌套包及工程收据 |
| O06 | survival/src/test中的SettingLeaseTest、OptionGateTest | 8项设置记录及15项真实控制类/转换器检查 |

23项新增检查实际执行真实SettingLease、SurvivalOptions、SurvivalAuthority、BytecodeGate和本地ControlArbiter；Minecraft客户端API由明确替身提供，不启动游戏。覆盖前后回调中断、正常恢复、过期许可、人工变化、对象替换、错误线程、失焦/暂停、非法类型、setter变化后报错、恢复重试及旧根隔离。完整原生重建结果与包哈希保存在[本轮证据](../../evidence/mc-runtime-round-070.json)。

完整重建还发现Wire在每一种消息定义上重复注册全部145个Schema定义，原生检查出现Java堆内存不足。本轮改为每个Wire只注册一次打包的权威Schema，直接按定义URI校验，并拒绝不存在的定义。保留Schema自身校验，不调整库版本或增大默认测试堆。新增独立256MB原生JVM检查全部协议实例及两类拒绝行为；此前失败日志和XML保留在round-070/native-001中。此修复影响游戏桥实际运行，不能只用旧编译产物替代验证。

原生构建沿用已固定JDK21、Gradle8.14.3、MC1.21.1和现有本地依赖；使用scripts/mc_build_survival.ps1及OfflineInputs，不通过Docker、WSL或虚拟机。没有扩展管理页面。

## 5. 当前交付边界

这5处写入纳入原任务约束，不代表所有客户端设置或全部上游副作用已经覆盖。其他写点、线程、包、Mixin实机、物理键鼠接管、完整普通生存/PvE和真实服务端效果仍须继续实现与验证。静态清单继续保留UNREVIEWED，SurvivalLaunchGuard继续无条件preLaunch拒绝，不能把当前候选作为已经可实机自动游玩的版本。

完整运行环境、真实模型/DSH/视觉、官方直播姬捕获与观众音画继续依[完整总纲](13-完整方案实施总纲.md)推进。真实验收仍0/68、新人物0/100，完整15领域见[实现进度](实现进度.md)及[机器状态](implementation-status.json)。
