# 定型基线 / Frozen baseline: A4090 + B3080 v1.0.0

2026-10-27 将当前已实测双机方案定型为 `split-a4090-b3080-v1.0.0`。运行时代码固定为 `fb7e6e8b0f655b9d6b9863486cc0e6f8b1e8f697`；本次定型提交只补充发布基线、测试报告和文档，不改变实播模型、降低精度或重启进程。机器可读配置见[发布清单](../../configs/releases/split-a4090-b3080-v1.json)。

This release freezes the tested native A4090 inference / B3080 official Livehime architecture. Media playback and real-comment replies passed the recorded cases. Memory consolidation, public-state reconciliation, real gifts and audience CDN latency retain their explicit acceptance limits. Documentation publication does not imply a new GPU deployment or a restarted broadcast.

## 固定职责与参数

| 项目 | 定型值 |
| --- | --- |
| A | 4090 48GB / 64GB RAM；人物、语音、唯一 DSH/Humanity 写入者、弹幕采集 |
| B | 3080 10GB / 64GB RAM；轻量接收、官方直播姬、最终编码与上传；不加载人物或语音模型 |
| 角色 | 女A / 林知夏，知夏的日光宿舍，48 段动作素材 |
| 口型 | MuseTalk FP16、batch8、720×1280、25 FPS |
| 音色 | MOSS04 / v04 明朗亲和；MOSS-TTSD-v1.0，NF4 4-bit / BF16，FP32 CPU codec |
| 跨机媒体 | 一份共享 NVENC H264、视频目标 3Mbps；PCM16k 单声道；4s 接收缓冲 |
| B 播放 | 软件 WebCodecs 解码、直接 Canvas / WebAudio；浏览器素材源内音频 |
| 云端 | 用户自备渠道；本次 gpt-6-luna；无凭据进入清单或仓库 |
| 状态 | A `state/female-a-4090` 唯一权威；一房间一活跃回复、一播放权威；有效租约30s |
| 安装方式 | 原生 Windows / Python / Node；不使用 Docker、WSL、虚拟机或 OBS |

原操作者本机不再运行正式接收器；不在 A 打开直播姬或正式输出浏览器。B 退休的旧推理、MOSS 和 DSH 不应同时恢复。旧 415 个状态文件保持归档，不覆盖 A 状态。

## 重启现有已安装环境

以下是现有安装的启动命令，不是全新机器安装器。完整初装与状态切换分别见[双机部署](SPLIT_DEVICE.md)、[4090迁移](RTX4090_MIGRATION.md)及[B3080实际目录与依赖](RTX3080_RECEIVER.md)。不要重新执行 `--isolated-state` 建立新的正式记忆库。

A 设备，项目运行根：

```powershell
Set-Location -LiteralPath 'C:\dev\虚拟数字人直播'
.\Start-Inference.ps1 -PythonExe 'C:\dev\虚拟数字人直播\runtime\livetalking\Scripts\python.exe'
```

B 设备，接收器根：

```powershell
Set-Location -LiteralPath 'C:\dev\虚拟数字人直播\receiver-b'
.\Start-Receiver.ps1 -PythonExe 'C:\dev\虚拟数字人直播\runtime\livetalking\Scripts\python.exe'
```

官方直播姬浏览器素材位于 B 自己的回环地址：

```text
http://127.0.0.1:8020/output.html?output=platform&renderer=livehime&rev=3080-fb7e6e8
```

画布与素材均为720×1280，源内音频100%、输出到流，桌面与麦克风静音。启动程序不等于平台已开播；网页会话、播放权威、采集连接、直播姬与公开房间状态应分别检查。平台人脸验证由账号本人完成。

## 验收与已知问题

完整证据见[可视化报告](../analysis/README.md)，包含32条留存请求与CSV。当前官方客户端5/5、真实弹幕7/7完整播完；317次Canvas采样中位25.285FPS，欠载、缺包与解码错误为0。真实弹幕至首正样本回执平均34.10s、完整完成平均44.40s，均不包含B站观众端CDN延迟。

本场已经下播，模型仍常驻。以下不属于已通过范围：

- 本场下播记忆压缩 `DEFERRED / budget`；当日维护调用20/20，持久事实条目0。旧维护任务有6个 `extraction_failed`。不能将会话回复成功当作长期记忆已完成。
- 平台曾发出 `PREPARING` 并停止公开流，客户端状态曾未准确反映公开房间状态。需要公开状态对账；本次不猜测平台停止原因。
- 真实礼物、观众物理发声时延、全程实播CPU/GPU峰值未验证。下播后采样不冒充直播峰值。
- MOSS完整语音准备平均21.21s；本次没有部署流式TTS、GPU codec或减小缓冲等建议优化。

## 维护与变更规则

下播时停止平台弹幕采集并结束内部会话；在单写者上等待120s静默窗口，再按5s轮询调度持久任务。每日03:30、周一04:10执行增量计划，直播期间不提交维护结果。日预算耗尽时延后一小时重查，不保证一小时后一定完成。具体额度、租约和失败状态见[完整报告](../analysis/2026-10-27/report.md)。

后续每次改变音色、模型精度、batch、口型配置、播放缓冲、跨机编码、状态归属或记忆策略，建立新版本并重复官方客户端五段与真实弹幕验收。先保留原配置和只读证据；不静默降级、不混用历史旧路径结果、不复制活动SQLite主文件替代一致备份。公开网页只发布脱敏报告，不代理远程控制、渠道密钥、推流信息或活动私有状态。

## English acceptance boundary

The frozen media runtime is unchanged: MuseTalk FP16 batch8, MOSS v04 NF4/BF16 with CPU codec, 720×1280 at25FPS, shared H264/PCM and a4-second receiver buffer. One A state writer owns requests and memory; B only receives and broadcasts. Restarting the existing services does not publicly start Bilibili. The release accepts the measured media and comment cases while preserving the documented memory-budget failure, public-state mismatch and unmeasured audience/gift cases. Subsequent behavior changes require a new version and repeatable acceptance evidence.
