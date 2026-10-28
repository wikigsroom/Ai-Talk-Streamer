# 女A K01—K05口型横评 / Review bundle

**五组60秒原片已完成文件验证。**

在线：<http://192.168.196.209:8035/>；本机：<http://127.0.0.1:8037/>。

- [完整HTML测评](report.html) / [原始Markdown](report.md)
- [复现、调度与指标协议 / Reproduction and measurement](protocol.md)
- [原始表格CSV](results.csv) / [原始数据JSON](results.json)
- [同源60秒PCM WAV](audio/common-60s.wav) / [台词与逐句原音索引](audio/input.json)
- [交付文件大小与SHA256清单](delivery-manifest.json)

对比网页可选择任意两组同步播放、放大嘴部、拖动到相同时刻，并按生成耗时/RTF/显存排序。个人评分保存在浏览器，独立于原始数据。

## 在其他原生系统打开 / Portable viewing

需要Python3.10或更新版本；不需要第三方包、Docker、WSL或GPU。保持整个目录结构，在本目录执行：

```powershell
python viewer_server.py --port 8037
```

访问 <http://127.0.0.1:8037/>。若端口已被占用，用`--port 8039`并访问对应地址；不要终止已有服务。

The standalone viewer is read-only, binds to loopback by default and supports HTTP byte ranges. Copy the complete directory without flattening it. The bundle contains the five portrait files when completed, original speech, observed measurements and review materials. Large model installations and the8,000-frame training image cache remain on the4090 and are referenced by hashes/paths; they are not included in the delivery total.

No PDF or compressed archive is produced. Offline rendering throughput is not live-stream latency. K03 is a synthetic-teacher identity-training pilot; K05 uses the documented native adapter. This experiment does not change the production stream.
