# Playback continuity / 播放连续性

[English README](../README.md) · [中文 README](../README.zh-CN.md) · [RTX 3080](RTX3080.md)

## Findings / 已确认问题

The October 24 investigation used native Chrome/Edge on the viewing workstation and the prepared RTX 3080 service. The former browser FPS statistic counted `drawImage` calls. It missed the second sampling stage: the canvas was sampled again at 25 Hz, then played through an HTML video element. Two probes of final presentation measured **18.78 FPS over 30 seconds while idle** and **22.17 FPS over 60 seconds including speech**, despite near-25 FPS arrivals. A controlled change to explicit canvas capture measured **25.01 FPS over 30 seconds**, with presentation p95 intervals improving from 85.3 to 49.7 ms in those idle samples.

10 月 24 日使用观看电脑的原生 Chrome／Edge 与 3080 服务排查。旧 FPS 只统计 `drawImage`，随后画布还会被独立的 25 Hz 采样再次捕获。最终视频实测待机 30 秒 **18.78 FPS**，含播报的 60 秒 **22.17 FPS**；只把捕获改成随绘制显式触发，同条件待机 30 秒测得 **25.01 FPS**。这些是独立采样窗口，不是所有设备的性能承诺。

The old sender also discarded the oldest **whole JPEG + PCM packet** whenever a viewer's three-entry queue filled. A later 61.65-second run, with the new browser but the old sender, lost **341 sequences** and registered **70 audio scheduling gaps**, with a 475.9 ms maximum arrival interval. Dropped PCM cannot be repaired by a larger browser buffer. Earlier quiet runs had no missing packets, demonstrating that average FPS and one successful recording were insufficient acceptance criteria.

旧发送端三包队列一满，就把最早的 JPEG **连同 PCM 声音**一起删除。后续一次 61.65 秒测试中新网页仍连接旧发送端，缺失 **341 个序号**，出现 **70 次音频排程缺口**，最大到达间隔 475.9ms。增加浏览器缓冲无法找回已经被删掉的声音；此前无丢包的样本也不足以证明持续稳定。

## Implementation / 修正实现

| Change / 修改 | Effect / 作用 |
| --- | --- |
| `captureStream(0)` + `requestFrame()` | Capture each scheduled draw explicitly / 每次绘制显式捕获，取消独立 25 Hz 二次采样 |
| PCM before JPEG decode / 先排音频 | Image decoding no longer gates sound / 图片解码慢时保留声音排程 |
| 2.4 s initial playout lead / 初始播放预缓冲 | Covers the accumulated lateness seen in original-strength long speech; adds 2.28 s versus the original 120 ms / 覆盖原强度长播报的累计迟到，比最初 120ms 多 2.28 秒播放等待 |
| High-resolution sender deadlines / 高精度发送计时 | Pace media against `perf_counter` / 以高精度时钟计算发送期限 |
| Audio-preserving viewer buffer / 保留音频的观看队列 | Strip stale queued pictures; keep sequence and every PCM sample / 省略积压旧图片，保留序号及全部声音 |
| Bounded decoder and viewer queues / 队列有界 | At most four pending image decodes and 125 queued server packets; excessively slow viewers disconnect / 最多四项图片解码、125 个服务端待发包，过慢连接断开重连 |
| Decode shortly before presentation / 临近播放再解图 | Hold compressed JPEGs during prebuffering, then decode about 120 ms before their deadlines / 预缓冲保存压缩 JPEG，临近播放约 120ms 再解码，避免积压数秒大位图 |
| Presentation-based FPS / 最终呈现统计 | Exposes received, drawn and presented counts, audio underruns, missing packets, and skipped pictures / 分开记录收包、绘制、呈现、缓冲耗尽、缺包及省略图片 |

These changes retain batch 8, FP16, the original face model, JPEG quality 86, 720×1280, the target 25 FPS and the full motion bank. A constrained connection can still receive fewer pictures; audio preservation does not manufacture bandwidth.

仍采用 batch 8、FP16、原人脸模型、JPEG 质量 86、720×1280、目标 25 FPS 与完整动作库。带宽受限时会省略图片以保留声音，这不保证任意网络仍有完整帧率。

An intermediate 320 ms buffer passed synthetic tests but still produced four to six scheduling gaps in some real long-speech samples, even with no missing sequences. The selected 2.4-second setting prioritizes continuity and is **additional playback latency**, not faster inference. Rebuffering is triggered only when the audio timeline has actually expired, with a small floating-point tolerance; the former early threshold could insert a pause while audio was still queued.

中间版本的 320ms 缓冲通过了模拟测试，但真实长播报某些样本仍有 4–6 次排程缺口，且没有缺包。最终采用 2.4 秒预缓冲优先保证连续性，**这是新增播放延迟，并非推理提速**。仅当音频时间线实际耗尽才重建缓冲，并保留浮点误差容限；提前触发会在仍有音频待播时人为插入等待。

## Verification / 验证

Five queue tests verify exact PCM preservation and ordering, independent fast/slow viewers, reader wakeup and bounded backlog. A native-browser regression feeds continuous synthetic audio while withholding arrivals for 200 ms or delaying each JPEG decode by 90 ms. Under slow decoding the old browser produced 23 scheduling gaps and 3.03 seconds of captured silence in one eight-second run; the corrected browser produced no scheduling gaps or captured silence in that sample. This is a controlled transport test, not a speech-naturalness assessment or a measurement of physical speakers.

五项队列测试验证逐样本音频保留、顺序、快慢观看端互不影响、等待唤醒及积压上限。浏览器压力测试连续输入测试音，模拟 200ms 到达抖动或每张图片解码 90ms；一次慢解码对照中，旧网页出现 23 次排程缺口及累计 3.03 秒捕获静音，修正网页该样本均为零。测试音结果不代表真人语音自然度或扬声器物理输出。

```powershell
python -X utf8 -B devtools/test_viewer_buffer.py
node devtools/check-playback.cjs --browser "<native-chrome-or-edge.exe>" --output "<report.json>"
```

Browser contexts are closed in `finally`. No Docker, WSL or VM is involved. The historical scenario MP4s and GIFs predate this playback correction and are not presented as new captures.

浏览器上下文在 `finally` 关闭，不使用 Docker／WSL／虚拟机。原五段 MP4 与 GIF 录制于本次修正之前，不将它们作为新版本录屏。

Final live and synthetic measurements, source hashes and intermediate failures are recorded in [playback evidence](evidence/playback-continuity.json). Live frame rates use final video presentation, and audio gaps are measured from the Web Audio schedule. Synthetic captured-audio checks are separate from physical speaker output.

最终实机与模拟数据、代码哈希以及中间失败样本见播放证据。实机帧率使用最终视频呈现，音频缺口来自 Web Audio 时间线；模拟测试另检查捕获的音频，不据此声称测量了扬声器物理输出。

| Final 60-second sample / 最终 60 秒样本 | Presented FPS / 呈现帧率 | Scheduled audio gaps / 音频缺口 | Missing whole packets / 整包缺失 | Longest presentation interval / 最大画面间隔 |
| --- | ---: | ---: | ---: | ---: |
| Chrome studio, long Echo / Chrome 演播台长稿 | 24.88 | 0 | 0 | 200.3 ms |
| Edge OBS page, multi-sentence cloud reply / Edge 云端多句回复 | 24.72 | 0 | 0 | 239.7 ms |

These samples preserved every PCM packet; the sender omitted 7 and 14 old pictures respectively while retaining their audio. They show improved audio continuity and typical frame cadence, with occasional remaining picture gaps. The evidence also includes a 25-second studio smoke test after adding the final stale-image decoding check; its source hash is recorded separately.

上述样本完整保留 PCM，发送端分别省略 7 和 14 张积压图片并保留其声音。声音连续性与通常画面节奏得到改善，仍有偶发画面间隔变大。证据另记录最后加入过期图片解码检查之后的 25 秒演播台复测，并分别保存代码哈希。

## Remaining limits / 仍有的限制

The existing JPEG/PCM path consumed about **31 Mbps per viewer** in initial samples. It has no H.264/Opus congestion control. Sustained low bandwidth can reduce picture cadence or force reconnection; a fixed buffer cannot mask an arbitrarily long stall. GPT-SoVITS still returns a complete WAV per text segment. One long test waited about 11.1 seconds for synthesis before speech started; synthesis wait and the 2.4-second initial playout lead are separate delays. Already delivered audio also delays the effect of interrupting speech. This setting favors smooth playback over subsecond conversation and immediate interruption. These bounded tests do not establish uninterrupted operation for an indefinite broadcast.

当前 JPEG／PCM 在初始样本中约占 **每观看端 31 Mbps**，没有 H.264／Opus 的拥塞控制。持续低带宽会减少画面或触发重连，固定缓冲无法覆盖任意长卡顿。TTS 仍为每段文字完整生成 WAV；一次长稿等待约 11.1 秒完成合成，合成等待与播放预缓冲是两项延迟。已经送到观看端的声音也会延后打断的生效。当前设置优先保证平稳观看，不作亚秒对话或即时打断承诺；有限时长测试不等于任意长直播无卡顿。

After updating an existing installation, activate the integration and restart the avatar service. Reload existing Chrome/Edge pages with **Ctrl+F5** so both sides understand audio-only packets. Debug counters are available as `window.studio.transport.metrics()` in the studio or `window.avatarTransport.metrics()` on `/obs.html`.

已有安装需应用集成并重启数字人服务，旧 Chrome／Edge 页面使用 **Ctrl+F5** 刷新，让发送端与网页同步支持纯音频包。控制台可通过上述接口查看诊断计数。
