# Materials and regeneration / 素材与重建

当前角色与场景归档为 **女A · 林知夏 / 知夏的日光宿舍**。分类归档、CSV 清单和下载方式见[角色档案](CHARACTERS.md)。

The paired character and scene use registry **female-a**. See the [character archive](CHARACTERS.md) for identity, categories, hashes and the downloadable snapshot.

[Index / 导航](README.md) · [Architecture / 架构](ARCHITECTURE.md)

## Included inventory / 已包含素材

| Kind / 类别 | Count / 数量 | Location / 位置 | Meaning / 含义 |
| --- | ---: | --- | --- |
| Selected H3 gesture videos / 新动作视频 | 48 × 8 s | `outputs/vertical/materials/*.mp4` | 384 s, six categories × eight, 48 distinct SHA-256 values / 独立生成并选用 |
| Baseline clips / 基准视频 | 2 × 8 s | `outputs/vertical/source/idle_a.mp4`, `idle_b.mp4` | Original 16-second comparison baseline / 原始基准 |
| Final bank index / 最终索引 | 50 clips | `configs/vertical/materials/motion-index.json` | 400 s / 10,000 frames after preparation / 预处理后的整体索引 |
| Independent pose photographs / 独立动作照 | 28 | `output/imagegen/motion-poses/` | Native generated images and prompts / 原生尺寸与提示词 |
| Pose delivery versions / 动作照适配版 | 28 | `assets/vertical/pose-references/` | 720×1280 derivatives; not another 28 generations / 不重复计数 |
| Posters / 缩略图 | 48 | `outputs/vertical/materials/posters/` | Browsable 180×320 previews / 网页预览 |
| Selected keyframes / 动作关键帧 | 48 | `outputs/vertical/materials/keyframes/` | One frame per accepted video / 每段抽取一帧 |
| Review sheets / 审核接触表 | Selected + rejected takes | `outputs/vertical/materials/review/` | Full-frame and available hand/head detail sheets / 全画幅及部分手脸细节 |
| Workflows / 工作流 | 48 selected + baseline variants | `configs/vertical/` | API JSON, prompts and selected execution history / 参数、提示词与执行记录 |
| Character / scene references / 角色场景参考 | Included reference set | `output/imagegen/`, `assets/vertical/` | Original image, portrait reference, background and final portrait anchor / 原图及竖屏锚点 |

The expansion is **48 ÷ 2 = 24× by clip count** and **384 ÷ 16 = 24× by duration**. Including the two old clips gives 50 / 400 s, or 25× total. There are performance/left-right variants; this is not a claim of 48 distinct action concepts. Posters, extracted frames, crops and resizes do not count as independent materials.

The bundled baseline files retain their native 736×1312 / 24 FPS / 192-frame generation format. `compose_vertical_loop.py` converts and joins them into the 720×1280 / 25 FPS / 400-frame preparation input. Their source checksums are in [baseline-media.json](../configs/vertical/baseline-media.json).

扩充量以两段共 16 秒为基准：新增片段和时长均为 24 倍；含旧素材的总量是 25 倍。左右手和表演变体属于独立视频，并不等于 48 种完全不同的动作概念。抽帧、裁切和缩放不算新增生成。

两个基准源文件保留 736×1312、24 FPS、192 帧的生成规格，合并脚本会转换为直播预处理所需的 720×1280、25 FPS、400 帧。

The pose delivery manifest lists 28 accepted originals from a larger review batch. Eight original video takes were rejected and replaced by `take2` versions. `reviews.json` retains these rejection decisions; the active catalog and package use only the selected takes. Review checks sampled frames and later live behavior, not automated anatomical certification of every frame.

28 张动作照来自较大的生成审核批次；8 段首版视频经复核被 take2 替换。审核记录保留拒绝理由，当前清单只指向已选版本。抽帧检查和后续实时播放验证不等于逐帧自动手指解剖检测。

## Use existing materials / 使用现成素材

No image or H3 service is needed to rebuild the delivered live bank. Follow [Deployment](DEPLOYMENT.md). The installer creates the 16-second baseline, prepares the 48 selected clips and assembles the bank. Source files are immutable inputs; preprocessing products live under ignored `src/LiveTalking/data/avatars/` and `.setup`.

使用现成视频即可重建直播人物，无需再调图像或视频 API。源视频是输入；解码帧、坐标、蒙版和潜变量放在不入库的上游人物目录。更改源视频必须重新审核和准备，不能沿用旧的预处理成功记录。

The local package command is:

```powershell
python -X utf8 deployment/run_avatar_stage.py package_motion_materials
```

It validates selected video uniqueness and pose hashes, then writes `outputs/vertical/portrait-motion-materials.zip` and its delivery manifest. ZIPs are ignored by Git to avoid duplicating all media. Video hashes in [delivery-manifest.json](../outputs/vertical/materials/delivery-manifest.json) and photo hashes in [pose delivery.json](../output/imagegen/motion-poses/delivery.json) are checked by `devtools/verify-repository.py`.

打包会检查视频哈希唯一性和动作照校验值，ZIP 不提交 Git。仓库验证脚本也会核对选用视频、照片原件及适配版的 SHA-256。

## Optional local H3 generation / 可选本地再生成

The original image was edited through the selected image gateway during design. The 48 body clips were generated locally on the reference GPU using an existing native ComfyUI H3 installation. The live installer does **not** install H3 or a second ComfyUI. This optional environment is unnecessary for playback or real-time lips.

人物图在设计时通过图像渠道编辑；身体片段由参考 GPU 上已有的原生 ComfyUI/H3 本地生成。直播安装脚本不附带安装 H3/ComfyUI，它们也不是使用现成动作库的必要依赖。

| Workflow dependency / 工作流依赖 | Recorded choice / 已记录选择 |
| --- | --- |
| UNet | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` |
| Selected turbo LoRA | `minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors` |
| Sampling | Euler, simple, 4 steps, video sigma shift 12 / audio shift 3 |
| Generation | 736×1312, 192 frames / 24 FPS / 8 seconds |
| Delivery | Scale/crop to 720×1280; convert to 25 FPS / 200 frames |
| Nodes | Native H3 nodes (`MiniMaxH3TurboLoRA`, `MiniMaxH3SigmaShift`, `MiniMaxH3ImageToVideo`), standard sampling/VAE nodes, `JWImageLoadRGB`, `JWSaveImageSequence` |

The supplied API graphs record the working node interface and model filenames. Custom-node versions and H3 weights are external dependencies, not a self-contained generation installer; use a compatible native installation and check its `/object_info` before submitting. Model licenses are separate from this repository. Do not substitute a cloud video workflow if local computation is required.

工作流记录的是已运行的节点接口与模型名，不是完整的视频生成安装包。可选再生成需准备接口兼容的原生节点和模型，先检查 ComfyUI 的 `/object_info`。H3 权重许可独立于本项目；如要求本地计算，不应换成云端生视频。

All public API graphs/history use `${PROJECT_ROOT}` in place of private absolute project paths. Expand a graph into ignored local state before manual dispatch:

```powershell
python -X utf8 devtools/materialize-workflow.py configs/vertical/materials/m01_welcome_right_wave.api.json .setup/local-wave.api.json
```

`scripts/generate_motion_library.py` also expands that placeholder. It targets local ComfyUI on 8188, submits one item at a time, writes generation state and contact sheets, and releases models only when the queue is empty. Already reviewed video files are reused. Create new IDs and new output paths for a new revision, clear its acceptance state, and inspect full-body/head/hand motion before marking it accepted. Do not reuse an old preparation-success marker after changing a take.

再生成脚本只向本机 8188 提交，并顺序执行、记录状态、制作接触表；已有已审核文件会复用。新版本使用新 ID 与新输出路径，取消旧的通过状态，检查全身、手部与脸部后再验收，禁止沿用不匹配的成功标记。

The published execution records are path-redacted copies for inspection. Their JSON bytes differ from private originals because of path redaction; source image/video bytes and their media hashes are unchanged. Rejected raw frames, private API requests, full decoded banks, model weights and workstation control files are not included.

公开执行记录经过路径脱敏，因此 JSON 字节不与私有原件一致；源图、源视频及媒体哈希保持不变。拒绝素材的原始帧、私有 API 请求、整套解码人物库、权重及设备控制文件均不提交。
