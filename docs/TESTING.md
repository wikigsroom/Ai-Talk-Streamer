# Validation and evidence / 测试与证据

[Index / 导航](README.md) · [Gallery / 展示](GALLERY.md)

## Selected MOSS 04 / 当前 MOSS 04

The current 3080 MOSS configuration passed all five actual browser cases: shared audition text, novel text, cancellation, recovery and a configured cloud reply. See [the configuration, latency and limits](MOSS_LIVE.md), [browser evidence](evidence/moss-live-browser.json) and [720×1280 recording with audio](media/moss-04-live-demo.mp4). The older OBS recordings below retain their original TTS voices. / 当前 MOSS 04 的五项网页实测均通过，详见专项文档、证据和带声音的竖屏录像；下方较早的 OBS 录像仍保留原语音引擎。

## Scenario recordings

These five recordings were captured from the **actual live OBS scene**, using the accepted daylight dorm character and local TTS/MuseTalk. The inputs are prepared Echo scripts, not five cloud-generated answers. Each test gates gestures on actual speech, takes an OBS screenshot, checks audio/video, waits for the recording-stopped event and remuxes the closed recording. The published previews preserve the full duration and audio, resized from 720×1280 to 432×768 for GitHub.

以下五段均来自实际 OBS 直播场景，采用本地语音与口型；测试内容是原文播报脚本，不能当成五次云端问答。每段检查实际说话状态、动作、截图、音轨和尺寸，等待录像真正结束再转封装。仓库预览保留完整时长及声音，尺寸缩为 432×768；参考原件为 720×1280。

| Case / 情境 | Duration / 时长 | Verified behavior / 验证内容 | Full preview / 完整预览 |
| --- | ---: | --- | --- |
| 01 Welcome / 开场欢迎 | 25.44 s | Speech with a hand wave / 招手与播报 | [MP4](media/s01_welcome.mp4) |
| 02 Explanation / 内容讲解 | 48.68 s | Two speech phases, palm presentation and emphasis / 连续两段、摊掌及强调 | [MP4](media/s02_explain.mp4) |
| 03 Listen then reply / 聆听后回应 | 36.44 s | Quiet listening followed by a prepared spoken answer / 安静倾听后朗读回应 | [MP4](media/s03_listen_reply.mp4) |
| 04 Interrupt and resume / 打断后恢复 | 46.40 s | Speech → stop → checked quiet window → new speech / 停止、静音窗口及新播报 | [MP4](media/s04_interrupt_resume.mp4) |
| 05 Closing / 结束告别 | 60.28 s | Thanks, bow/hand movements and goodbye / 致谢、收尾动作与告别 | [MP4](media/s05_closing.mp4) |
| **Total / 总计** | **217.24 s** | **5 passed / 全部通过** | [Evidence / 证据](evidence/scenarios.json) |

![Interruption and resumption excerpt / 打断与恢复节选](media/interrupt-resume.gif)

The interruption test measures a quiet audio window in the recording; it does not establish a universal network-to-silence latency. Body clips continue while voice is stopped. Scenario JSON contains original file hashes; resized documentation MP4s have separate hashes in the media manifest.

打断用例检查录像中的静音窗口，不代表所有网络环境下的停止延迟承诺。停止语音时身体动作继续。场景证据记录原片哈希，文档压缩版的哈希另见媒体清单。

## Reference acceptance / 参考实机验收

| Check / 检查 | Result / 结果 | Evidence / 证据 |
| --- | --- | --- |
| Browser functional acceptance / 网页功能 | 17 checks passed: portrait stream, actual speech, manual action, recorder download, shared OBS, interrupt, mobile layout, reconnect, cleanup and galleries / 17 项通过 | [browser-acceptance.json](evidence/browser-acceptance.json) |
| Configured cloud LLM / 实际云端问答 | One successful configured-channel request; 14.723 s first text / 16.541 s first speech / 单次实测 | [cloud-conversation.json](evidence/cloud-conversation.json) |
| New material provenance / 新素材来源 | 48 distinct videos, 384 seconds, selected workflows/media verified / 已核验 | [material-provenance.json](evidence/material-provenance.json) |
| Full live motion tour / 完整动作巡检 | 48 selections over 407.68 s; 30 speaking screenshots, 18 quiet / 全部手动选播 | [motion-tour.json](evidence/motion-tour.json) |
| Delivery archive checks / 交付包 | Material ZIP and five-test ZIP passed CRC and media hash checks / CRC 与媒体哈希通过 | [package-verification.json](evidence/package-verification.json) |
| Publication captures / 本次文档实录 | Six screenshots, actual browser response, loaded gallery thumbnails / 真实页面与响应 | [capture manifest](media/capture-manifest.json), [gallery manifest](media/gallery-capture-manifest.json) |

The cloud test replied “欢迎来到直播间！今天想聊点什么？” through the user's existing channel. Provider address, key and private model-channel configuration are not published. Echo observations include 5.281 s to speech in one browser run and 14.734 s in another OBS run. These are individual warm measurements, not a latency distribution or promised SLA.

云端测试使用已有渠道并成功回复上述文本，但不公开渠道地址、密钥或私有配置。原文播报单次实测为 5.281 秒及另一次 14.734 秒，不能理解为稳定延迟或性能分位数。

Generation/validation monitoring sampled every ten seconds: observed maxima were 44,955 MiB VRAM (43.90 GiB) and 58.841 GiB host RAM. These include co-running host usage and can miss short spikes. After unloading generation models, the final live snapshot was about 12,574 MiB VRAM (12.28 GiB) and 15.97 GiB host RAM. Browser captures observed roughly 23–25 FPS at particular moments; the configured target is 25 FPS. These figures do not prove suitability for an ordinary 24 GB card or more simultaneous avatars.

[Resource sampling evidence](evidence/resource-summary.json) · [Historical live snapshot](evidence/runtime-snapshot.json)

生成与验证阶段十秒采样的峰值包括机器其他负载，也可能漏掉瞬时峰值。卸载生成模型后，直播快照降到约 12.28 GiB 显存及 15.97 GiB 内存。瞬间帧率不等于持续吞吐保证，也不能据此证明 24GB 卡或多人物可用。

## Repeat the checks / 复验方法

Repository-only checks require no model downloads or GPU:

```powershell
python -X utf8 devtools/verify-repository.py
python -m unittest discover -s tests -v
# With native ffprobe on PATH, also inspect every supplied video:
python -X utf8 devtools/verify-repository.py --media
```

The verifier checks Python syntax, JSON, local Markdown links, pinned sources, selected video/photo hashes, contiguous 10,000-frame indices, safe publication paths and media provenance. The 18 unit tests exercise blending, whole-clip scheduling, MOSS audio tails, cancellation, stale requests, engine identity, complete cloud replies and safe service startup/shutdown. The hosted CI runs repository checks; it does not claim a GPU end-to-end test.

验证脚本检查语法、JSON、文档链接、锁定源码、素材哈希、连续帧索引和公开文件边界。单元测试覆盖调度边界、最后待播请求与安静/说话选取。CI 不执行 GPU 端到端测试。

To record the five scenarios again, start the prepared studio, open its portable OBS scene, ensure no other recording/stream is active, then run:

```powershell
.\runtime\livetalking\Scripts\python.exe -X utf8 scripts\record_scenario_tests.py
```

The script creates `outputs/vertical/scenarios/manifest.json`, five MP4s/screenshots, detailed results and a ZIP. It reuses matching successful scenario outputs. To force a new complete run, preserve the old scenario directory under another name first. It leaves an existing active OBS output untouched. Once completed, `/tests` and `/tests/download` show this machine's original results.

脚本会复用符合脚本指纹和哈希的成功结果；若要完全重录，先把旧测试目录另存。遇到其他录制或推流会退出。完成后网页显示本机原尺寸结果。

For the exhaustive gesture tour, use `scripts/record_motion_tour.py` with the same idle OBS prerequisites. For documentation captures:

```powershell
npm ci
$env:AVATAR_BASE_URL='http://127.0.0.1:8010'
npm run capture
# Re-capture only galleries, including off-screen images:
node devtools/capture-studio.cjs --gallery-only
```

The capture script owns its Chrome context and closes pages/context in `finally`. It actually submits speech, so use an idle studio. Its browser screen recording has no audio track; the separate OBS videos contain speech. Capture tools are development dependencies, not live inference dependencies.

截图脚本会真实提交播报，请在空闲演播台运行。它关闭自己创建的页面与浏览器上下文。网页屏幕录像不带音轨，OBS 场景视频带声音；这些工具不参与直播推理。

## Scope and limitations / 验证边界

The five scenarios are five **interaction situations in the same accepted dorm**, not five different physical backgrounds. Visual review confirms sampled hand/body consistency, not every frame's anatomy or perfect phoneme alignment. MuseTalk's 256-pixel generation can soften teeth/lips. No long-duration soak test, large viewer-load test, public Internet deployment or new clean GPU installation has been performed for this publication. Evidence JSON is curated/path-redacted; its source-record hash is included where available.

五段测试是同一宿舍里的五种使用情境，不是五处不同背景。没有进行长时间稳定性、大规模观看压力、公网部署或本次全新安装测试。素材逐帧解剖与音素级同步也不在自动验收范围。证据 JSON 经筛选脱敏，保留原记录哈希以便追溯。
