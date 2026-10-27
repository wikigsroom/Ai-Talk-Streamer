# Performance analysis / 性能分析

[4090 案例测评 / Online report](https://4090.sid.mom/cases/ai-talk-streamer/2026-10-27/report.html) · [2026-10-27 完整分析](2026-10-27/report.md) · [交互可视化](2026-10-27/report.html) · [16 页 PDF](2026-10-27/report.pdf) · [逐条 CSV](2026-10-27/data/requests.csv) · [资源采样 CSV](2026-10-27/data/resource-samples.csv)

本次冻结报告分析 A4090 推理 + B3080 官方直播姬的 7 条真实弹幕、5 条官方客户端验收，以及 A 当日保留的 20 条较早调试请求。包含逐阶段耗时、MOSS GPU / CPU codec / RTF、317 次播放采样、两机下播后资源、队列与维护周期、云端用量、公开中断及记忆整理的实际状态。

主样本收到弹幕到首次正样本播放回执平均 **34.10 秒**，到整句完成平均 **44.40 秒**。当前下播后的记忆维护因当天预算 20/20 而延后，不能视为本场持久事实记忆已经完成。资源样本为下播后常驻与预览，未冒充实播峰值。

The frozen report separates seven public-comment replies, five official-client cases and twenty earlier debugging requests. It includes phase timing, MOSS generation / CPU codec / RTF, 317 playback samples, post-broadcast resource samples, queue limits, cloud usage, a public-stream interruption and the actual memory-maintenance state. The 34.10-second mean ends at the official source's positive playout receipt; audience CDN delay is unmeasured. Maintenance was deferred at the daily 20-call budget. No additional broadcast recording was created.

Rebuild the report from its sanitized snapshot, without models or network access:

```powershell
python -X utf8 devtools/build-performance-report.py
node devtools/check-performance-report.cjs
python -X utf8 devtools/serve-performance-report.py --port 8769
```

生成依赖 matplotlib、reportlab、Pillow 与 Microsoft YaHei 字体；浏览器检查使用仓库现有 playwright-core 与本机原生 Chrome，测试结束关闭全部测试标签与浏览器。服务器仅向本机提供本报告，不加载模型或启动直播。数据里的时间、路径与状态均为快照，不代表阅读时的实时服务状态。

## Publication / 发布

已将报告加入现有 4090 案例测评站并发布到 Vercel 正式环境。保留原有 1,410 个案例源文件，仅更新首页入口并增加本案例；21 个公开文件逐一通过 HTTP 200 和 SHA-256 校验。线上浏览器筛选、时间轴、估算器与手机布局检查通过，测试浏览器已全部关闭。[发布与校验回执](2026-10-27/data/publication.json)。

The production case preserves the existing gallery assets. Public HTML, PDF, chart and data bytes match the staged report. Re-publishing uses `devtools/publish-4090-case.py` against the latest production source and refuses a concurrent production change; `devtools/check-4090-publication.py` checks source preservation and anonymous public downloads. The existing local Vercel session is used; no credentials enter the report.
