# Troubleshooting / 常见问题

[Index / 导航](README.md) · [Deployment / 部署](DEPLOYMENT.md)

| Symptom / 现象 | Check and action / 检查与处理 |
| --- | --- |
| Setup download fails / 下载失败 | Inspect `.setup/bootstrap.events.jsonl`, model results and the failing URL. Check your network or set your own `AVATAR_DOWNLOAD_PROXY`; do not replace downloaded errors with fake success records. / 查看具体下载记录，不伪造完成状态。 |
| Existing source lock mismatch / 上游源码版本不匹配 | Preserve the customized directory and install in a new project directory. The bootstrap refuses to claim an unverified source tree matches its lock. / 保留旧目录，另建安装，不直接覆盖。 |
| Port opens but page not ready / 端口通但服务未就绪 | Read `logs/tts.runtime.*.log` and `avatar.runtime.*.log`. Port listening is not full model readiness. / 查看语音与人物日志。 |
| First connection takes a long time / 首次预览慢 | The first viewer loads avatar metadata and starts the isolated GPU worker. Keep one connection, watch logs, and avoid repeatedly reopening tabs. / 首个观看连接需加载资源，不要不断开新页。 |
| 409 when sending / 发送返回 409 | Connect preview or OBS first. `/api/studio/speak` requires an actual viewer. / 先连接预览或 OBS。 |
| No sound / 没声音 | Click the connect control to unlock browser audio, check OS/browser mute and OBS source meters. Echo should work without any LLM key. / 点击连接解锁音频，检查静音和音量表。 |
| AI mode fails / AI 回复失败 | Check exact base URL, API protocol, provider model ID and key. Confirm the channel accepts streaming. A display name is not an API ID. / 核对地址、协议、实际模型 ID、密钥及流式支持。 |
| Reply forgets previous turns / 无多轮记忆 | Current requests include only the system prompt and current message. Persistent history is not implemented. / 当前尚未实现历史上下文。 |
| Gesture appears late / 动作延迟出现 | Commands wait for the current clip boundary; controller state can lead buffered output. Wait the remaining clip plus buffering. / 等待当前片段结束及缓冲。 |
| A new gesture replaces an old pending one / 待播动作被替换 | This is intentional latest-request behavior, not a queued playlist. / 设计为最后一次待播请求，不是动作播放列表。 |
| Mouth is soft or haloed / 嘴部模糊或接缝 | Compare the original source frame with the live result. MuseTalk generates a 256-pixel region. The delivered bank uses bbox shift 4 and a compact mask; changing one setting without rebuilding aligned assets can worsen it. / 对照原片，保持预处理一致。 |
| RAM/VRAM pressure / 内存或显存高 | Release idle generation models, close unused viewers, keep CPU latents and 48-entry FrameStore active. Do not decode the whole bank eagerly. Do not terminate unrelated jobs. / 释放生成模型、关闭无用观看页，不一次加载全库。 |
| `avcodec-61.dll` / TorchCodec error | Verify `tools/ffmpeg7-shared` contains the shared DLLs and launch via the runtime environment helper. A standalone `ffmpeg.exe` does not provide decoder DLLs. / 检查共享 DLL 与 PATH，不只检查可执行文件。 |
| Offline tokenizer/dictionary missing / 离线文本资源缺失 | Run the failed preparation/resource stage and `deployment/check_installation.py`. Check project-local NLTK, FastText and OpenJTalk resources. / 补齐资源后再启动推理。 |
| OBS image is horizontal or cropped / OBS 横屏或裁切 | Stop output and run `configure_vertical_obs.py`. Check source, canvas, output and transforms are all portrait. / 停止输出后重新配置竖屏。 |
| OBS audio repeats / OBS 重音 | Avoid capturing browser playback again as desktop audio; use the rerouted browser-source audio once. / 避免重复采集同一声音。 |
| MP4 cannot open / MP4 无法播放 | Stop OBS fully; wait for `OUTPUT_STOPPED`, then remux the closed MKV using native FFmpeg. Keep the original MKV until playback is verified. / 等文件关闭后再封装，保留原件。 |
| `/materials/download` returns 404 / 素材包不存在 | Run `python -X utf8 deployment/run_avatar_stage.py package_motion_materials`. ZIP is generated locally, not checked into Git. / 本机重新打包。 |
| Fresh `/tests` is empty / 新安装测试页空白 | Repository previews are in `docs/media`; record scenarios to produce this installation's runtime manifest and original downloads. / 文档预览可直接看，运行测试后填充本机图库。 |
| A preparation directory already exists / 已有人物准备目录 | Inspect its result and source hashes; preserve it. Use a new avatar ID for a new revision. / 核验后保留，新版本用新 ID。 |
| Optional ComfyUI node missing / 可选生成节点缺失 | H3 generation is a separate native dependency. Compare `/object_info` with the graph's node names. Existing clips need no ComfyUI. / 现有片段不依赖生成环境。 |

When sharing an issue, include the stage name, relevant package versions, GPU/RAM capacity, error tail and sanitized result JSON. Remove endpoint credentials, OBS password, host/user identifiers and full private paths. Do not upload `channel.env`, raw control records or the entire `.setup` directory.

提交问题时提供阶段、版本、硬件容量、必要错误尾部与脱敏结果。删除渠道密钥、OBS 密码、设备信息和私有绝对路径，不要上传整套 `.setup` 或控制记录。
