# MC原生客户端依赖安装

> 2026-11-01更新：用户提供的实际目标是NeoForge 21.1.248整合包，离线名NAIMEI，游戏测试仅在3080执行。接入约束见[第14章](14-NeoForge整合包与NAIMEI接入约束.md)。本页Fabric依赖准备记录保留为历史，不证明新整合包的控制兼容或自动游玩。

本入口将同玩家Fabric执行所需的MC、Java和游戏资源安装到项目自己的运行目录，推进真实客户端联验的环境准备。它不启动玩家、模型或直播，不生成完整应用准备证明，也不解除生存执行器的preLaunch阻挡。

| 项目 | 固定值 |
|---|---|
| MC / Fabric Loader / Fabric API | 1.21.1 / 0.16.14 / 0.116.6+1.21.1 |
| 平台 / Java | 原生Windows x64 / Mojang提供的Java21 |
| 版本解析器 | PortableMC4.4.1，原始wheel的SHA256固定，不调用游戏runner |
| 依赖锁 | [mc-client.lock.json](../../../configs/mc-client.lock.json) |
| 安装目录 | 项目下runtime/minecraft/mc-1.21.1-fabric-0.16.14 |
| 玩家数据目录 | 同目录的work；独立于旧直播安装和用户默认.minecraft |
| 安装结果 / 进度 | .setup/mc-client-installation.json / .setup/mc-client-progress.json |

从本项目的原生Python运行：

```powershell
python scripts/mc_runtime.py client-prepare
python scripts/mc_runtime.py client-status
python scripts/mc_runtime.py preflight
```

client-prepare先核对公开的3080应用profile和真实源码来源，再进入既有原生操作锁。安装不要求推理GPU空闲；不执行推理环境启动、停止或迁移。Java安装在MC目录，不修改系统PATH。源码包安装须使用真实导出摘要和install-source生成的本目录来源证明，不能拷贝准备记录冒用。

安装前按固定SHA256校验四份上游元数据和原解析器wheel。Fabric无内嵌摘要的八份库另有公开固定SHA1/SHA256；Mojang游戏、Java、日志配置、平台库和资源采用锁定元数据里的SHA1及大小，并记录实际SHA256。资源索引包含3911个命名资源，重复内容按对象哈希合并。Fabric库使用fabricmc.net同组织的maven2端点和固定内容摘要；旧缓存不能只凭大小命中。

实际下载限制为八个工作线程，只提交当前窗口内的文件；发现失败后停止提交其余依赖，等待当前窗口收尾，不再排空数千项等待队列。HTTPS来源限定为上游域名；禁止未知跳转。下载先写同目录临时文件，大小和摘要通过后再原子发布。中断或摘要失败保留已完成的有效缓存及原文件；当前下载的临时文件在正常异常退出时回收。重跑重新校验缓存内容并补齐缺项。进度记录只表示依赖准备情况。

安装完成后实际执行该目录的java.exe版本探针，要求Java21和amd64；不运行MC主类。版本解析器仅返回主类、类路径和本机库路径，不创建离线玩家身份。安装结果逐文件记录路径、大小和摘要，client-status再次校验；本目录绑定、锁变化、文件损坏、缺失必要类路径或跨目录复制结果均拒绝。完整应用的runtime_files检查纳入这份结果及其全部文件，客户端缺失或变化时不能获得完整准备证明。

| 证据 | 可以说明 | 仍不能说明 |
|---|---|---|
| client-status通过 | 此安装目录内的客户端依赖匹配本版锁和实际文件 | MC已启动、控制器可运行、DSH已接通 |
| Java版本探针通过 | 安装的原生Java实际可执行且为21/x64 | Mixin、OpenGL、声卡或游戏帧率通过 |
| 本地协议及文件检查 | 下载中断、损坏缓存、路径和准备记录行为 | 实际MC、平台弹幕、模型或正式输出验收 |

客户端依赖安装不包含游戏桥/生存执行器安装、不配置玩家身份，也不包含模型、新人物素材、官方捕获或完整应用启停验收。完整交付仍按[实施总纲](13-完整方案实施总纲.md)和[全端实现蓝图](09-全端实现蓝图.md)执行；当前状态以[实现进度](实现进度.md)及[机器状态](implementation-status.json)为准。已有候选JAR的无条件启动阻挡继续保留，不能把依赖已安装写成已自动游玩。

上游参考：[PortableMC4.4.1](https://pypi.org/project/portablemc/4.4.1/)、[Fabric安装说明](https://fabricmc.net/use/installer/)。
