# 2026-10-26 方案归档：女A、直播姬与 4090 迁移

[4090 目标](../RTX4090.md) · [迁移手册](../deployment/RTX4090_MIGRATION.md) · [全部文档](../README.md)

## 归档决定

人物和配套场景继续为 **女A / 林知夏 / 日光宿舍**，不继续构建新角色。实时链路采用本地 MOSS 04、MuseTalk 和预生成完整身体动作库；云端只承担用户指定的文字模型。后端以 DSH + Humanity 保持人格、同场上下文、观众隔离和跨场记忆。

B站使用官方直播姬，直接加载竖屏浏览器素材与源内音频。账号已有开播权限、没有开放平台应用；弹幕先用现有 Web 客户端，官方应用接口保留独立扩展路径。抖音历史适配器仍在仓库，但本次归档不宣称已完成抖音真实账号开播。

**主运行目标改为 4090（REMOTE_4090_HOST，48 GB 显存）；3080 作为历史参考。** 本次更新仓库与方案内容并同步目标机器，不自动停止现有直播或替换活动记忆。

## 完整方案阅读地图

| 主题 | 正式文档 |
|---|---|
| 整体技术链路、本地/云端分工 | [架构](../ARCHITECTURE.md)、[中英双语 README](../../README.zh-CN.md) |
| 女A身份、场景、动作和素材归档 | [角色](../CHARACTERS.md)、[素材](../MATERIALS.md) |
| MOSS04、音色选择、当前等待与精度 | [实时语音](../MOSS_LIVE.md)、[音色](../VOICES.md) |
| 人格、状态、来源和一致性规范 | [DSH总方案](../DSH_HUMANITY.md)、[状态协议](../dsh-humanity/LIVE_STATE.md) |
| 下播压缩、每日合并、每周整理 | [记忆流水线](../dsh-humanity/MEMORY_PIPELINE.md)、[运行手册](../dsh-humanity/RUNBOOK.md) |
| 记忆更正、归档合并、删除和恢复 | [管理契约](../dsh-humanity/ADMINISTRATION.md) |
| B站直播姬安装、源内音频、开播和下播 | [直播姬实现](../platforms/BILIBILI_LIVEHIME.md) |
| 平台评估、弹幕事件、去重和队列 | [平台接入](../PLATFORM_INTEGRATION.md) |
| 当前代码、实际测试与限制 | [实施记录](../dsh-humanity/IMPLEMENTATION.md)、[平台验收](../platforms/ACCEPTANCE.md) |
| 截图、实际视频、GIF与来源 | [平台媒体](../platforms/MEDIA.md)、[总展示](../GALLERY.md) |
| 4090库存、部署参数、私有状态和切换 | [4090主目标](../RTX4090.md)、[迁移手册](../deployment/RTX4090_MIGRATION.md) |

## 此次已验证事实

| 层次 | 事实 | 证据边界 |
|---|---|---|
| 本地客户端 | 官方直播姬 8.11.1.11202，720×1280 / 30 FPS H.264＋AAC录像 | 音视频实际来自本地 MOSS04 / MuseTalk，不依赖 OBS |
| 五项本地测试 | 欢迎、去重、讲解、同场暂停恢复、两条顺序播放通过 | 五项含五次语音；去重本身无新语音；输入是本地注入 |
| 语音账本 | 五次均连续样本完整并自然结束 | 本地播放确认，不自动等同于观众听到 |
| 云端 | 原 gpt-6-luna Responses 渠道恢复，兼容/工具探针通过，独立 AI 语音完成 | 与早先 Echo 录像分开记录；初轮超时仍保留 |
| 公开开播 | 主播完成人脸验证后，官方客户端进入开播态；B站 API 返回房间595139 `live_status=1` | 记录时刻事实，不保证阅读文档时仍在线 |
| CDN | 拉取10.086秒公开流，成功解码H.264视频与AAC音轨，720×1280 / 30 FPS | 抓取时为待机画面；未测量公开流里可听的回复 |
| 真实观众弹幕 | WebSocket与心跳连通 | 尚未完成真实新弹幕→AI→观众端语音的完整验收 |
| 自动化回归 | 76 Node、23 Python、21原生代理路由通过 | 适用于该次代码和范围；不替代4090运行测试 |

本地完整原速录像为209.13秒，生成等待保留；五段节选和GIF只用于查看说话效果，不能用片长当作响应时延。3080欢迎和讲解的提交到完成时间约45.567秒、36.040秒；显存采样峰值9745MiB，最少空闲309MiB。迁往4090的理由包含资源余量和用户实测体验，但尚无4090新版本性能数字。

## 公开媒体与校验

- [官方直播姬本地带声音节选](../media/livehime-local-preview.mp4)
- [实际公开CDN十秒抓取](../media/bilibili-public-cdn-preview.mp4)
- [公开CDN实际画面](../media/bilibili-public-cdn-frame.png)
- [五项测试及后续公开开播证据](../evidence/bilibili-livehime.json)
- [媒体文件hash与来源清单](../media/livehime-media-manifest.json)

只发布解码结果和去凭据媒体，不发布带签名的CDN地址、平台Cookie、渠道key、人脸二维码或桌面代理信息。

## 未完成项与下一次执行入口

4090本次交付的是完整Git检出、方案文档和目标配置示例。旧GPU安装可复用，但MOSS两组模型/依赖、新DSH与直播姬运行部署、最终私有记忆迁移以及新机器实播测试仍按迁移手册执行。仓库准备与4090性能验收分别记账，不把3080的通过结果套用到4090。

后续从 `docs/deployment/RTX4090_MIGRATION.md` 第6节继续，优先目标4090。正式切换前先结束3080公开直播并保存一致状态；完成4090本地五项测试后再接管房间595139。

## English archive note

This snapshot preserves the delivered female-A identity, portrait motion bank, local MOSS 04/MuseTalk pipeline, DSH + Humanity personality and memory system, and native Bilibili Livehime integration. The account owner completed the official verification; public room status and a 10.086-second CDN decode were checked separately from local Echo and cloud-AI tests. A real viewer-comment-to-audible-reply round trip remains unverified.

Future operation targets the 48 GB RTX 4090. The repository and runbooks are synchronized without silently cutting over the running 3080 stream. Model/runtime installation, consistent private-state transfer and new-machine performance acceptance remain explicit activation stages.
