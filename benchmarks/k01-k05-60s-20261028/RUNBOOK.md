# K01–K05 同源60秒口型横评 / Native benchmark runbook

本实验保留女A/林知夏、日光宿舍、既有动作、O07声音和720×1280画布，只比较局部口型模块。生产配置、DSH状态、平台账号、B3080接收端均不修改，不启动公共直播。结果目录与历史测评分开。

This benchmark preserves the selected female-A identity, daylight dorm, existing portrait motion and O07 speech. It replaces only the local speech-driven facial module. It does not change production, start a public stream, create a second memory writer, or measure audience CDN latency.

## Paths and native execution

| Purpose | Path on A4090 |
|---|---|
| Project root | `C:\dev\虚拟数字人直播` |
| Isolated task code | `operations\k01-k05-60s-20261028` |
| Results | `outputs\lipsync-k01-k05-60s-20261028` |
| Model files | `models\lipsync-benchmark` |
| Pinned upstream source | `src\lipsync-benchmark` |
| Native isolated Python 3.10 | `runtime\lipsync-benchmark\feather`, `runtime\lipsync-benchmark\latent` |
| Existing Torch library, read only | `runtime\livetalking\Lib\site-packages` |
| Existing avatar | `src\LiveTalking\data\avatars\student_dorm_motion_bank_v3` |

No Docker, WSL, virtual machine or Linux container is used. The two native venvs override their own packages and append the existing production package directory through an ASCII `.pth` file. `--system-site-packages` alone does not inherit a parent venv's Torch. The runtime link is checked in `runtime-link.json`; production packages must never be uninstalled or downgraded.

The static review server at `http://192.168.196.209:8035/` supports byte ranges. Local review uses `http://127.0.0.1:8037/`. These are read-only file servers, not remote command APIs. Do not expose private configuration, MCP records or credentials through them.

## Fixed IDs and actual configurations

| ID | Implementation | Required qualification |
|---|---|---|
| K01 | Existing MuseTalk1.5, FP16, batch8, production mask | The baseline includes original frame/mask reads and blending |
| K02 | The same network/weights, bounded lower-face blend, median color correction, silence crossfade | A postprocessing ablation, not a separate model or TensorRT result |
| K03 | FeatherTalk144, FP32, batch16; 60-epoch identity model | A synthetic-teacher pilot, not a real-human training quality ceiling |
| K04 | Original Wav2Lip GAN96, FP32, batch16, original mel conditioning | The original network must strictly match the checkpoint; research-use weights |
| K05 | LatentSync1.6,512,FP16,16-frame chunks,20 DDIM steps,CFG1.5 | Native dlib alignment; bounded PNG I/O; independent VAE batch slicing; resident CUDA weights; reuse recorded VAE |

Do not relabel a low-step fallback as K05 or a TensorRT export as this K02. Any changed resolution, model, steps, precision, audio or frame sequence requires a separate run record. Numerical key mismatches must cause failure, not silent partial-weight inference.

K03 training explicitly selects batch16; the pinned upstream training CLI defaults to8. References to the full/native batch in capacity diagnostics mean the selected16-sample protocol, not that the upstream CLI default was16. FP32 precision,144-pixel visual model,60 epochs and default loss weights are retained.

`prepare_wav2lip_source.py` checks/fetches the two original network files by immutable Git blob SHA rather than a moving branch name. Run it before a fresh K04 inference entry. The author’s personal/research/non-commercial terms apply separately to these files and public weights. This helper downloads no model weights; `wav2lip-source.json` records the exact source hashes.

## Inputs and split

The final test is exactly1,500 frames at25FPS,60 seconds,720×1280. It takes the same eight motion clips in the same order for every backend. Seven contribute200 frames each; the last contributes100. The source bank has10,000 frames:48 accepted actions plus two basic clips. `input-manifest.json` freezes actual frame IDs and verifies the common audio on every run.

`audio/common-60s.wav` is mono16kHz PCM16,960,000 samples. Its SHA256 is `1f75f4676f21162ab0c7abf8e0dc0e4fe94d0f7bfe8fceb10c4d727c2a3ce5c4`. Sixteen complete O07 utterances end at57.35seconds; the final2.65seconds are silent. Speech is neither sped up nor truncated. Individual generated WAVs and the text/timing record are retained. The earlier41-second preparation audio never entered the completed runs.

The remaining40 action clips provide8,000 training frames/320seconds for K03. Their IDs do not overlap the test. Training speech is independent of the test script. K01 generates synthetic teacher frames; FeatherTalk learns from these frames using its released losses and110-point preprocessing. This permits a same-identity pilot from the existing silent motion bank, but inherits teacher mistakes and cannot establish the model's quality after training on genuine aligned human speech.

K01 preserves its original production mask. K02–K05 are pasted back through the same bounded lower-face region. All hand, body and background pixels outside the permitted facial area come from the common source frame. H.264 encoding changes pixel values slightly; the verification threshold accounts for this. A hand crossing the mouth still needs visual review: an outside-face pixel test cannot certify occlusion handling inside the face.

## Resource scheduling and downloads

`bootstrap.py` downloads only the selected backends, using the pinned revisions, byte lengths and SHA256 hashes in `download-plan.json`. Keep its active process and `.part` files. A timed-out MCP launch can still have executed: inspect status and process identity before another launch. Do not restart MCP, ComfyUI, services or the device to resolve a task-local import problem.

`run_suite.py` owns a native Windows file lock. Existing successful stages are skipped. `bench_launch.py` uses an additional project GPU lock so this experiment never runs two GPU backends at once. These locks affect this task only. Other people's jobs, ComfyUI queue, loaded models and MCP service are never cancelled or restarted.

The original full-video heavy path waited for the entire ComfyUI queue. Capacity probes subsequently established bounded cooperative execution without lowering model strength. The actual K05 path starts with9,000MiB free GPU memory and6GiB available RAM, then checks6,000MiB GPU /4GiB RAM between16-frame chunks. K03 native training starts with10,000MiB free GPU /6GiB RAM and checks10,000MiB GPU /4GiB RAM before each batch. Both use an8GiB PyTorch allocator ceiling. If necessary, only this process's unused CUDA allocator cache is released. No other process's model is unloaded. Resource checks are repeated in the backend after the suite's launch gate; waiting is recorded explicitly.

K05 loads the pinned checkpoint with mmap and a meta-initialized model, strictly verifies every key and shape, and casts weights to the original FP16 precision directly on the resident device. This avoids retaining another2.5GB CPU weight copy. It uses one original ImageProcessor through the full run, preserving alignment smoothing across chunks. Initial noise generation, audio-feature extraction, DDIM updates,512 resolution,16-frame block size,20 steps andCFG1.5 retain the original model strength. The documented adaptations cover dlib geometry, original-PNG frame I/O, bounded residency, independent VAE batch slicing and exact60-second tail handling. The upstream full-video pipeline call, with the same native dlib wrapper, remains in `render_latent.py` for a separate exclusive-resource comparison.

The selected60-second test uses the first1,500 audio-feature frames to match the frozen1,500 source frames, in93 full16-frame chunks plus a final12-frame chunk. Whisper's extra end-padding features are recorded but do not add or loop video frames. The final tail context therefore need not be pixel-identical to the official path that consumes every feature frame. The short offload/resident equivalence diagnostic compares those two adapted executions only.

Native K03 batch16 / FP32 completed a real optimizer step with6,153.66MiB allocated and7,052MiB reserved under a12GiB diagnostic ceiling. A CPU saved-activation alternative fit within4GiB but was too slow in its observed shared window, so it is not the selected training path. K05's resident full-strength16-frame probe used4,847.99MiB allocated /5,520MiB reserved under8GiB. Its MP4 was byte-identical to the same short sequential-offload probe. These are capacity diagnostics, not the requested60-second results and not a general quality-equivalence proof. See `K03/native-fit-probe.json`, `K03/gpu-fit-probe.json`, `K05/resident-fit-probe.json`, `K05/probe-execution-equivalence.json` and the probe metadata correction sidecar.

CPU preprocessing uses two Torch threads, two ONNX Runtime threads and batch16 PFLD. It consumes no CUDA memory. The same SCRFD/PFLD weights and crop geometry are used; ten preexisting landmark frames must match within one pixel. The observed sample matched exactly. Valid existing landmark files are reused after a controlled task-only retry; malformed partial files are recomputed. See `preprocess-backend-check.json`, `cpu-landmark-probe.json`, `onnx-landmark-probe.json` and the preserved reconfiguration attempt.

VGG19 is a574,673,361-byte **training loss** dependency. It is not an additional deployed talking-head model. Its official weight SHA256 is `dcbb9e9dad569fff7a846263a77324fc34978fea2bfb039c012d710e1776ae44`. The helper checks it before training. Report training dependencies, optimizer/resume checkpoints, deployed inference weights, packages and avatar caches separately.

`prepare_offline_environments.py` was used to transfer hash-checked Windows wheels from this task's temporary LAN wheelhouse after the device's inherited proxy failed. It stops only the obsolete matching task installer. Once transfer and installation finish, close the temporary wheel server. The already running main model download is independent.

## Stage order and logs

1. Prepare and freeze O07 audio and the motion manifest.
2. Render K01, K02 and K04. Preserve failed attempts and rectify architecture/import issues before retrying.
3. Generate independent K03 training audio and8,000 teacher JPEGs.
4. Preprocess training/test landmarks and FeatherHuBERT features; retain disjoint clip ranges.
5. After the selected downloads, environment and full-strength fit probe are ready, render K05 at its frozen strength with the bounded resident execution adapter. The dlib adapter supplies the original alignment's eyebrow/nose anchors; it does not replace generation or invent head motion. Validate its complete60-second file before the longer identity training.
6. Train the original FeatherTalk for60 epochs, batch16, original loss weights, seed20261028, Windows workers0, FP32 saved activations on CUDA. Cache only decoded152-pixel face crops on CPU; this preserves model math and sampling. Keep every tenth epoch, the final checkpoint and one rolling checkpoint each epoch for task-local recovery. Export the exact final model weights separately from optimizer slots.
7. Render K03 on the held-out common60seconds.
8. Decode and validate all five complete videos; generate the final report only after every file passes.

`bench_launch.py` chooses the native backend interpreter, redirects stdout/stderr to dedicated UTF8 files and preserves uncaught tracebacks. `suite-status.json` records actual stages and waits; `result.json` must contain observed timings only. Successful preparation does not imply a generated clip. `backend-import-smoke.json` checks imports/tokenizer assets with CUDA disabled, not model quality or performance.

K03 per-epoch seconds span the original optimization loop and CUDA synchronization. Rolling checkpoints, the upstream checkpoint/preview writes and initial crop-cache construction are included in the full training-entry wall time, not in those epoch-only timers. Loss values and training throughput describe this synthetic-teacher fit, not perceptual lip-sync quality.

Two invocations exited after completed checkpoints23and56 because Windows denied replacement of the transient progressJSON. `archive_failed_training.py` preserves both original exceptions, histories, sampled resources and suite windows before resume. After unique temporary files and bounded retries alone proved insufficient, `bench_common.save` treats progress-only PermissionError as nonfatal and retains a writer-specific fallback snapshot. Checkpoints, training history and measured results remain strict. The viewer buffers small mutable JSON before network transfer, releasing its file handle immediately; only this experiment's viewer was reloaded, not MCP or model services. The actual external holder of the denied file was not identified. `verify_atomic_progress.py` executes the actual writer against real native FILE_SHARE_READ-only handles and checks a slow HTTP transfer: telemetry survives, complete snapshots stay visible, result writes wait for release and media Range requests still work. Evidence is inatomic-progress-check.json.

Each resumed invocation restores the author's model/optimizer/epoch checkpoint and reseeds20261028. The author's checkpoint does not restore every Python/NumPy/CUDA RNG state; do not claim bit-identical uninterrupted training. `training-invocations.json` separates the final entry wall, all prior failed suite-stage walls and their aggregate, excluding idle repair gaps. Earlier sampled waiting is retained as observed evidence rather than invented as an exact cumulative timer.

The initial teacher preparation reused a60-second test summary label despite actually writing8,000JPEGs for320seconds. `TRAIN/metadata-correction.json` transparently corrects the derived duration/FPS/RTF/audio-hash labels. The original wall-clock measurement and original record are preserved. This preparation record is never presented as the K03 test video.

## Measurement and verification

- Generation wall time ends when the actual MP4 encoder closes. RTF=wall/60; throughput FPS=1,500/wall. Neither is live playout frame rate or platform response latency.
- Cold initialization is recorded per entry point, with differing module-import, asset-cache and warm-up boundaries disclosed. K05 source-video preparation is separate. Download/install, character training and cache preparation are not hidden in inference time.
- Feature, inference, read/preprocess, blending, encoder backpressure and final flush are recorded where applicable. K05 also measures affine alignment, decoded-latent reconstruction and full-face restoration.
- PyTorch allocated/reserved peaks belong to the benchmark process. One-second `nvidia-smi` samples describe the whole GPU including unrelated projects. System CPU/RAM are also shared. Python RSS excludes its FFmpeg child. These first runs occurred in different shared-load windows: they do not provide an exclusive-GPU speed ranking.
- Each MP4 must fully decode to1,500 frames,25FPS,720×1280 and60seconds. Verify original WAV hash, decoded AAC correlation>0.98 and absolute offset<20ms. This checks the soundtrack's integrity, not mouth synchronization quality.
- The final validator may retain an already successful full-decode/source-pixel/audio proof after rechecking identical videoSHA256 and the frozen source-audio hash. New or changed files still receive the complete checks; explicit model IDs force their validation. `verification-reuse.json` records any such reuse without rewriting the original successful proof.
- Compare60 sampled decoded frames to independently exported source PNGs outside the facial region. Mean absolute pixel error must be<3. This checks the local-module boundary, not the correctness of generated lips.
- Retain six common full-frame stills and complete resource data per backend. The comparison page uses one common audio clock, two selectable real video files, synchronized seeking, mouth enlargement and numeric sorting. Personal1–5 ratings live in the viewer's browser and never overwrite raw measurements.
- Decode all six review stills and the frame-zero poster from the final MP4, using two native CPU decoder threads. `stills/source.json` records the final-file signature and frame indices; a completed signature prevents repeated extraction during status publication. Encoding-before-render caches are not the final review screenshots.
- The portable bundle also includes the60 sampled original PNG frames and their plain-JSON face geometry under`inputs/source-evidence/`, so outside-face checks can be inspected independently. It excludes the binary avatar pickle and the remaining full motion/training image bank. The two short K05 execution probes are included as diagnostics and explicitly labelled0.64seconds, not60-second results.
- No SyncNet/LSE/MOS number is fabricated. Judge closure, teeth, lip timing, skin seams, identity and temporal stability from full videos; document observations separately from integrity checks.

## Finalization

After all five records and verification files exist, sync only the reviewed deliverables and evidence back to the local results directory. Keep large training caches/models on A; reference them with paths/hashes. Do not silently omit them from a claimed whole-device storage total.

```powershell
python -X utf8 operations\k01-k05-60s-20261028\plot_all.py
python -X utf8 operations\k01-k05-60s-20261028\make_final_assets.py
python -X utf8 operations\k01-k05-60s-20261028\build_report.py 'E:\dev\sandbox\虚拟数字人直播'
node operations\k01-k05-60s-20261028\review_page.cjs
```

The five-way MP4 is a60-second overview, not a substitute for the five original portrait videos. The GIF is a six-second, silent detail preview from seconds8–14. Charts require all five actual successful records and do not insert zeros for pending runs. The comparison page is checked in a fresh headless native Chrome context and closed in `finally`. Close only this task's browser processes; preserve user tabs and other applications.

An additional GIF shows the truly zero-sample57.35–60s soundtrack interval. Its encoded duration is quantized to10FPS and measured inreview-assets.json. It is for silence behavior, not a second60-second test. A local16-check native Chrome review passed for the four completed variants while K03 was training; final five-file playback is checked again after receipt. The range handler tolerates an absentstderr under hiddenpythonw, and the retained local viewer redirects logs to project-local files. The static viewer exposes only this experiment's files and supports206 byte ranges for seeking.

Do not create a PDF or compressed deliverable archive. Preserve historical reports, source audio and scores. Add a new dated report/source directory to Git, excluding model/runtime installations, MCP control logs, API keys, cookies, private state and signed download URLs. The selected live production backend remains unchanged until the user chooses a replacement.
