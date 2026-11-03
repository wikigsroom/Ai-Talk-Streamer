# Third-party notices / 上游来源与许可

The root [Apache-2.0 license](LICENSE) covers the project's original integration and documentation. It does not override the terms of upstream code, downloaded weights, reference voices, dependencies or generated-media services. The installer downloads upstream programs separately; it does not place their binaries in this Git repository.

根目录 Apache-2.0 许可覆盖本项目原创集成与文档，不改变上游代码、权重、参考声音、依赖或生成服务的原有条款。程序与权重通过部署脚本另行下载，未提交至本仓库。

| Component / 组件 | Source and terms / 来源及条款 | Use / 用途 |
| --- | --- | --- |
| LiveTalking | [lipku/LiveTalking](https://github.com/lipku/LiveTalking), [Apache-2.0 text](docs/licenses/LiveTalking.txt) | Local avatar application patched by deployment scripts / 本地人物应用及补丁 |
| MuseTalk | [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk), [MIT plus bundled component notices](docs/licenses/MuseTalk.txt) | Lip generation and associated preprocessing; runtime copy is vendored in locked LiveTalking / 口型及预处理 |
| GPT-SoVITS | [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS), [MIT text](docs/licenses/GPT-SoVITS.txt) | Local speech synthesis / 本地语音合成 |
| CosyVoice demo resource | [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice), [Apache-2.0 text](docs/licenses/CosyVoice.txt) | Upstream `asset/zero_shot_prompt.wav` and transcript used as the demonstration TTS reference / 示例参考音频及文本 |
| OBS Studio | [obsproject/obs-studio](https://github.com/obsproject/obs-studio), upstream license | Separately downloaded portable capture/stream application / 单独下载的录制推流软件 |
| blivedm 1.1.7 | [xfgryujk/blivedm](https://github.com/xfgryujk/blivedm), MIT; pinned `3bf17fe862b8c2fc6bc04c81c3f0c5db95de93d6` | Separately installed CPU-only Bilibili Web comment adapter; upstream LICENSE retained in its installation / 独立安装的 B站 Web 弹幕接入 |
| Playwright Core 1.59.1 | [microsoft/playwright](https://github.com/microsoft/playwright), Apache-2.0 | Isolated native Chrome/Edge comment collection and browser tests / 独立本机浏览器采集与验收 |
| Douyin Live Companion | [Official download](https://streamingtool.douyin.com/), proprietary upstream terms | Separately obtained broadcaster client, not redistributed as project source / 官方主播客户端，单独下载，不作为本项目源码再分发 |
| Bilibili Livehime 8.11.1.11202 | [Official download](https://live.bilibili.com/liveHime), proprietary upstream terms; installer and extracted executable signatures checked | Current Bilibili browser-material, audio and encoding client; separately downloaded, no client binaries redistributed / 当前 B站官方客户端，单独下载并验签，不分发程序 |
| Inno Setup Unpacker 2.70.1 | [Upstream distribution and source](https://github.com/jrathlev/InnoUnpacker-Windows-GUI/tree/07ee3b1a05a26fa27a0efe110fe78dfa72c06c71/innounp-2); console package `innounp.htm` states GNU GPL with embedded component notices | Pinned project-local unpacking tool; the separate GUI’s MIT license does not replace console/component terms / 控制台包声明 GNU GPL，保留包内条款，不提交二进制 |
| 7-Zip 26.05 | [Official downloads](https://www.7-zip.org/download.html), upstream LGPL/BSD/unRAR notices | Project-local client extraction only; downloaded binary and retained license files are not committed / 仅用于项目内解包，程序及许可保留在下载目录 |
| FFmpeg builds | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), [GyanD/codexffmpeg](https://github.com/GyanD/codexffmpeg), licenses of the selected GPL/shared builds | Separate encoding tools and runtime decoder DLLs / 编解码工具及 DLL |
| Python, uv, PyTorch and libraries | Their upstream licenses, retained in installed distributions / 安装分发中的上游许可 | Native inference environments / 原生运行依赖 |
| H3 / ComfyUI generation stack | External model/node licenses; not included in live setup / 外部模型与节点许可 | Optional local preparation of new body footage / 可选本地视频准备 |
| SoulX-Podcast, MOSS-TTSD, FireRedTTS2 | [SoulX](https://github.com/Soul-AILab/SoulX-Podcast), [MOSS](https://github.com/OpenMOSS/MOSS-TTSD), [FireRed](https://github.com/FireRedTeam/FireRedTTS2); respective upstream model/code terms | Existing native ComfyUI engines used for voice auditions; weights are not redistributed / 试听生成，不分发权重 |
| OmniVoice | [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice), Apache-2.0 code; [pretrained model](https://huggingface.co/k2-fsa/OmniVoice), CC-BY-NC-4.0 | Current O07 local TTS; weights are not redistributed / 当前主用语音，不分发权重 |
| F5-TTS v1 | [SWivid/F5-TTS](https://github.com/SWivid/F5-TTS), MIT code; pretrained weights CC-BY-NC-4.0 | F07 local backup, EMA checkpoint and local Vocos / 备用语音 |
| O07 synthetic reference | [Voice provenance and digests](configs/voices/female-a-o07-f07.json) | OmniVoice-generated reference reused by O07 and F07; no newly sourced real-person voice / 共用合成参考 |
| Common Voice zh-TW references | [Registered local source and CC0-1.0 provenance](assets/voices/female-a-v1/REAL_VOICE_SOURCES.md) | Ten different anonymous reference speakers for female-A casting / 女A十位独立参考说话人 |

The locked application source commits are in [sources.lock.json](configs/sources.lock.json). The license-inspection commits for standalone MuseTalk and CosyVoice are recorded in [docs/licenses/sources.json](docs/licenses/sources.json); those are license provenance, not a claim that the live stack checks out those two repositories. Downloaded model/resource revisions and reference hashes are in [model-files.csv](configs/model-files.csv).

应用源码固定提交与许可证取证提交用途不同，不应混淆。MuseTalk/CosyVoice 的许可证取证版本不代表直播安装会单独检出这两个版本；模型资源的修订和哈希见清单。

## Current O07 / F07 voice pair

The O07 reference and the two auditions in `assets/voices/female-a-o07/` are synthetic audio generated in the separate 2026-10-28 casting task. F07 clones that same reference. See the [current runbook](docs/deployment/BASELINE_O07_F07.md). The pretrained model terms apply independently of the integration and code licenses. Earlier MOSS/SoulX/GPT-SoVITS recordings retain their own reference provenance.

O07/F07为本次合成参考及两款试听，不使用新真人录音。两套所用预训练权重的CC-BY-NC条款与代码许可分开适用。旧演示声音的来源说明继续保留。

## Weights and reference voice / 权重与参考声音

MuseTalk weights, Stable Diffusion VAE, Whisper features, GPT-SoVITS weights, Chinese BERT/HuBERT, FastText and text resources are downloaded from their respective upstreams. Their model cards, dataset and resource terms apply independently; code-license labels alone do not establish all model or data rights. `sha256_upstream` is populated only where such a digest was provided; local hashes are reference checksums, not independent legal or origin certification.

模型卡、数据和资源条款独立适用，不能用代码的许可证标签推导所有权重或数据权限。清单仅在上游提供时记录其哈希，本地哈希用于一致性核验。

The demonstration speech uses an upstream demo reference, not a voice newly recorded or trained for the fictional student. Keep the upstream attribution and review applicable voice/model terms when replacing or publishing a production voice. This repository makes no claim of exclusive rights to that voice and provides no real-person impersonation endorsement.

演示声音采用上游示例参考，并非专为角色录制或训练的声音。用于正式直播时需保留来源说明，并审查实际参考音色及模型条款。本仓库不主张该声音的独占权。

## Demonstration media / 演示媒体

The character is a fictional **22-year-old adult** in a daylight dorm. Reference/pose images were generated or edited through the selected image gateway during design. Body clips were generated locally using H3. Actual browser and OBS recordings demonstrate the integrated system and contain the demonstration synthesized voice. Prompts, selected takes, review decisions and media hashes are included for traceability.

角色设定为虚构的 22 岁成年人。人物与动作照片通过图像渠道生成/编辑，身体视频由本地 H3 生成，网页及 OBS 实录包含示例合成声音。仓库保留提示词、选用版本、审核与哈希；上游或服务条款仍各自适用，不提供对所有素材用途的统一商业授权保证。

Modified upstream behavior is documented in [Architecture](docs/ARCHITECTURE.md) and implemented explicitly by the deployment patch scripts. Preserve this notice and applicable upstream licenses when redistributing those components.

Native Minecraft dependency preparation uses [PortableMC 4.4.1](https://pypi.org/project/portablemc/4.4.1/) as a version resolver, with its original upstream GPLv3 license retained inside the pinned wheel. The project wrapper installs dependencies without calling its game runner or creating an offline player identity. The exact wheel, metadata, Fabric libraries and Fabric API hashes are in [the client dependency lock](configs/mc-client.lock.json). Minecraft client/assets and the Mojang-provided Java runtime are retrieved from their upstream endpoints; the public source package contains the wrapper and lock, and does not redistribute those game/runtime binaries. Fabric Loader and Fabric API retain their respective upstream licenses. See [Fabric installation](https://fabricmc.net/use/installer/).

原生MC依赖准备使用固定版PortableMC解析版本及平台依赖，并保留原轮子中的上游许可；不调用其游戏启动器或生成离线玩家身份。公开源码包不包含游戏、Java、音效或材质二进制。安装依赖、已能游玩和完整主播应用验收分别记录。


## Mindcraft item-goal planner native port

Mindcraft, MIT license, commit `e1c1fc3ffa481506c2445fc639e16dba504b5920`. The native port embeds the upstream item dependency solver with dependency-injected imports. Original files, source hashes and full MIT license are preserved in `backend/game/mindcraft/upstream/` and `upstream.lock.json`. Execution uses this application's same-player native adapter; it does not run the complete upstream Mineflayer client or upstream generated code.
