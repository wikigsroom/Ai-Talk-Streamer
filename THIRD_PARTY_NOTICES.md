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
| FFmpeg builds | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), [GyanD/codexffmpeg](https://github.com/GyanD/codexffmpeg), licenses of the selected GPL/shared builds | Separate encoding tools and runtime decoder DLLs / 编解码工具及 DLL |
| Python, uv, PyTorch and libraries | Their upstream licenses, retained in installed distributions / 安装分发中的上游许可 | Native inference environments / 原生运行依赖 |
| H3 / ComfyUI generation stack | External model/node licenses; not included in live setup / 外部模型与节点许可 | Optional local preparation of new body footage / 可选本地视频准备 |

The locked application source commits are in [sources.lock.json](configs/sources.lock.json). The license-inspection commits for standalone MuseTalk and CosyVoice are recorded in [docs/licenses/sources.json](docs/licenses/sources.json); those are license provenance, not a claim that the live stack checks out those two repositories. Downloaded model/resource revisions and reference hashes are in [model-files.csv](configs/model-files.csv).

应用源码固定提交与许可证取证提交用途不同，不应混淆。MuseTalk/CosyVoice 的许可证取证版本不代表直播安装会单独检出这两个版本；模型资源的修订和哈希见清单。

## Weights and reference voice / 权重与参考声音

MuseTalk weights, Stable Diffusion VAE, Whisper features, GPT-SoVITS weights, Chinese BERT/HuBERT, FastText and text resources are downloaded from their respective upstreams. Their model cards, dataset and resource terms apply independently; code-license labels alone do not establish all model or data rights. `sha256_upstream` is populated only where such a digest was provided; local hashes are reference checksums, not independent legal or origin certification.

模型卡、数据和资源条款独立适用，不能用代码的许可证标签推导所有权重或数据权限。清单仅在上游提供时记录其哈希，本地哈希用于一致性核验。

The demonstration speech uses an upstream demo reference, not a voice newly recorded or trained for the fictional student. Keep the upstream attribution and review applicable voice/model terms when replacing or publishing a production voice. This repository makes no claim of exclusive rights to that voice and provides no real-person impersonation endorsement.

演示声音采用上游示例参考，并非专为角色录制或训练的声音。用于正式直播时需保留来源说明，并审查实际参考音色及模型条款。本仓库不主张该声音的独占权。

## Demonstration media / 演示媒体

The character is a fictional **22-year-old adult** in a daylight dorm. Reference/pose images were generated or edited through the selected image gateway during design. Body clips were generated locally using H3. Actual browser and OBS recordings demonstrate the integrated system and contain the demonstration synthesized voice. Prompts, selected takes, review decisions and media hashes are included for traceability.

角色设定为虚构的 22 岁成年人。人物与动作照片通过图像渠道生成/编辑，身体视频由本地 H3 生成，网页及 OBS 实录包含示例合成声音。仓库保留提示词、选用版本、审核与哈希；上游或服务条款仍各自适用，不提供对所有素材用途的统一商业授权保证。

Modified upstream behavior is documented in [Architecture](docs/ARCHITECTURE.md) and implemented explicitly by the deployment patch scripts. Preserve this notice and applicable upstream licenses when redistributing those components.
