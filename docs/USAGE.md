# Studio usage and API / 演播台使用与接口

[Index / 导航](README.md) · [Configuration / 配置](CONFIGURATION.md)

## Browser workflow / 网页操作

Start the prepared workstation with `Start-Streamer.cmd`, then open `http://127.0.0.1:8010/`. For another device, replace loopback with your workstation's reachable address. Allow only your trusted LAN/VPN through the firewall. A webpage tab can view the same output as OBS; it does not get its own isolated conversation.

启动后打开本机地址；其他设备改用工作站的可达地址。网页与 OBS 共用一位人物和同一条播报队列，多人操作会相互影响。启用 DSH 时使用管理员登录和观众身份分区；人物画面仍共用同一输出。连接预览后，管理员需点“开始网页会话”，状态变为“会话进行中”才能发送。暂停后点“恢复网页会话”，结束时点“结束会话”。首次管理员令牌来自工作站的 configs/dsh-operator.token；可直接在演播台登录。

| UI label / 按钮 | Action / 行为 |
| --- | --- |
| 连接预览与声音 | Connect live picture/audio; first connection may load the avatar / 连接首帧及音频，首次可能较慢 |
| 开始网页会话 / 恢复网页会话 | DSH operator starts or resumes this session after preview connection / 登录管理员后开始或恢复当前场次 |
| 原文播报 → 发送播报 | Locally speak the text exactly; no LLM required / 本地朗读原文，不调用 LLM |
| AI 回复 → 发送播报 | Send text to the configured cloud channel, then locally speak its reply / 云端产生回复，本地合成与口型 |
| 停止说话 | Invalidate old generation and flush queued speech / 打断旧播报，已送达的缓冲可能短暂残留 |
| 自动编排 | Let speech state and clip order choose body footage / 按说话状态及调度节奏选动作 |
| 安静倾听 | Use quiet automatic categories / 采用待机、倾听和坐姿类别 |
| 动作选择 → 播放一次 | Queue one manual clip at the next clip boundary; latest pending selection wins / 当前动作结束后播放最后一次待播动作 |
| 录制并下载 | Start MediaRecorder; press again to finish and save WebM / 再次点击结束录制并保存音画 WebM |
| 断开预览 | Release this browser's socket and audio; shared OBS output continues / 释放本页连接与声音 |

Begin with 20–100 Chinese characters and one short sentence. The HTTP limit is 1–1,500 characters. Short segments improve time to first speech; a complete sentence is synthesized before its WAV is decoded. Body commands can wait for the remainder of an eight-second clip plus output buffers. The control label reflects the renderer's state and may lead the visible picture slightly.

建议先用 20–100 字短句测试。接口接受 1–1500 字；每段语音需要先得到完整 WAV。动作等待当前八秒片段剩余时间和音画缓冲，控制状态可能稍早于肉眼看到的画面。

## Your cloud channel / 自有 LLM 渠道

Expand **渠道设置**. Fill your OpenAI-compatible base URL, API key and the exact provider model ID. Choose `chat_completions` or `responses`, save, then select **AI 回复**. A display name is not sufficient to determine the API ID. The saved configuration is local; a blank key field keeps the previously stored key. To remove a key, edit the ignored `configs/channel.env` and restart the avatar service. The channel status endpoint returns `has_key`, never the key itself.

填写实际接口地址、密钥、模型 ID 和协议后保存，再切换 AI 回复。显示名称不能代替模型 ID；密钥框留空意味着保留旧值。要彻底清除，编辑本地配置并重启人物服务。状态接口只返回密钥是否存在，不回显密钥。

The integration sends the system prompt and the current message on each request. It does not retain conversation history. Only text goes to this configured LLM; local media inference uses the workstation. Model/provider latency and TTS latency both affect the first spoken reply.

每轮只发送系统提示词与当前消息，不保留聊天历史。人物图像、参考声音和音视频推理不发送给该 LLM。云端响应与本地语音合成均影响首音延迟。

## Material pages / 素材页面

| Route / 页面 | Content / 内容 |
| --- | --- |
| `/materials` | 48 reviewed gesture videos, category filtering, posters and source downloads / 已验收动作视频 |
| `/poses` | 28 independent pose photographs; native and 720×1280 versions / 独立动作参考照 |
| `/materials/download` | Full selected source package, created by `package_motion_materials` / 打包脚本生成的完整素材包 |
| `/tests` | Locally recorded five-scenario gallery when its manifest exists / 本机完成场景测试后显示五段录像 |
| `/tests/download` | Original scenario package after successful recording / 测试成功后的原始视频包 |

Repository previews are under [docs/media](media) and are available immediately after cloning. The original workstation's `/tests` contains its completed recordings; a fresh clone's live `/tests` is empty until you run the scenario recorder. See [Testing](TESTING.md).

克隆仓库后可直接查看文档媒体。参考工作站已有测试图库；新部署需运行测试脚本，才会生成本机 `/tests` 及原尺寸下载包。

## OBS output / 直播与录制

```powershell
.\Avatar.cmd -Action start-obs
.\runtime\livetalking\Scripts\python.exe -X utf8 scripts\configure_vertical_obs.py
```

Use profile/collection **Avatar Local**, scene **Avatar**, input **Avatar Browser**. The source is `http://127.0.0.1:8010/obs.html?v=vertical-1`. Source, base canvas and output should all be 720×1280, 25 FPS. Browser-source audio is rerouted into OBS and set to −3 dB by the vertical configuration script. Avoid monitoring the same audio twice through desktop audio.

使用项目专用配置，确认浏览器源、画布与输出均为 720×1280、25 FPS。声音由浏览器源送入 OBS，脚本将源设为 −3dB 留余量。避免同时采集桌面回放造成重音。

No stream starts automatically. Configure the platform destination in OBS yourself, preview sound/picture, then use OBS controls. Stop output before changing video settings. The scenario recorder waits for OBS's actual `OUTPUT_STOPPED` event before remuxing MKV to MP4; incomplete MP4 exports should be remuxed from a fully closed source file.

项目不会自动开播。请在 OBS 配置平台目的地并检查音画后手动开始。修改画布前结束输出；测试录制会等待文件真正关闭再封装 MP4。

## HTTP examples / 接口示例

Connect a browser preview or OBS first. The service uses one shared session called `studio`. JSON responses and errors use UTF-8. The same-origin check rejects a different browser `Origin`; it is not user authentication.

```powershell
$AvatarBase='http://127.0.0.1:8010'
Invoke-RestMethod "$AvatarBase/api/studio/status"
$AvatarBody=@{text='你好，欢迎来到直播间。';mode='echo';interrupt=$true} | ConvertTo-Json
Invoke-RestMethod "$AvatarBase/api/studio/speak" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($AvatarBody))
Invoke-RestMethod "$AvatarBase/api/studio/motion" -Method Post -ContentType 'application/json' -Body '{"id":"m01_welcome_right_wave"}'
Invoke-RestMethod "$AvatarBase/api/studio/interrupt" -Method Post -ContentType 'application/json' -Body '{}'
```

| Method | Path | Payload / result / 请求及返回 |
| --- | --- | --- |
| GET | `/api/studio/status` | TTS readiness, speaking state, GPU snapshot, viewer count, active avatar, masked channel state / 状态与资源快照 |
| GET / POST | `/api/studio/channel` | `base_url`, `api_key`, `model`, `protocol`, `system_prompt`; GET omits the secret / 渠道读取与保存 |
| POST | `/api/studio/speak` | `text`, `mode` (`echo`/`chat`), optional `interrupt` default true; returns request ID / 播报请求 |
| POST | `/api/studio/interrupt` | Empty object; advances generation and flushes speech / 打断 |
| GET / POST | `/api/studio/motion` | GET state/clips; POST `id`, `auto` or `calm` / 动作状态及控制 |
| GET | `/api/studio/stream` | Binary WebSocket JPEG + PCM / 实时音画 |
| GET | `/sse?sessionid=studio` | Speech/reply/error events after the shared session exists / 共享人物事件 |
| GET | `/api/studio/materials`, `/api/studio/poses`, `/api/studio/tests` | Selected gallery manifests / 图库清单 |

`speak` returns 409 when no viewer is connected, 400 for an empty/oversized text or unconfigured chat channel. Motion requests return 409 before the avatar exists and 400 for unknown IDs. Successful submission is not proof of successful synthesis; use events and actual audio/video to verify. The older `/api/studio/assets/portrait` upload is a legacy horizontal-image helper and does **not** rebuild or activate a vertical avatar.

提交成功只代表进入处理，不代表已经出声。请结合事件、音频能量和实际播放判断。旧的 portrait 上传接口服务于早期横屏素材，不会重建或切换当前竖屏人物。
