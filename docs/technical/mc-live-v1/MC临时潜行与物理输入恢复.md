# MC临时潜行与物理输入恢复

第071轮，mc分支，完整交付D03/D04。完整普通生存与PvE范围、冻结横屏设计和全部验收要求保持。

## 1. 实际游戏路径

固定AltoClef的ProjectileProtectionWallTask.interact会保存player.input.sneaking，将其设为false，执行方块交互及挥手，再恢复先前值。交互抛错、任务许可在中间撤回时，后一次恢复可能不执行。此前两个字段写入经过一般任务许可检查，但没有登记临时输入归属。

本轮把这两个PUTFIELD转换为SurvivalInputs.sneaking(Input,boolean)，经原ArbiterBoundary和InputOwner.Scope进入唯一原生InputOwner。每次写入核对原控制Permit、输入代数、主线程、玩家/世界/网络/交互管理器身份、存活、聚焦和暂停状态；Input必须是当前玩家的实际输入对象。没有新建第二位键鼠写入者。

GatePolicy只接受Input.sneaking:boolean的固定字段签名，BytecodeGate只接受实例字段写入，观察读取保持原语义。固定上游源码不在生成目录手改；现有构建管线转换实际产物，并检查最终报告中两处sneaking路线。

## 2. 临时字段归属

OwnedFlag登记首次实际变化之前的布尔值和本任务写入值。相同值请求不触发写入或取得归属；上游后一次写入回到原值时立即结束临时归属，因此不会把下一次正常键盘更新误判为本任务仍持有的值。

异常、撤权或接管后，原输入代数统一清理。字段已有不同的后续值时保留该值。非KeyboardInput的合成输入恢复本任务原值；KeyboardInput在清理当下通过既有PhysicalKeys/绑定键读取真实物理状态，采用当前重映射、鼠标或扫描码路径。不能用进入交互前保存的“曾按住”覆盖交互期间的实际松键。

输入对象被替换时，旧记录不写入新对象。临时字段恢复与既有movement输入对象恢复由同一InputOwner完成；旧Session、旧输入代数的迟到清理不能恢复到新任务上。字段恢复不发送游戏包，也不重新取得AUTO。

## 3. 失败和边界

物理状态读取或字段清理失败会保留原输入代数和原根清理责任，阻止新根越过未处理的恢复。显式重试继续使用原记录；不隐式重新派发游戏动作。字段变化后报错的记录仍可清理；后续不同的外部值不被覆盖。

布尔值本身不能证明两个同值写入的来源；对原生键盘的退出恢复因此读取当前物理状态。其他合成输入仍按已登记对象和值恢复。该实现只覆盖两个临时潜行字段写入，不能据此认定所有字段、飞行能力、其他包、回调或物理接管均已覆盖。

## 4. 实现与验证

| 编号 | 实现位置 | 内容 |
|---|---|---|
| S01 | fabric/src/main/java/dev/aitalkstreamer/mc/core/OwnedFlag.java | 临时布尔输入归属、同值无效果、正常回原值结束归属、恢复重试 |
| S02 | fabric/src/main/java/dev/aitalkstreamer/mc/InputOwner.java | 原Scope、当前Input身份、当前物理绑定读取、统一清理 |
| S03 | survival/src/main/java/dev/aitalkstreamer/mc/survival/ArbiterBoundary.java及SurvivalInputs.java | 原任务许可到唯一原生控制器的接线 |
| S04 | survival/gate-policy.json及src/audit中的GatePolicy、BytecodeGate | 两个字段写入的强类型转换及签名拒绝 |
| S05 | scripts/mc_check_survival_build.py | 最终转换报告、桥包OwnedFlag/控制器、选定路线和测试报告核验 |
| S06 | fabric/src/test中的OwnedFlagTest、survival/src/test中的SneakGateTest | 9项临时字段检查与19项跨端实际控制类检查 |

检查使用真实编译的BytecodeGate、SurvivalInputs、SurvivalAuthority、ArbiterBoundary、InputOwner/Scope、InputLeaseFence、PhysicalKeys和ControlArbiter；MC/GLFW接口是明确替身，不打开游戏窗口或调用实际GLFW。覆盖原许可、4个原生上下文身份、错误线程、失焦/暂停/死亡、松键/仍按住、当前重映射/鼠标/扫描码、交互报错、字段外部变化、输入对象替换、原输入与移动输入联合恢复、物理读取失败重试和旧根隔离。

本轮完整构建、当前源码包及实际结果保存在[本轮证据](../../evidence/mc-runtime-round-071.json)。原生构建沿用已锁定JDK21、Gradle8.14.3、MC1.21.1和现有本地依赖，不使用Docker、WSL或虚拟机。

## 5. 完整交付状态

生存候选SurvivalLaunchGuard继续无条件preLaunch拒绝，原静态位置清单继续保留UNREVIEWED。真实Minecraft运行、全部写点/输入恢复、服务端效果、完整普通生存/PvE、DSH/模型/视觉、人物与官方直播输出仍须继续联验，不能把替身检查记为实机通过。

真实验收0/68，新人物0/100，完整15领域与原全部待办见[实现进度](实现进度.md)、[机器状态](implementation-status.json)及[完整总纲](13-完整方案实施总纲.md)。
