# 设备分支 / Device branches

从2026-10-29开始，两个推理目标使用独立部署分支。`main`是公共源码入口，
不指定推理设备，不直接启动人物、TTS或DSH。两端沿用女A、K02、O07主用和F07备用，
部署参数与验收状态分别保存。

| 分支 | 推理设备与输出 | 人脸参数 | 唯一DSH状态目录 | 验收状态 |
|---|---|---|---|---|
| [`deploy/rtx3080`](https://github.com/wikigsroom/Ai-Talk-Streamer/tree/deploy/rtx3080) | 3080原生同机推理＋本机8020接收器＋官方直播姬 | FP16 / batch4 / 25FPS / 720×1280 | `state/female-a-3080-k02` | 五段本地官方源播放已过；公开推流未复测 |
| [`deploy/rtx4090`](https://github.com/wikigsroom/Ai-Talk-Streamer/tree/deploy/rtx4090) | A4090推理＋B3080仅接收和运行官方直播姬 | FP16 / batch8 / 25FPS / 720×1280 | `state/female-a-4090` | K02激活与候选清理仍待用户通知恢复控制 |
| [`main`](https://github.com/wikigsroom/Ai-Talk-Streamer/tree/main) | 公共源码、分支导航与历史报告 | 无部署默认值 | 无 | 启动入口拒绝直接部署 |

**B3080接收角色与3080推理角色不同。** 在4090分支架构里，B3080的`receiver-b`
不加载人物或语音模型；3080分支则在同一设备运行全链路。不要因为看到“3080”
就把接收端与推理端的配置互相覆盖。

## 权威配置

- `configs/deployment-target.json`：当前分支目标、Git分支名和是否可部署。
- `configs/deployment-targets.json`：两个设备的固定映射、发布指针、GPU、batch、状态目录及验收范围。
- `configs/releases/current.json`：本分支发布指针；main只有分支目录。
- Git检出目录以实际分支核对；传统复制运行目录必须有`.setup/deployment-origin.json`，记录目标、来源分支和完整提交SHA。MC源码安装另有下述独立来源证明，不能用手填记录替代。
- `.setup`、私有配置、模型、运行环境、数据库和删除账本不属于Git分支。换分支不会迁移或隔离这些运行数据，必须继续使用独立安装目录与状态根。

启动检查读取实际显卡名称与显存，不分配CUDA模型。3080要求该型号及至少9000MiB；4090
沿用本项目48GB规格，要求该型号及至少45000MiB。显卡、分支、发布指针、batch或DSH状态
目录任一不符即报错。24GB4090需另建经过验证的规格，不能冒用当前48GB部署记录。

检查已接入`launch.py`人物/TTS启动、`start_studio.py`、DSH启动、3080配置器和K02命令行
激活入口。停止和状态查询继续可用，便于处理旧部署。它防止误操作，不替代操作系统权限。

## 获取与检查

032新增[MC公共源码ZIP导出与无Git安装](../technical/mc-live-v1/MC源码包导出与原生安装.md)。安装校验已审查的整包摘要、完整文件和公开profile后，独立记录`.setup/mc-source-origin.json`；只有完整本机准备证明有效，既有启动检查才接受该来源。源码安装不生成或改写deployment-origin；若存在旧设备记录，仍核对3080及其设备来源分支。源码ZIP不包含模型/依赖/完整素材，完整应用安装与实机验收继续待完成。

MC开发分支新增应用级[NeoForge原生3080 profile](../../configs/deployment-profiles/mc-native-3080-neoforge-v1.json)，设备目标、batch4和状态根沿用上述3080契约。由`scripts/mc_runtime.py preflight/prepare`核对真实mc检出、全运行源码清单、原生程序及锁定文件后生成独立的`.setup/mc-native-preparation.json`，不改写设备发布指针或deployment-origin。既有启动检查只有在完整准备证明与当前安装一致时接受mc来源；没有证明、源码/文件变化或复制到另一目录均拒绝。完整MC素材、执行器门禁、安装包和实机验收仍待完成，详见[MC准备说明](../technical/mc-live-v1/MC原生应用profile与准备.md)。

3080源码：

```powershell
git clone --branch deploy/rtx3080 --single-branch git@github.com:wikigsroom/Ai-Talk-Streamer.git Ai-Talk-Streamer-3080
```

4090源码：

```powershell
git clone --branch deploy/rtx4090 --single-branch git@github.com:wikigsroom/Ai-Talk-Streamer.git Ai-Talk-Streamer-4090
```

已有检出先保存自己的改动，再更新正确分支：

```powershell
git fetch origin
git switch deploy/rtx3080
git pull --ff-only origin deploy/rtx3080
python scripts/deployment_target.py --describe
```

4090将上面的分支换成`deploy/rtx4090`。`--describe`仅显示分支契约；完整启动预检使用
准备好的项目Python执行`python scripts/deployment_target.py`，它也会检查GPU和运行配置。
源码目录没有模型、私有策略或运行来源记录时，完整检查报未准备是正常结果，不能将其伪造成通过。

3080实际运行根仍是`C:\dev\虚拟数字人直播`，更新后的来源记录绑定3080分支。
本次分支整理只同步公共代码与来源信息，不重启模型、不迁移数据库、不改变已验收参数。
4090设备继续保持此前的暂停控制状态；建立和推送4090分支不表示已远端部署。

## 维护规则

1. 通用逻辑修复先在main提交，再将明确的公共代码提交应用到两个设备分支。
2. 两个部署分支不互相整分支合并。不要从另一设备复制`deployment-target.json`、`current.json`或私有策略。
3. 设备专属参数调整仅在对应分支完成；更新本分支清单、说明和独立验收，不改历史测评数字。
4. 同步前核对分支与目标，同步后重新执行只读目标预检；启动才加载模型。
5. 不把一台机器的PID、密钥、活动SQLite主文件或`.setup`整体复制到另一台。

3080正式分支只允许已验收batch4启动。原batch8失败记录保留；要重新进行不同强度实验，
应在单独实验分支明确更新目标规格并重新验收，不能悄悄改生产分支参数。

## English

Use `deploy/rtx3080` for the accepted single3080 native cohost deployment and
`deploy/rtx4090` for A4090 inference plus a receiver-only B3080. The latter's K02
activation remains pending; no4090 control or migration is performed by this change.
`main` is shared source with no inference target.

Each branch has its own release pointer and target descriptor. Startup validates the
actual Git branch or pinned copied-runtime receipt, GPU specification, MuseTalk batch
and DSH state root. The check is read-only and loads no models. Stop/status paths
remain available even for a mismatched installation.

Keep private runtime configuration and persistent state outside Git and in separate
installation/state roots. Selective common-code fixes may flow from main; never merge
one device branch wholesale into the other or copy private state through Git.

082起当前MC应用准备使用独立NeoForge21.1.248 / NAIMEI profile，旧Fabric profile及其生存preLaunch拒绝保留。游戏资源前提单独核对；正式DSH地址、原设备/状态与单所有者、完整推理资产和端口空闲条件共同成立后才允许生成本目录准备证明。资源检查不启动游戏或模型，也不迁移运行状态。
