# Documentation / 文档导航

后续主运行目标为 [4090](RTX4090.md)，完整方案已[归档](archives/2026-10-26-LIVEHIME-HANDOFF.md)，按[迁移与切换手册](deployment/RTX4090_MIGRATION.md)继续运行准备。3080 保留为历史实测参考。

当前运行方案为 **A4090推理 + B本机官方直播姬**：阅读[双机详细部署](deployment/SPLIT_DEVICE.md)、[英文指南](deployment/SPLIT_DEVICE.en.md)与[五段跨机验收、录像和剩余边界](deployment/SPLIT_DEVICE_ACCEPTANCE.md)。接收端不加载人物或语音模型。

B站当前默认由官方直播姬输出，详见[直播姬完整方案 / Bilibili Livehime](platforms/BILIBILI_LIVEHIME.md)。该路径不启动或调用 OBS；历史 OBS 媒体保留原来源。

[English README](../README.md) · [中文 README](../README.zh-CN.md)

This is the documentation for the delivered **daylight dorm / portrait / local-media** implementation. It describes MuseTalk with the selected MOSS 04 live voice and the original GPT-SoVITS installation option. The included recordings show real operation of the reference workstation; older recordings retain their original voice.

本项目交付的是**白天宿舍、写实人物、9:16 竖屏、本地音视频推理**方案。云端仅承担可选的 LLM 对话；人物肢体使用预生成动作库，口型随实时语音推理。

| Document / 文档 | Read it for / 内容 |
| --- | --- |
| [Split-device / A推理+B直播](deployment/SPLIT_DEVICE.md) | Native A/B installation, virtual LAN, H264/PCM, receiver, official source audio, memory ownership and recovery / 原生双机部署、源内音频、状态、回执、下播维护与切换 |
| [A4090 + B3080 current deployment / 当前部署](deployment/RTX3080_RECEIVER.md) | Official-client five-case results, real comments, latency breakdown and receiver restart / 官方客户端五段验证、真实弹幕、延迟分解及重启方法 |
| [Split-device acceptance / 双机验收](deployment/SPLIT_DEVICE_ACCEPTANCE.md) | Five actual cross-device speech cases, recordings, regression results and official-client boundaries / 五段跨机实录、测试与官方客户端边界 |
| [RTX 4090 / 后续主运行目标](RTX4090.md) | Complete archive, target inventory, repository synchronization, model/configuration gaps and consistent memory cutover / 归档、同步、部署差异及记忆迁移 |
| [Platform integration / 直播平台接入](PLATFORM_INTEGRATION.md) | Bilibili, Douyin, OBS, native comment adapters, event queues and per-viewer memory / 双平台评估、无开放应用基础路径、完整实现和验收边界 |
| [Platform media / 平台实机录像](platforms/MEDIA.md) | Actual control pages, loopback RTMP, MOSS speech, GIF and account-validation boundaries / 真实页面、本地推流与账号验收边界 |
| [DSH + Humanity / 人格与持续记忆](DSH_HUMANITY.md) | Normative lifecycle, receipts, isolation, consolidation and recovery; implementation/acceptance status is separate / 状态、播放确认、隔离、压缩合并及恢复；实际状态见实施记录 |
| [DSH implementation / 实施记录](dsh-humanity/IMPLEMENTATION.md) | Code map, channel inheritance, verified scope and outstanding gates / 代码、继承网页渠道、证据边界及剩余验收 |
| [DSH runbook / 操作手册](dsh-humanity/RUNBOOK.md) | Native installation, broadcast timeline, schedules, corrections, deletion and restore / 原生安装、下播时间线、周期任务、更正、删除与恢复 |
| [DSH administration / 管理与范围重建](dsh-humanity/ADMINISTRATION.md) | Exact archive/merge/undo, paged queries, durable SSE, stale-control protection and bounded rebuild contracts / 归档合并、补偿、分页、订阅及范围重建 |
| [DSH acceptance / 验收记录](dsh-humanity/ACCEPTANCE.md) | A01–A40 evidence and remaining gates; S1–S5 require the real channel / 逐项证据及剩余门槛 |
| [DSH media / 实机页面与录像](dsh-humanity/MEDIA.md) | Actual studio, memory UI, Echo recording and GIF; no cloud LLM in this capture / 真实页面、原文播报与来源记录 |
| [MOSS 04 live / MOSS 04 实时播报](MOSS_LIVE.md) | Selected voice, actual local adapter, cancellation, warm-up and measured waiting time / 当前音色、本地适配器、打断、预热和等待实测 |
| [Voices / 女A音色](VOICES.md) | Ten MOSS voices and ten matched SoulX voices, plus FireRed 01 / MOSS 十款与 SoulX 十款同号对照、FireRed 01、修改与重新生成 |
| [RTX 3080 / 3080 部署](RTX3080.md) | Actual 10 GB tests, original batch-8 configuration, screenshots and explicit fallback order / 10 GB 实测、原始 batch 8、截图与降级顺序 |
| [Playback / 播放连续性](PLAYBACK.md) | Presented-frame measurements, audio integrity and backpressure correction / 实际呈现帧率、音频完整性与队列修正 |
| [Deployment / 部署](DEPLOYMENT.md) | Native Windows prerequisites, installation stages, preparation, restart and recovery / 原生安装、素材预处理、启动与恢复 |
| [Usage / 使用](USAGE.md) | Browser controls, channel settings, gestures, recording, OBS and HTTP calls / 网页交互、渠道、动作、录制及接口 |
| [Architecture / 架构](ARCHITECTURE.md) | Media preparation, speech, GPU isolation, frame alignment, transport and cancellation / 准备与实时链路、对齐及打断逻辑 |
| [Configuration / 配置](CONFIGURATION.md) | Model versions, ports, environment variables, local files and exposure boundaries / 版本、端口、配置文件和运行边界 |
| [Night casting / 夜间角色选型](CHARACTER_CAMERA_V3.md) | V3 camera revisions for 01–03, Clove cosplay, five enclosed night sets / 01–03 新直播机位、暮蝶 Cos、五款封闭夜景选型 |
| [Character / 女A 角色档案](CHARACTERS.md) | 林知夏、日光宿舍、分类素材归档与校验 / Identity, paired scene and verified archive |
| [Materials / 素材](MATERIALS.md) | Asset counts, directory map, hashes, review and optional local regeneration / 素材清单、审核、校验与可选再生成 |
| [Testing / 验证](TESTING.md) | Five real scenarios, measured behavior, acceptance evidence and repeatable checks / 五段实录、实测结果和复验命令 |
| [Gallery / 展示](GALLERY.md) | Six screenshots, four GIFs, six MP4s and their provenance / 页面截图、GIF、录像及来源 |
| [Troubleshooting / 排障](TROUBLESHOOTING.md) | Startup, resource pressure, lips, audio, network and recording issues / 启动、资源、口型、声音及录像问题 |
| [Contributing / 开发](../CONTRIBUTING.md) | Source layout, checks and contribution hygiene / 代码分工、检查与提交约定 |
| [Third-party notices / 上游说明](../THIRD_PARTY_NOTICES.md) | Code, models, voice and media attribution / 代码、模型、声音和素材许可 |

For a first run: read the Chinese or English root README, follow Deployment, test **原文播报 / Echo**, then configure your LLM and the official Bilibili Livehime output. For visual review, start with Gallery and Testing. For implementation work, read Architecture and Contributing.

首次使用：先读根目录 README，再按部署文档准备，优先验证原文播报，之后配置云端模型和B站官方直播姬。查看效果请读展示和验证文档；修改代码请先读架构与开发说明。

The upstream checkouts, Python environments, model weights and machine configuration are deliberately outside Git. The checked-in assets can rebuild the motion bank without calling an image or video generation service. A full fresh GPU installation has not been repeated for this publication; the recorded reference system and the repository checks have different scopes, documented in Testing.

上游源码检出、Python 环境、模型权重及设备配置均不提交 Git。仓库里的已验收视频足以重建直播动作库，无需重新生图或生视频。本次整理没有重跑完整的全新 GPU 安装；实机验收与仓库静态验证的范围见验证文档。
