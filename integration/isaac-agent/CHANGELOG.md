# Changelog / 变更记录

## 0.1.0 · native130-dsh · 2026-11-07

- 从上游初始快照更新为本地逐帧控制 + 官方 DSH 策略架构；保留 MIT 来源。 / Extend the upstream initial snapshot with local per-frame control and official DSH strategy, retaining MIT attribution.
- 增加武器蓄力/释放、危险预测、地刺、TNT、路线防阻塞与相关回归。 / Add weapon charge/release, hazard forecasting, spikes/TNT, route recovery and regressions.
- 实现 12 类策略子集、4 个工具、短编号身份绑定、显式预算与效果回执。 / Add twelve strategic subsets, four tools, short-reference binding, budgets and receipts.
- 完善授权槽、存档哈希、真实暂停、进程归属、失联暂停与不自动恢复。 / Add slot/save gates, real pause, ownership, disconnect pause and no automatic resume.
- 修复原生运行时路径发现和首次安装；提供新机器存档备份配置与纯本地模式。 / Fix native runtime discovery and first deployment; add verified save setup and local-only mode.
- 提供中英文 README、架构/能力/运维/验证文档、真实截图、原速录像与 GIF。 / Add bilingual docs, real screenshots, original-speed video and GIF.
- 公开脱敏证据，明确模型网关可用性与策略收益尚未证实的范围。 / Publish sanitized evidence and distinguish gateway availability from unproven strategic benefit.

- 正式发布前修复根目录 IPC 忽略模式误排除测试样本的问题，补齐整包回归所需数据，并增加源码/插件/校验清单与自动正式发布流程。 / Fix IPC ignore patterns excluding regression fixtures; add complete source/plugin/checksum assets and final-release automation.
