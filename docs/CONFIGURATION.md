# Configuration / 配置参考

> Current voice / 当前语音：**O07 OmniVoice 主用，F07 F5-TTS v1 备用**。启动、切换、回退与新版验收以[新版手册](deployment/BASELINE_O07_F07.md)为准；本页旧MOSS记录/命令保留历史来源。Historical MOSS measurements are not new-release latency.

[Index / 导航](README.md) · [Deployment / 部署](DEPLOYMENT.md)

## Runtime files / 本地文件

| File / 文件 | Purpose / 作用 | In Git? / 是否入库 |
| --- | --- | --- |
| `configs/channel.env.example` | Blank template for your cloud channel / 渠道模板 | Yes / 是 |
| `configs/channel.env` | Real endpoint, key, model and system prompt / 实际渠道 | No / 否 |
| `configs/livetalking.yaml` | JSON-compatible YAML: avatar ID, TTS URL, reference WAV/text, batch, port / 人物运行设置 | No / 否 |
| `configs/resident-tts.example.json` / `configs/resident-tts.json` | O07/F07 worker paths, reference hash, steps and failure policy / 新版常驻语音模板与实际配置 | Template only / 仅模板 |
| `configs/tts-selection.private.json` | Persisted O07/F07 next-request selection / 下次请求的声线选择 | No / 否 |
| `configs/voices/female-a-o07-f07.json`, `configs/releases/current.json` | Approved synthetic reference, archived auditions and current release / 当前方案契约 | Yes / 是 |
| `configs/moss-live.example.json` / `configs/moss-live.json` | Portable template / private native MOSS paths and selected voice; see [MOSS live](MOSS_LIVE.md) / 模板与本机 MOSS 配置 | Template only / 仅模板 |
| `configs/tts-v2.yaml`, `tts-v2ProPlus.yaml` | Local TTS weights, CUDA device, half precision / 语音权重设置 | No / 否 |
| `configs/vertical/avatar-profile.json` | Baseline preparation profile, compact mask and bbox shift / 基准预处理规格 | Yes / 是 |
| `configs/vertical/materials/catalog.json`, `reviews.json`, `motion-index.json` | Reviewed selected assets and contiguous bank indices / 素材、审核和帧索引 | Yes / 是 |
| `configs/sources.lock.json`, `model-files.csv` | Upstream commit pins and reference download records / 源码固定版本及参考模型清单 | Yes / 是 |
| `.setup/`, `logs/`, `tools/obs/config/` | Machine state, source backups, runtime logs and OBS password / 设备状态、日志及 OBS 密码 | No / 否 |

## Environment variables / 环境变量

| Name | Meaning / 含义 |
| --- | --- |
| `AVATAR_LLM_BASE_URL` | Provider's OpenAI-compatible base URL, normally including its API prefix / 渠道 API 根地址 |
| `AVATAR_LLM_API_KEY` | Your private channel credential / 私有密钥 |
| `AVATAR_LLM_MODEL` | Exact model ID accepted by that provider / 渠道实际模型 ID |
| `AVATAR_LLM_PROTOCOL` | `chat_completions` (default) or `responses` / 请求协议 |
| `AVATAR_SYSTEM_PROMPT` | Single-line system prompt; default asks for short natural Chinese replies / 单行系统提示词 |
| `AVATAR_DOWNLOAD_PROXY` | Optional download-time proxy; not used for live media inference / 可选下载代理 |
| `AVATAR_BASE_URL` | Documentation capture target; default loopback on 8010 / 截图录制目标地址 |
| `CHROME_PATH` | Native Chrome executable for the capture script / 截图使用的 Chrome 路径 |

`scripts/runtime_environment.py` loads `AVATAR_*` entries from the ignored channel file and directs caches/temp files into the project. It strips inherited HTTP proxy settings and sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `AVATAR_GPU_ISOLATION=1`, and CPU thread limits. The cloud client still uses its explicit configured URL. The media runtime is not an installation downloader; missing weights should be fixed before starting it.

运行环境把缓存与临时文件定位在项目内，清除继承的 HTTP 代理，启用本地权重与 GPU 隔离。渠道文件里以 `AVATAR_` 开头的设置会载入；不要在其中添加不理解的内部开关。模型缺失应在准备阶段修复。

## Historical base versions and preparation / 原始基础环境与预处理

These pins describe the original GPT-SoVITS base. The current O07/F07 workers use separate existing native environments; do not merge their Torch/Transformers installations. See the [current runbook](deployment/BASELINE_O07_F07.md).

| Item / 项目 | Reference / 参考值 |
| --- | --- |
| Python inference environments | CPython 3.10 native Windows / Windows 原生 |
| Core CUDA packages | PyTorch 2.9.1 + cu128; torchvision 0.24.1; torchaudio 2.9.1 |
| Compatibility pins | NumPy 1.26.4; Transformers 4.51.3; Diffusers 0.35.1; OpenCV headless 4.11.0.86 |
| TTS decoder | TorchCodec 0.8.1 + FFmpeg 7.1.1 shared DLLs |
| Native face adapter | dlib-bin 20.0.1.post1 + face-recognition-models 0.3.0 |
| TTS used in recordings | GPT-SoVITS v2; v2ProPlus configuration is also prepared / 实录使用 v2 |
| Avatar | MuseTalk v1.5, `student_dorm_motion_bank_v3`, batch 8 |
| Face preparation | tracked full-resolution landmarks; bbox shift 4; median smoothing 5 frames; compact mask |
| Output / bank | 720×1280 / 25 FPS / 10,000 frames |
| Frame memory | 48 decoded images per FrameStore; CPU-resident latents / 每个缓存 48 帧 |
| OBS | Portable 31.1.2 / `Avatar Local` / scene `Avatar` |

Changing avatar ID alone is insufficient for a new person. Rebuild its coordinates, masks, latents and motion index from consistent source footage. Pose photographs are references, not direct substitutes for preprocessed video frames. Do not alter frame rate or source clip order without rebuilding the index and prepared bank.

更换人物不能只改 ID，需要重新准备整套一致的人脸坐标、蒙版、潜变量和动作索引。动作照片不能直接替换直播帧。修改源帧率或片段顺序后必须重建索引与人物库。

## Ports and access / 端口与访问

| Port / 端口 | Service / 服务 | Binding / 范围 |
| --- | --- | --- |
| 8010 | Studio HTTP + WebSocket + SSE | `0.0.0.0` after studio integration; trusted LAN/VPN only / 演播台集成后监听网卡 |
| 9880 | Current O07/F07 resident TTS broker / 当前串行语音调度 | `127.0.0.1` / 仅本机 |
| 9881 /9882 | O07 OmniVoice /F07 F5-TTS v1 isolated workers | `127.0.0.1` / 仅本机 |
| 3092 | A-side sole DSH/Humanity writer | `127.0.0.1` / 仅本机 |
| 8020 | B-side receiver; official material accesses B's own loopback | `127.0.0.1` / B本机 |
| 4457 | Project OBS WebSocket | Authenticated with a generated local password; restrict via firewall / 随机密码，需防火墙限制 |
| 8188 | Optional existing native ComfyUI for generation | Not started or installed by the live setup / 可选生成环境 |

The studio has no user authentication. Same-origin checks are not access control; the underlying upstream application also has administrative routes. Do not expose port 8010 directly to the public Internet. Protect any remote use with your existing network access controls. There is no tunneling service or published API credential in this repository.

网页没有登录鉴权，同源检查不能替代访问控制，上游还包含管理接口。仅在可信局域网或 VPN 使用；不要把 8010 直接映射公网。仓库不提供公网隧道或共享密钥。
