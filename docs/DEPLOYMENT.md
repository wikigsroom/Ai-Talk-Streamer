# Native Windows deployment / 原生 Windows 部署

[Index / 导航](README.md) · [Configuration / 配置](CONFIGURATION.md) · [Troubleshooting / 排障](TROUBLESHOOTING.md)

**Primary target / 后续主目标：** `remote-4090` / `REMOTE_4090_HOST`。Existing-installation migration, consistent private-state cutover and current readiness are documented in the [4090 runbook](deployment/RTX4090_MIGRATION.md). The generic fresh-install steps below also preserve the original GPT-SoVITS option; the selected MOSS04/DSH/Livehime runtime requires the additional stages in that runbook.

## Requirements / 环境

The reference machine is Windows x64, an RTX 4090 reporting **48 GB VRAM**, and **63.9 GiB usable host RAM**. A usual 24 GB RTX 4090 is a different capacity and is not the validated reference. Use an NVIDIA driver compatible with the CUDA 12.8 PyTorch wheels. The bootstrap command needs Git, a working Python 3.10+ and Internet access to GitHub, Hugging Face, PyPI, PyTorch and upstream data downloads.

参考机器是 Windows x64、**48 GB 显存的 4090**、约 63.9 GiB 可用内存；普通 24 GB 4090 不等同于本次验证环境。驱动需支持 CUDA 12.8 版 PyTorch。安装入口需要 Git、可运行的 Python 3.10+，以及上述下载站点的网络连通性。

Reserve 100 GB or more of free space as an installation/preprocessing allowance; it is not a measured minimum. PNG frames, masks, per-clip latents, package caches and source archives dominate disk growth. Use one NTFS volume: the bank assembler uses native hard links to reuse the prepared clip images. The installer uses native CPython `venv`; it never starts Docker, WSL or a VM.

建议预留至少 100 GB 空间作为规划余量，不能视为测得的最低需求。解码帧、蒙版、潜变量与安装缓存会占用较多空间。全部放在同一 NTFS 卷，动作库使用硬链接减少重复 PNG。这里的 Python venv 是原生进程环境，不涉及容器、WSL 或虚拟机。

## First installation / 首次安装

```powershell
git clone git@github.com:wikigsroom/Ai-Talk-Streamer.git
cd Ai-Talk-Streamer
python -X utf8 devtools/verify-repository.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup-Streamer.ps1 -PrepareAvatar
```

If `python` is not your bootstrap interpreter, pass `-Python 'C:\path\to\python.exe'`. An optional `AVATAR_DOWNLOAD_PROXY` configures your own download proxy; there is no built-in proxy address. Download configuration is separate from the offline media runtime.

如需指定入口解释器，增加 `-Python 'C:\path\to\python.exe'`。可通过 `AVATAR_DOWNLOAD_PROXY` 设置自己的下载代理；仓库不内置代理地址。运行时会清除代理变量并优先使用本地模型，不继承安装代理。

| Order / 顺序 | Script / 脚本 | Work / 作用 |
| --- | --- | --- |
| 1 | `deployment/bootstrap.py` | Fetch locked LiveTalking / GPT-SoVITS sources, native uv, MinGit, FFmpeg and OBS 31.1.2 / 下载上游源码及原生工具 |
| 2 | `deployment/download_models.py` | Download MuseTalk, VAE, Whisper and GPT-SoVITS resources; record checksums / 下载模型并记录校验 |
| 3 | `deployment/prepare_extras.py` | Fetch upstream demo video and reference voice / 获取安装验证素材与参考音频 |
| 4 | `deployment/prepare_environments.py` | Create two native Python 3.10 environments, PyTorch CUDA 12.8 and dependencies / 建立分离的口型、语音环境 |
| 5 | `deployment/configure_stack.py` | Patch Windows imports/TTS; write local configs and portrait OBS profile / 应用原生适配并生成配置 |
| 6 | `deployment/prepare_runtime_assets.py`, `prepare_ffmpeg7.py` | Decoder DLLs, language ID and offline text resources / 准备解码 DLL 和离线文本资源 |
| 7 | `deployment/configure_obs_runtime.py`, `activate_studio.py` | Configure portable OBS authentication and install web/GPU integration / 配置 OBS 与演播台集成 |
| 8 | `deployment/check_installation.py` | Dependency, CPU import, tokenizer, dictionary and decoder checks / 安装与本地资源检查 |
| 9 | Avatar stages below / 下列预处理阶段 | Build the supplied portrait bank, package materials and finalize records / 构建动作库与交付包 |

Source commits are in [sources.lock.json](../configs/sources.lock.json). Reference package freezes are [avatar](../configs/requirements-livetalking-verified.txt) and [TTS](../configs/requirements-tts-verified.txt). The installer pins core compatibility versions and resolves remaining dependencies; those freezes record the tested system, not a hermetic installer. Some tool releases and model revisions are discovered at installation time; compare new `.setup` records with [model-files.csv](../configs/model-files.csv). Model weights and programs are not embedded in this Git repository.

源码提交由 lock 文件固定；两个 verified requirements 是已验证环境的快照。安装器固定关键兼容版本，其余依赖仍会解析，并非完全封闭的可重复构建。部分工具或模型修订在安装时查询，需对照新的 `.setup` 记录和参考模型清单。仓库本身不含权重及安装好的程序。

## Avatar preparation / 人物预处理

`-PrepareAvatar` runs these stages using `deployment/run_avatar_stage.py`, which supplies the same local paths, decoder DLLs and offline environment as live inference:

```powershell
python -X utf8 deployment/run_avatar_stage.py compose_vertical_loop
python -X utf8 deployment/run_avatar_stage.py prepare_vertical_avatar
python -X utf8 deployment/run_avatar_stage.py prepare_motion_library
python -X utf8 deployment/run_avatar_stage.py assemble_motion_bank
python -X utf8 deployment/run_avatar_stage.py package_motion_materials
python -X utf8 deployment/run_avatar_stage.py finalize_preparation
```

The first stage joins the two bundled baseline videos into 16 seconds. The next prepares 400 baseline frames, then each selected 200-frame clip. Assembly produces `student_dorm_motion_bank_v3`: 50 clips / 10,000 frames with consistent coordinates, masks and latents. Its final config uses batch size 8. Packaging enables `/materials/download`.

第一步合并两个基准片段；随后预处理 400 帧基准与 48×200 帧新动作，再组成最终动作库并把配置切换到 v3，batch size 为 8。打包阶段生成素材 ZIP，供网页下载。

Preparation performs real GPU work. Close unrelated generation jobs first. Individual material preparation requests a 3 GiB process allocation limit; that is not a whole-stack minimum. Scripts preserve existing avatar directories and refuse destructive replacement. Resume from the failed stage after checking `.setup/vertical-material-prepared`, `.setup/material-preparation-progress.json` and `logs/`. Do not blindly rerun the whole setup over a customized, active installation: configuration stages regenerate local runtime files. Back up those files first.

预处理会实际占用 GPU。单素材阶段的 3 GiB 配额只限制该预处理进程，不代表全栈最低显存。脚本会拒绝覆盖已存在的人物目录。失败后查看日志和进度，从对应阶段恢复。完整 Setup 会重新生成运行配置，不宜直接覆盖正在使用的自定义安装；先备份本地配置。

## Start, OBS and shutdown / 启动与关闭

```powershell
.\Start-Streamer.cmd
# Or keep browser launching under your own control:
.\runtime\livetalking\Scripts\python.exe -X utf8 scripts\start_studio.py --no-browser
```

Open `http://127.0.0.1:8010/`, connect the preview and test Echo. Services start in TTS → avatar order. `start_studio.py` waits for ports; the browser's status and first decoded frame are the next readiness checks. The first viewer loads the shared avatar and may take longer than later connections.

依次启动语音与人物服务后，在浏览器连接预览并测试原文播报。启动脚本等待端口打开，不能代替页面就绪检查及首帧检查。首位观看者会触发共享人物加载，通常更慢。

```powershell
.\Avatar.cmd -Action start-obs
.\runtime\livetalking\Scripts\python.exe -X utf8 scripts\configure_vertical_obs.py
.\Avatar.cmd -Action status
# Stop recording / streaming in OBS before stopping services:
.\Avatar.cmd -Action stop
```

OBS uses the portable `Avatar Local` profile / collection. Vertical configuration refuses to alter an active recording or stream. Service shutdown checks project-owned executable paths and launch records. It does not close OBS or unrelated programs. Close unused preview tabs to release their decoding/audio work.

OBS 使用便携配置，竖屏设置脚本遇到正在录制或推流会退出。停止服务只处理本项目拥有的进程，不关闭 OBS 或其他应用。请先结束 OBS 输出，并关闭不用的预览页。

## Installation verification scope / 安装验证范围

The reference deployment has passed actual speech, live avatar, browser and OBS tests. This repository publication adds syntax, asset, documentation and media checks. A complete fresh download + GPU installation of the organized distribution has **not** been repeated; setup adaptations such as portable root paths are statically checked. Keep the stage records when reporting an installation issue.

参考实机已通过语音、口型、浏览器和 OBS 验证；本次发布另外检查语法、素材、文档与媒体。整理后的发行目录没有重新进行一次完整下载及全新 GPU 安装；路径可移植等整理改动经过静态检查。排障时请保留阶段记录。
