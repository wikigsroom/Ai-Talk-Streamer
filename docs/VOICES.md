# 女A 音色选型 / Voice casting

[中文说明](#中文说明) · [English](#english) · [女A档案 / Character](CHARACTERS.md) · [音频清单 / Inventory](../assets/voices/female-a-v1/inventory.csv)

## 中文说明

本批为**女A·林知夏**制作了 **10 款独立参考说话人的中文女声**，每款分别使用 **MOSS 与 SoulX** 生成，01 号另附 FireRed 对照，共 **21 段实际合成样片：MOSS 10、SoulX 10、FireRed 1**。使用 RTX 3080 10 GB / 64 GB 内存上的原生 Windows ComfyUI；模型推理全部在本机完成。形象仍为原来的白天宿舍女A。

打开运行中演播台的 **`/voices.html?v=2`**，或下载 `female-a-voice-selection-v2.zip` 后打开 `web/voices.html`，即可离线试听。页面默认展示 **MOSS 10 款**，支持切换到 **SoulX 10 款**、同号跨模型对照、单段播放、暂停、拖动、原速/变速试听、音量、WAV 下载、候选保存和 JSON 导出。页面与截图均使用实际生成音频；CSS/JS 版本号用于更新上一版的浏览器缓存。

**这是一批音色选型素材。** 加入候选、导出或改变播放速度不会修改运行中的直播引擎。现有实时直播仍使用 GPT-SoVITS；把 SoulX / MOSS / FireRed 接到实时链路，需要实现并验证 TTS 适配器、排队/打断、分句、采样率与延迟。本次没有把它们标成已经验收的实时方案。

另外提供 `female-a-moss-10-v2.zip`：仅包含 MOSS 的十款 WAV、原始 FLAC、对应参考声、实际工作流与清单，方便单独评选。 / A separate MOSS-only ZIP contains ten MOSS clips, their raw FLACs, references, workflows and inventory.

### 如何比较

[桌面页面截图](media/voice-selection-desktop.png) · [手机页面截图](media/voice-selection-mobile.png) · [浏览器验证记录](evidence/voice-selection-browser.json)

[逐款 MOSS / SoulX 对照表与音频链接](VOICE_COMPARISON.md)列出十组同号试听、完整音频时长和实测耗时。

所有样片使用相同台词：

> 你好，我是林知夏。欢迎来到直播间，今天过得怎么样？别着急，我们慢慢聊。

先用原速、相同音量试听 MOSS 的 10 款；每张卡片可直接播放同号 SoulX 对照，也可切换模型查看其完整 10 款。两种模型的同号音色使用完全相同的参考 WAV、逐字稿与合成台词。下方对照表可选择 01–10；01 有三个模型，其余有 MOSS 与 SoulX 两个模型。候选导出区分**模型＋音色编号**，例如 MOSS 02 与 SoulX 02 可以同时加入，不能只按编号覆盖。FireRed 当前仅有 01 对照，没有声称已生成十款。

同号的风格名称固定为选角方向，并非人工听感评级；两种模型可能呈现不同听感。卡片上的基频来自各自实际音频的粗略自相关估计；它不能衡量自然度、年轻感或说话人身份。参考源有台湾普通话口音，音色克隆可能保留口音。源说话人的年龄没有提供，不能将角色年龄当作声源年龄。

### 实测配置与耗时

| 模型 | 实际使用配置 | 首段音频 | 本批首段总耗时 |
| --- | --- | ---: | ---: |
| MOSS-TTSD-v1.0 | LLM NF4 4-bit、BF16 计算，codec FP32 CPU | 8.08 秒 | 176.726 秒 |
| FireRedTTS2 | LLM BF16，codec FP32 CUDA | 5.28 秒 | 132.500 秒 |
| SoulX-Podcast-1.7B | 完整 LLM BF16、Flow FP32，HF 引擎 | 7.60 秒 | 36.287 秒 |

SoulX 其余九款在模型缓存已加载时，总耗时约 12–17 秒/款，具体值在清单。上述总耗时包含加载、轮询、可能排队及回传，**不是纯模型推理时延或首包时延**。这只是本机、本次短台词的测量，不能据此保证长文本或实时口型并发性能。MOSS 的量化配置来自设备上已验证的工作流；它不能描述为全精度 8B 推理。

测试时先暂停本项目的 GPT-SoVITS 与人像服务，避免 10 GB 显存竞争。MOSS 使用设备已有的原生 ComfyUI 节点与配置逐款生成，保留逐款加载与执行记录；SoulX 复用加载器。生成结束后卸载 ComfyUI 模型缓存并恢复原直播服务。没有使用 Docker、WSL 或虚拟化环境。

### 修改播报内容

当前直播：在演播台的文本框输入文字，选择原文播报；AI 模式则让配置好的云端 LLM 产生文字。新音色素材：在 ComfyUI API 工作流中改 `dialogue_script`（SoulX）或 `dialogue_text`（MOSS/FireRed），保留 `[S1]` 说话人标记。不要把参考文本改成待合成文本。

已有三个模型和对应自定义节点的原生 ComfyUI 可复用下列命令：

```powershell
python scripts/render-voice-selection.py --base-url http://127.0.0.1:8188 --voice v02 --engine soulx --text "你好，我是林知夏，今天想聊什么？" --output outputs/voices/my-line.flac
python scripts/render-voice-selection.py --base-url http://127.0.0.1:8188 --voice v02 --engine moss --text "你好，我是林知夏。" --output outputs/voices/my-moss-line.flac
python scripts/render-voice-selection.py --base-url http://127.0.0.1:8188 --voice v02 --engine firered --text "你好，我是林知夏。" --output outputs/voices/my-fire-line.flac
```

控制端需要 `requests`；音频母带脚本需要 `numpy` 和 PATH 中的原生 FFmpeg。以上命令只提交自己的任务到队尾，不会卸载模型或取消别人的任务。若直播与 ComfyUI 共用 10 GB 显卡，应先停止本项目 GPU 服务。工作流依赖设备已有的 `PodcastTrioNative`、`SoulXPodcastLoader`、`SoulXPodcastInputParser`、`SoulXPodcastGenerate` 和标准音频节点；仓库不捆绑节点安装、模型权重或一个全新安装验收。

### 修改音色

每款参考声在 `assets/voices/female-a-v1/references/v01.wav` 至 `v10.wav`。精确逐字稿在 [references.json](../assets/voices/female-a-v1/references.json)，授权与源文件记录在 [REAL_VOICE_SOURCES.md](../assets/voices/female-a-v1/REAL_VOICE_SOURCES.md)。

替换音色时同时替换**参考音频与逐字稿**：SoulX 为 `S1_prompt_audio` 与 JSON 中 `prompt_text`；MOSS/FireRed 为 `S1_audio` 与 `S1_text`。推荐干净单说话人、无背景音乐、5–15 秒参考音，逐字稿必须与音频一致。不要通过改音高把同一声源包装成十位说话人。

如果选择继续用当前低延迟 GPT-SoVITS，可在 `configs/livetalking.yaml` 设置 `REF_FILE`（参考 WAV 的本机路径）与 `REF_TEXT`（对应逐字稿），重启本项目人像服务使默认配置生效。现有适配器也读取逐条消息中的 `tts.ref_file` / `tts.ref_text`，但当前网页未提供这两个字段。这里的参考声可以复用，**GPT-SoVITS 的合成结果不会与 SoulX 样片完全相同，必须重新试听验收**。

### 修改语速、音量和音频文件

试听页的速度控件使用浏览器保持音高的播放变速，只影响试听，不修改模型或下载文件。音量控件同样只影响播放。正式输出可使用 GPT-SoVITS `/tts` 的 `speed_factor`，或对生成后的文件做适度音频处理；改参考说话人才能改变主要音色。

本批将原始 FLAC 保留在 `outputs/voices/female-a-v1/`；供试听的 WAV 在 `web/voice-audio/female-a-v1/`，24 kHz 单声道 PCM16。母带目标 -20 LUFS、真峰值不高于 -2 dBTP，保留自然长度与停顿，不拉速、不补长度、不改音高或共振峰。处理实现见 [voice_audio.py](../scripts/voice_audio.py)。例如仅改文件音量：

```powershell
ffmpeg -i input.wav -af "volume=0.85" -c:a pcm_s16le quieter.wav
```

### 验证与文件体系

完整解码、时长保持、非静音、零削波、响度与真峰值检查，以及已有离线 Whisper-small 的 CPU 转写，保存在 [voice-audio-quality.json](evidence/voice-audio-quality.json)。自动转写会把“林知夏”写成同音字；原始转写与字错率均保留，未将其伪装成人工盲听、MOS 评分或逐字无误认证。

已有 CAM++ 模型在 CPU 上分别对十款 MOSS、十款 SoulX 音频与全部十条参考做相似度比较，**两组各有 10/10 的最近参考对应自己的登记声源**，见 [MOSS 记录](evidence/voice-speakers-moss.json)与 [SoulX 记录](evidence/voice-speakers.json)。这是声纹相似度检查，不是自然度、年轻感或身份概率评分；复验脚本为 [verify-voice-speakers.py](../scripts/verify-voice-speakers.py)，通过 `--engine MOSS` 或 `--engine SoulX` 选择音频，复用 ComfyUI 中的 `campplus.onnx`、ONNX Runtime、PyTorch、Torchaudio 和 SoundFile，不下载模型。

| 文件 | 用途 |
| --- | --- |
| `web/voices.html`、`voices.css`、`voices.js` | 可联网部署，也可从下载包离线打开的试听页 |
| `web/voice-audio/female-a-v1/*.wav` | 21 段统一响度的完整试听，文件名包含模型与音色编号 |
| `outputs/voices/female-a-v1/*.flac` | 未做母带的原始 ComfyUI 结果 |
| `assets/voices/female-a-v1/` | 十位参考说话人、精确逐字稿、来源、清单 |
| `configs/voices/workflows/*.api.json` | 21 次真实生成的 API 工作流 |
| `configs/voices/female-a-v1.json` | 页面数据、音色、音频哈希、参数、转写 |
| `scripts/render-voice-selection.py` | 在已有 ComfyUI 上重生成任意一句台词 |
| `scripts/build-voice-selection.py` | 从生成记录与检查结果重建页面和 ZIP |
| `docs/media/voice-selection-*.png` | 实际页面的桌面、手机截图 |
| `docs/evidence/voice-selection-browser.json` | 真实播放、候选保存、导出与页面验证 |

仓库已保留生成音频与检查记录，可在克隆后直接运行 `python scripts/build-voice-selection.py` 重建页面、对照表和 V2 ZIP，无需再次占用 GPU。若有新生成结果，传入 `--records` 与 `--quality-dir`；构建器会验证样片数量、模型覆盖和音频哈希，不能把缺失的 MOSS 样片作为完整批次发布。 / Rebuild the page and bundle from the published catalog with the same command; GPU inference is not required for packaging.

源记录来自本地已登记的 [Clean Common Voice zh-TW 数据集](https://huggingface.co/datasets/OKHand/Clean_Common_Voice_Speech_24.0-TW)，CC0-1.0；十个不同匿名 speaker/client ID 均保留可追溯哈希。源数据给出的 predicted MOS 仅用于筛选参考录音，不是本次生成音频评分。模型遵循各自上游条款：[SoulX](https://github.com/Soul-AILab/SoulX-Podcast)、[MOSS](https://github.com/OpenMOSS/MOSS-TTSD)、[FireRed](https://github.com/FireRedTeam/FireRedTTS2)。

## English

This release contains **ten distinct registered female reference speakers**, each rendered with **both MOSS and SoulX**, plus FireRed for voice 01: **21 real clips — MOSS 10, SoulX 10, FireRed 1**. Everything ran in native Windows ComfyUI on the existing RTX 3080 10 GB / 64 GB workstation. No cloud TTS, Docker, WSL or virtualization was used. The avatar remains **female-A / Lin Zhixia** in her approved daylight dorm.

Open **`/voices.html?v=2`** on the running studio, or extract the V2 delivery ZIP and open `web/voices.html`. **Ten MOSS clips are shown by default**; switch to SoulX for its ten clips or use each card's same-reference comparison button. The comparison table can select reference 01–10. Voice 01 has three models; all others have two. Shortlist export retains both model and reference ID, including the same reference chosen with two engines. The page also supports seeking, pitch-preserving audition speed, volume and WAV download. It is a casting page: **shortlisting does not switch the live avatar's TTS engine**. Live GPT-SoVITS remains active until a selected voice and the required adapter have been tested.

All clips use exactly the same Chinese greeting. The three model comparisons use exactly the same voice-01 reference audio and transcript. MOSS used NF4 4-bit LLM weights with BF16 computation and a CPU FP32 codec; FireRed used a BF16 LLM and CUDA FP32 codec; SoulX used the full BF16 LLM with FP32 Flow. The table above records actual first-case wall time, including loading/polling/transfer; warm SoulX cases took roughly 12–17 seconds. These are not first-chunk latency measurements or a guarantee of concurrent real-time video performance.

Change spoken content with `dialogue_script` / `dialogue_text`; change timbre by replacing **both the reference WAV and its exact transcript**. The portable render commands above reuse installed models/nodes and submit only their own jobs. They require `requests`; mastering requires `numpy` and native FFmpeg. For current GPT-SoVITS defaults, set `REF_FILE` and `REF_TEXT` in `configs/livetalking.yaml` and restart the avatar service. Reusing a reference with another engine requires another audition: synthesis will differ.

The browser's speed/volume controls affect audition playback only. Mastered audio is 24 kHz mono PCM16, targeted to -20 LUFS / -2 dBTP, without pitch/formant shifts, duration forcing or omitted endings. Complete original FLACs are preserved. Checks cover full decoding, natural duration, non-silence, clipping, loudness and offline CPU Whisper transcription; transcripts and normalized character error rates are retained. **No human MOS or blind listening score is claimed.** Model and reference-source links are listed above. Style labels describe casting directions, source ages are unknown, and the zh-TW source may preserve its accent.

The inventory, source registration, full API graphs, audio hashes, page screenshots and browser evidence are included alongside the clips. Model weights, private device addresses, channel credentials and a fresh model/node installation are outside this distribution.

The existing CPU CAM++ checkpoint compared each generated MOSS and SoulX voice against all ten registered references: **10/10 nearest-reference matches for each engine**. Complete cosine tables are preserved in `docs/evidence/voice-speakers-moss.json` and `docs/evidence/voice-speakers.json`. Select an engine with `--engine MOSS` or `--engine SoulX` when repeating the check. This is an approximate speaker-similarity check, not a perceptual-quality or identity-probability score.
