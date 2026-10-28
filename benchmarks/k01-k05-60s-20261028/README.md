# 女A局部口型横评代码 / Female-A local lip-sync benchmark

本目录归档 K01–K05 同源60秒测试的原生 Windows 集成代码。它是离线横评入口；线上 O07/F07、唯一 DSH 写入端和 B3080 官方直播姬的配置继续由现有定型手册管理。

This directory archives the native Windows integration used for five same-input60-second recordings. It is an offline experiment, separate from the production A4090/B3080 release. Actual results belong to the dated report; successful environment preparation is not evidence of a completed recording.

[本轮完整实测、原片与音频 / Completed results and original media](../../docs/analysis/lipsync-k01-k05-20261028/ARCHIVE.md)：五组均通过文件验收；口型质量问题和共享负载边界在报告中单列。完整生成RTF均大于1，不能把单独网络段耗时当成当前实时直播能力。

## 固定方案 / Selected configurations

| 编号 | 实际实现 | 说明 |
|---|---|---|
| K01 | MuseTalk1.5 / FP16 / batch8 | 既有网络与生产融合口罩 |
| K02 | 相同 MuseTalk 网络 / FP16 / batch8 | 下半脸融合、有限颜色校正和静音渐变；未使用TensorRT |
| K03 | FeatherTalk144 / FP32 / batch16 | 独立动作和台词的合成教师初训60轮；上游推理加载时执行重参数化 |
| K04 | 原 Wav2Lip GAN96 / FP32 / batch16 | 原始网络严格加载GAN权重；复用既有人脸坐标 |
| K05 | LatentSync1.6 /512/FP16/16帧/20DDIM/CFG1.5 | 原模型强度；dlib几何、原PNG分块读写、VAE批次切片和60秒尾块适配 |

每组保持女A/林知夏、日光宿舍、同一组手部和身体动作。共用16kHz PCM WAV，720×1280、25FPS、1,500帧；不变速、不截断测试台词。K03训练素材与测试动作分开，但教师标签来自K01，不能代表真人实拍训练的效果上限。详细边界和指标口径见 [RUNBOOK.md](RUNBOOK.md)。

All five variants preserve the source body, hands and background. Shared-load timings, cold-load boundaries and native execution adaptations are part of the result, not evidence of exclusive-GPU performance or live-stream response latency.

## 文件组织 / Code map

| 环节 | 文件 |
|---|---|
| 公共数据、Unicode图像I/O、编码与采样 | `bench_common.py` |
| 固定音频与动作清单 | `prepare_audio.py` |
| 原生环境、固定源码和下载哈希 | `download-plan.json`、`bootstrap.py`、`prepare_environments.py`、`link_shared_runtime.py` |
| 原GAN网络来源校验 | `prepare_wav2lip_source.py` |
| 三个通用/基准入口 | `render_muse.py`、`render_wav2lip.py`、`render_latent_bounded.py` |
| K03教师、预处理、训练及推理 | `prepare_training.py`、`preprocess_assets.py`、`landmark_cpu_batch.py`、`train_feather.py`、`render_feather.py` |
| 真实数据与显存容量诊断 | `audit_training_data.py`、`probe_feather_memory.py`、`preflight.py` |
| 任务调度、原生文件锁与专用日志 | `run_suite.py`、`bench_launch.py` |
| 失败训练证据归档与续训成本 | `archive_failed_training.py`、`K03/training-attempts.json`、`K03/training-invocations.json`（后两项在交付结果目录） |
| 完整视频、音频及局部替换边界验证 | `validate_outputs.py`、`export_source_evidence.py` |
| 原始数据、HTML文档、图表及比较素材 | `build_report.py`、`render_report.py`、`plot_all.py`、`make_final_assets.py` |
| 交互页面与只读HTTP Range服务 | `compare.html`、`range_http.py`、`serve_remote_review.py` |
| 哈希清单与本机同步 | `make_delivery_manifest.py`、`sync_deliverables.py` |
| 按原始字节归档完整测评 | `archive_review_bundle.py`；结果目录用`-text`保留换行与SHA256 |
| 原生Chrome页面验收 | `review_page.cjs` |
| Windows占用回归与最终观察发布 | `verify_atomic_progress.py`、`refresh_review_server.py`、`publish_review.py` |
| 网页起播事件诊断 | `probe_viewer_startup.cjs`；`--after`独立保留修复后轨迹 |

`render_latent.py`保留上游整段视频pipeline调用，用于另行对照；本次正式K05使用有界驻留入口。CPU预处理与环境修复辅助脚本记录当时的实现，不应把历史临时wheel服务器当成仍可用的安装服务。

## 部署到既有参考环境 / Use the reference installation

本次参考运行根目录是 `C:\dev\虚拟数字人直播`，代码运行位置是其下的 `operations\k01-k05-60s-20261028`；Git检出在 `Ai-Talk-Streamer` 子目录。先将本目录的代码复制到上述operations目录，保留同级文件结构。已有角色、音色、源码、模型和原生环境是运行前置条件；本归档不宣称已在空白系统重跑完整安装。

The measured reference uses an existing production installation and two isolated native Python environments. Model weights, upstream checkouts, the10,000-frame avatar bank and Python packages are installed separately and are not committed here. Do not replace production package versions to satisfy this experiment.

```powershell
$LipTaskRoot = 'C:\dev\虚拟数字人直播'
$LipTaskCode = Join-Path $LipTaskRoot 'operations\k01-k05-60s-20261028'
& "$LipTaskRoot\runtime\livetalking\Scripts\python.exe" -X utf8 -B "$LipTaskCode\prepare_wav2lip_source.py"
& "$LipTaskRoot\runtime\livetalking\Scripts\python.exe" -X utf8 -B "$LipTaskCode\bench_launch.py" run_suite.py
```

`run_suite.py`跳过已经成功的阶段，保留失败证据，并用任务内GPU锁串行运行模型。资源不足时只等待或释放本进程未用CUDA缓存；不重启MCP、ComfyUI、设备，也不取消其他项目。K03续训保持原始训练格式；预览和原始成绩不会因为评分操作而被覆盖。

实际执行分别在23轮、56轮检查点后因Windows进度文件替换被拒绝而中断。第一次增加重试，第二次将临时进度写入与正式成绩区分：进度受阻时保留后备快照并继续训练，检查点和成绩仍严格写入。小JSON先读入内存再传输，并且只重载本实验网页服务；未重启MCP或模型服务。真实Win32共享锁与慢HTTP读取回归检查通过。原失败资源与耗时独立归档；每次恢复模型、优化器和轮次，随机种子重新设为20261028。上游检查点未保存全部随机数状态，因此不宣称逐位等同于不间断训练。The recorded resumes preserve completedepochs and model/optimizer state; they are not a bit-identical uninterrupted run. All failed-stage costs remain visible separately.

上述命令是本次既有结果目录的续跑入口。首次独立复现还需先完成：原生环境与权重校验、共用音频/动作清单、K01/K02、K03教师素材及预处理，以及K03 native12和K05 resident两项容量探针。主suite不会把缺少的容量证据当作已通过，也不会自动补跑K01/K02。对新的实验使用独立run-ID并同步调整固定路径，避免覆盖已归档的测量；精确对比可复用交付的共用WAV和动作清单，免去TTS随机差异。

首次准备须使用 `download-plan.json` 的固定revision、长度与SHA256；FeatherTalk预处理权重随其固定源码安装，VGG19仅用于训练损失。`prepare_wav2lip_source.py`固定两个Git blob，避免模型结构随上游分支移动；它不下载权重。预处理缓存、原始训练帧、训练检查点和最终推理权重分开统计。

## 观看与验证 / Review

参考结果目录：`outputs\lipsync-k01-k05-60s-20261028`。A端只读页面为 `http://192.168.196.209:8035/`，本机接收副本为 `http://127.0.0.1:8037/`。交付目录自带 `viewer_server.py`，只需Python3.10+，默认仅监听loopback；复制整个目录即可独立观看，无需GPU或第三方Python包。

页面可选择两组同步播放、放大嘴部、按生成耗时/RTF/显存排序，并按实际台词定位。个人评分独立保存在浏览器，不写回测评数据。完整原视频、原始音频、逐秒资源、验证记录和PNG来源抽样均在独立输出目录；不生成PDF或压缩包。

For the native browser check, set `AI_TALK_STREAMER_REPO` if the checkout cannot be discovered; `AI_TALK_BENCHMARK_OUTPUT` selects the received results folder. `AI_TALK_CHROME_PATH` can select an installed native Chrome executable. The check creates a fresh headless context and always closes its browser; it never closes the user's existing tabs.

本机与A4090入口的最终17项检查均通过，五组均验证了未暂停时的实际时钟推进。初次检查暴露了视频先播放、音轨后启动及seek误判缓冲的竞态；修复为同轮并发起播、取消过期播放请求、避免重复seek，并保留原失败和5秒前后事件轨迹。完整文件检查独立于网页短时播放；原始视频和性能成绩未因播放器修复重新生成。Both final17-check receipts and the original startup failure are included in the dated report. Test browsers are closed in`finally`.

## 上游来源 / Attribution

- [MuseTalk](https://github.com/TMElyralab/MuseTalk) and [LiveTalking](https://github.com/lipku/LiveTalking): existing baseline, features and avatar cache.
- [FeatherTalk fixed source](https://github.com/anliyuan/FeatherTalk/tree/7a8bb0439eb5da5e10601168df329a7052b7edf3): Apache-2.0 code; keep component/model conditions separate.
- [Wav2Lip](https://github.com/Rudrabha/Wav2Lip#disclaimer): original model source/public weights have personal/research/non-commercial conditions; no claim of commercial production approval.
- [LatentSync fixed source](https://github.com/bytedance/LatentSync/tree/a229c3948406bc2cf6eaf4873e662e70c6a04746): Apache-2.0 code; [fixed1.6 weights](https://huggingface.co/ByteDance/LatentSync-1.6/tree/c42c7e6c8e9c213626389fa7d9a3c444b8536353), existing VAE and dlib landmark assets are recorded separately.

The project's integration license does not replace these upstream terms. This code archive contains no model binaries, MCP credentials, cloud keys, account cookies, signed download URLs or private DSH state. Historical reports remain unchanged.
