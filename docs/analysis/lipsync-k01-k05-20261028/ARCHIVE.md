# 测评归档 / Verified review archive

[浏览器报告](report.html) · [原始Markdown](report.md) · [同步对比页面](index.html) · [文件与SHA256清单](delivery-manifest.json) · [原生实验代码](../../../benchmarks/k01-k05-60s-20261028/README.md)

五组均为60秒、720×1280、25FPS，使用同一O07音频与同一动作序列。K03是合成教师初训与有记录的续训实验；K05为保留网络强度的原生执行适配。共享负载的离线耗时不能代表独占GPU或直播端到端延迟。历史测评与正式直播配置保持原样。

在本目录执行`python viewer_server.py --port 8039`，再访问`http://127.0.0.1:8039/`。原始MP4、WAV、JSON、来源抽样和图表按原结构归档；Git属性保留原始字节，避免换行转换破坏测评SHA256。

The portable archive preserves the measured evidence bytes. Run the standard-library viewer from this directory; Python3.10+ is enough and no GPU is needed for review. Large model weights, native environments and the8,000-frame training cache remain onA4090 and are referenced separately. No PDF, compressed archive, MCP records, account credentials or private memory database is included.

## 观看与验收 / Media and acceptance

[本机同步页面](http://127.0.0.1:8037/) · [A4090同步页面](http://192.168.196.209:8035/) · [五组60秒总览](K01-K05-comparison-60s.mp4) · [原始60秒WAV](audio/common-60s.wav)

![实际对比页面 / Review page](review-page.png)

![8—14秒嘴部预览 / Six-second silent preview](mouth-comparison-08s-14s.gif)

[本机17项检查](page-review.json) · [A4090入口17项检查](page-review-remote.json) · [初次起播失败](page-review-before-fix.json) · [修复前事件](startup-before-fix.json) · [修复后事件](startup-after-fix.json)

两个入口均要求音轨和视频实际向前播放，不能以seek后时间不为0冒充成功。首次起播竞态已修复并保留失败证据。All task-owned test browsers are closed; original model measurements remain unchanged.
