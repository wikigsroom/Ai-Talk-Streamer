# MC原生应用profile与准备

对应实现记录029、030兼容修正、032源码安装接线及082的NeoForge应用准备。本文把[06章](06-部署与故障恢复.md)的应用profile要求接入原有设备启动检查。[总计划](12-一次完整交付总计划.md)、D01–D15和全部68项验收保持完整范围；本文的准备记录不计作游戏、模型性能、官方输出或最终发布验收。

## 1. 设备契约与应用来源分别绑定

当前公开配置为[mc-native-3080-neoforge-v1](../../../configs/deployment-profiles/mc-native-3080-neoforge-v1.json)。原[Fabric配置](../../../configs/deployment-profiles/mc-native-3080-v1.json)保留为历史来源，不能作为当前NeoForge安装的准备证明。它明确source_branch=mc、device_target=rtx3080、原生同机拓扑、FP16/batch4/25FPS、`state/female-a-3080-k02`及初始PAUSED。原有`deployment-target.json`、设备注册表和K02发布指针继续按原值核验。4090应用profile及控制仍未启用。

profile绑定冻结布局revision04与其SHA256、MC1.21.1、Loader0.16.14、Fabric API0.116.6+1.21.1、既有生存构建锁和3080原生模型锁。布局、MC/Fabric或设备映射不一致时预检失败。模型锁中的Python3.10.22、Node24.22.1、原生x64 JDK21分别实测版本；JDK的实际小版本和二进制hash写入本机准备记录。

新准备记录位于`.setup/mc-native-preparation.json`，由准备命令在真实mc检出或经过核验的[无Git源码安装目录](MC源码包导出与原生安装.md)生成。原有`deployment-origin.json`不被修改。没有新记录时，原有启动检查仍拒绝将mc当作设备部署分支；有记录时，[deployment_target.py](../../../scripts/deployment_target.py)先复核完整应用证明，再使用同一设备/GPU/batch/DSH状态检查。

## 2. 原生准备与诊断命令

在既有Windows安装中，将[绑定模板](../../../configs/mc-runtime.example.json)保存为`configs/mc-runtime.private.json`，填入实际Node、人物环境Python和原生Java可执行文件路径。相对路径必须在本安装内；绝对路径必须指向对应的node.exe、python.exe或java.exe。绑定文件由Git忽略。模板中的JDK路径不是已安装证明。

```powershell
python -X utf8 -B scripts/mc_runtime.py describe
python -X utf8 -B scripts/mc_runtime.py preflight
python -X utf8 -B scripts/mc_runtime.py prepare
python -X utf8 -B scripts/mc_runtime.py status
```

| 命令 | 实际行为 |
|---|---|
| describe | 只读核对公开profile、冻结布局、设备映射和版本锁 |
| preflight | 只读核对源码、GPU/运行配置、原生程序、既有模型/DSH/游戏构建物及项目空闲情况；逐项JSON结果，失败退出码1 |
| prepare | 空闲时执行同一预检、再次核对源码与文件，原子生成本安装准备记录；不安装依赖或启动服务 |
| status | 只读复核已存准备记录、当前源码/文件/原生程序；结果范围为准备证明有效性，不代表服务正在运行或当前GPU已验收 |
| operation-status | 只读报告本安装原生操作的占用、阶段和恢复需求；不检查服务就绪，详见[原生启动事务与失败回收](原生启动事务与失败回收.md) |
| supervision-status | 只读报告提交后各进程组的实际监督身份、故障/停止阶段和回收凭据；不启动服务或证明模型就绪，详见[持续监督](原生运行持续监督与故障回收.md) |
| prepare --refresh | 完整复核更新后的安装，把旧准备记录另存`.setup/mc-native-history`后原子替换；失败保留原记录 |

预检失败时按checks中的项目解决后重新检查；程序不自动下载、切换设备、改写来源、放宽batch或清理占用。源码目录当前缺少真实运行绑定/原生模型等条件时应报告未准备，不写出成功记录。

## 3. 源码、程序与文件证明

源码检出读取实际Git分支和HEAD，通过Git列举已跟踪文件与未忽略的新文件。范围覆盖backend、web、integration、scripts、deployment、configs、game-adapters、docs/dsh-humanity、运行协议Schema、根依赖清单/忽略规则、CMD/PowerShell入口和项目许可证。032补齐旧清单漏掉的协议/入口/许可证，生成的verification.json另作检查产物。构建/模型/状态/私有绑定不作为公共源码；每个文件保存实际SHA256，完整清单另有snapshot_sha256。无Git安装读取独立源码来源记录并实际扫描全部公共源码，修改、新增、删除或复制记录到另一位置均拒绝。

脏工作区可以被如实登记：HEAD只提供提交来源，实际运行源由完整文件清单描述，不把未提交改动冒称为该提交内容。源码修改、新增、删除、分支或HEAD变化均要求重新准备。列举有文件数/总大小限制，拒绝路径越界、符号链接和junction。

| 证明内容 | 核对方式 |
|---|---|
| 原生Node | 实际24.22.1/win32/x64；用内存SQLite完成原生模块探测；二进制hash |
| 原生人物Python | 隔离模式仅探测标准库，实际3.10.22/win32/64位；不导入CUDA或人物模型 |
| 原生Java | 实际JDK21和amd64、实际版本；不启动MC或Gradle |
| 人物与声音基线 | 既有readiness/asset-check；模型锁每个文件的字节数与实际hash、O07参考、O07/F07精度及硬件preset |
| DSH/Humanity | 源与安装package/package-lock相同、固定包版本、原生Humanity补丁及connector实际hash |
| NeoForge游戏前提 | NAIMEI离线身份、原319模组及当前控制器、复制原生库、JRE、资产对象和准确构建源码/JAR/schema/嵌入依赖；游戏前提独立于人物/模型检查报告 |
| 本机配置 | 硬件、人物/TTS、DSH指针/策略、运行绑定均保存hash；不输出其原文或凭证 |

后续启动会再次核对源码、文件hash和原生程序探测。完整模型hash检查有磁盘读取成本，不能在报告中伪称瞬时操作。当前检查不覆盖所有第三方源码/依赖的完整许可证对应、真实推理兼容、全部媒体素材或视觉模型，D01/D09–D12继续保留这些要求。

## 4. 启动、停止与准备互斥

原有人物/TTS启动、`start_studio.py`、`dsh_control.py start`等调用同一个设备检查，所以无需给mc增加无条件分支例外。准备证明有效只代表该本机原生环境允许进入既有启动前检查；各服务自身的资产、显存、端口和单所有者要求仍继续执行。

prepare拒绝已有端口占用和仍在启动/关闭的本项目宿主、人物、TTS或接收器进程。只识别本安装的精确入口，不停止其他应用。准备期间的独占锁阻止另一准备者和新的设备启动检查。异常中断留下锁时，报告需检查原准备任务；不通过删除未知锁自动继续。跨入口的完整进程启停事务、启动失败回收和MC客户端/视觉/官方端统一编排仍属D01待办。

原有停止入口继续允许处理不匹配或正在退出的安装，不能要求先重新准备才能停控/停止。DSH保留开播会话拒绝退出及唯一SQLite写入者约束；来源证明不接管或替代这些生命周期。

## 5. 保留的运行门禁与安装边界

准备记录始终声明automatic_input_authorized=false和真实验收0项；它不会开启游戏配置、AUTO、恢复旧任务或申请正式播放权。受控生存候选的无条件preLaunch拒绝保持原样，全部D03/D04实现与实机证据补齐后才能按实际审查关闭该门禁。旧人物基线和本机模型文件齐备也不代表新100段人物已制作。

记录绑定本安装绝对位置、真实mc来源与全部清单，不能复制到另一个路径或把旧设备来源改成mc冒用。032新增项目源码ZIP导出、摘要核对及无Git新目录安装，完整环境准备与既有启动检查可据实际源码包来源继续核验；源码包本身不生成环境证明。完整依赖/许可/上游源码、应用安装包、一致备份及干净原生复现仍需完成，沿用完整D01交付，不手工伪造`.setup/deployment-origin.json`。

029实现并本地验证上述配置/准备/启动前约束，结果见[029证据](../../evidence/mc-runtime-round-029.json)。该次测试使用Python3.13；030在生产要求的真实Python3.10.22下发现并修正两处兼容问题，见下节。原生程序探测、GPU查询与文件核对不会启动游戏、加载人物/TTS/视觉模型或开播。完整真实验收仍0/68，新人物仍0/100；本地夹具中的原生程序探测替身仅证明代码路径。

## 6. Python3.10.22兼容验证与本机测试解释器

030记录日期为2026-10-31（Asia/Taipei），见[030证据](../../evidence/mc-runtime-round-030.json)。029的Python3.13通过记录及其源码快照保持原样，不被追认为生产Python验证。030先用真实Python3.10.22复现原故障，再修正、回归和留存实际输入。

| 兼容问题 | 真实复现与修正 |
|---|---|
| 文件校验调用新版标准库 | 3.10.22执行原sha函数报hashlib没有file_digest；现用固定大小分块更新SHA256，保留空文件及大于读取缓冲的二进制文件校验用例 |
| 目录联接识别静默缺失 | 3.10.22没有Path.is_junction，原fallback在真实Windows内部junction上未拒绝；现读取lstat原生mount-point标签，同时保留符号链接与解析后目录约束；实际junction用例检查拒绝后只移除测试联接并确认原目标内容保留 |

最终55项部署检查及3项DSH生命周期检查共58项通过，030新增2项；同一条用例的中间重跑不重复计数。测试进程确为Python3.10.22/win32/64位；源码/文件/Git/路径检查使用真实文件系统，设备及Node/Python/Java版本探测夹具仍有替身。真实本目录describe通过，preflight与status继续报告设备/绑定/运行文件未准备，前后监测配置与来源文件一致。

为取得版本一致的测试解释器，本项目单独保存`tools/cpython-3.10.22-compat-validation`。来源为[Astral官方20261009发布](https://github.com/astral-sh/python-build-standalone/releases/tag/20261009)的Windows x64 install-only stripped归档，归档SHA256为`f20288c45ff11e7fe026f40ddcfb2acfe695cec18860746639e289142a589745`；下载后先核对官方元数据中的大小和SHA，再逐项检查归档路径并解包。独立安装的psutil7.2.1来自[PyPI版本元数据](https://pypi.org/pypi/psutil/7.2.1/json)，使用校验后的本地ABI3 Windows wheel安装，不执行远程脚本。

依赖来源元数据、实际解释器/3122份安装文件清单、归档/wheel hash、准确命令、两项修正前复现、中间与最终日志分别保存在`outputs/mc-validation/round-030`；解释器、缓存与本地验证产物不提交Git。首个归档网络请求连接重置，重试取得完整归档并通过同一官方hash核验后才使用。

该解释器用于本机CPU兼容检查，没有人物/TTS/视觉模型及完整CUDA运行环境，不能填入正式人物运行绑定冒认准备完成。原人物环境及模型锁仍须在实际设备上完成依赖、推理、音画和完整负载验收；D01–D15与一次完整交付要求保持不变。


## 7. MC联合上下文容量与既有安装迁移

095将公开策略的`conversation.context_max_estimated_tokens`设为12000。094现场记录中，部分口播和游戏工具续轮需要6364–8609估算token，旧6000上限会在发送前拒绝；此调整提供原生状态、记忆、视觉结果和工具续轮的共同容量。估算仍为应用侧保守门禁，不等同服务商计费token或实测模型窗口。

已有安装不会因模板更新自动修改私有策略。迁移必须在本安装的DSH、人物、TTS、接收器和游戏均停止时，通过`configs/dsh-active-policy.json`定位并核验本安装内的真实策略，先保存逐字节备份，再只修改上述字段；记录旧值、新值和文件摘要，不输出私有策略原文。旧值不符合预期时停止迁移，随后重新执行readiness、preflight和prepare，不复用旧准备证明。

该容量继续受1000–16000配置范围、每轮请求容量、工具最多6步、口播输出上限、每日预算、取消、65536字符签名回放限制和唯一DSH/Humanity播放源约束。增大上下文不能代替真实联合负载、延迟与内容质量验收；095的实际结果以对应运行证据为准。

## 8. NeoForge应用配置与真实安装清单

082将当前MC应用明确切换到用户提供的Minecraft1.21.1 / NeoForge21.1.248整合包。独立profile绑定NAIMEI、固定离线UUID、原319模组、服务器白名单要求及原设备/人物/语音/状态路径；它不修改原Fabric配置或生存preLaunch拒绝，也不接受旧Fabric准备记录作为新profile的准备证明。

`mc_runtime.py neoforge-status`只检查已有安装，不下载、不启动游戏或模型。实际清单读取供包439份锁定文件、复制模组及原生库、整个实际JRE，以及资产索引中的对象；资产大小与SHA1必须符合索引，清单同时保存其实际SHA256。控制器必须对应当前完整Java/资源源码集合、schema、构建脚本及两份固定依赖；再检查JAR中的控制类、原资源/schema、嵌入依赖及版本元数据。构建回执缺摘要、遗漏新源码或依赖不能绕过这些检查。

完整应用准备另须有明确的游戏连接配置：`enabled=true`，`endpoint=ws://127.0.0.1:3092/api/dsh/game/bridge`。18974是工程宿主，不能获得正式应用准备证明。此配置是连接目的地约束，不授予AUTO。设置、生成配置、日志、存档和任务账本会正常变化，不列为不可变文件；原账号、历史服务器及存档不导入。原供包配置的全面副作用审核仍单独待完成。

完整`preflight`分别报告`game_files`、原生程序、设备/推理配置、全部运行文件和空闲条件。游戏文件通过而人物/DSH配置缺失或正式端口被旧安装占用时，总结果仍失败，不生成准备记录、不停止原服务。完整安装后，仍必须由既有prepare流程现场核验并建立本目录的准备证明；禁止复制其他安装的证明、活跃SQLite或设备来源来冒用。

082的3080执行结果与限制见[本轮证据](../../evidence/mc-runtime-round-082.json)。独立资源清单和真实原生程序探测不等于真实DSH规划/弹幕/口播联合、全部素材、完整节目或68项统一验收。
