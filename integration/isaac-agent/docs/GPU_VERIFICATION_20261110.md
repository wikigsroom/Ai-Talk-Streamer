# GPU02 fixed-input validation (2026-11-10)

This is an optional deterministic geometry backend, not a model or strategic actor. Tests used native Windows on an RTX4090 and dual Xeon E5-2673v4, existing PyTorch2.9.1+cu128. No model weights or dependencies were downloaded.

The same frozen predictor, original native Lua/Vector and complete safety guards were executed against identical prepared inputs while the real game was normally paused. The voice/avatar/programme services remained running; official recording was not yet active. Wall times include extraction, packing, TCP, CUDA and native guards, excluding Frida scheduling and fixture construction. Each backend has 25 samples, nine directions and ten steps. This controlled replay must not be described as live combat FPS.

|Enemies+projectiles|CPU mean ms|GPU plan mean ms|CPU P95 ms|GPU plan P95 ms|Speedup|Actual GPU successes/25|
|---|---:|---:|---:|---:|---:|---:|
|1+0|2.99|3.36|3.65|4.12|0.89x|0 (adaptive CPU)|
|4+8|9.66|7.89|10.21|10.30|1.22x|25|
|12+32|29.99|10.58|63.41|13.84|2.83x|25|
|32+128|96.47|55.57|149.06|164.58|1.74x|15|

Every one of 100 paired movement and aim outputs matched. The 160-track case had one timeout and nine cooldown CPU samples: its tail latency did not improve, so this result is not an extreme-load real-time guarantee. The one-enemy rows execute the CPU path and differ due to repeated measurement variability. Raw fixtures, input SHA256 and all 200 samples are in [fixed-input.json](evidence/gpu-fixed-input-20261110.json). A separate 200-request TCP/CUDA scalar-oracle check had maximum absolute error1.1369e-13, which is not exhaustive native gameplay equivalence.

A separate real official capture (315-second monitored interval, 322.77-second raw file) yielded a continuous300-second1080p30 export with actual narration and avatar inference. Real game geometry successes increased by18 with no fallback. OpenGL sliding-window samples had median59.56FPS, minimum58.75FPS; active game-logic intervals median29.15/s, minimum25.20/s. Sparse5-second observation did not capture combat at interval endpoints, so no combat-specific logic FPS is claimed. Different encounters and static/pause content prevent a controlled before/after video motion comparison; full-time steady60FPS and all long-run release gates are not claimed.

Standalone regressions:613 Python tests and4 Node binding tests passed. Integration deployment separately passed638 rule,119 stack,49 DSH/input tests. First local HTTP run had a transient connection failure; direct networking rerun passed the individual test and full suite. The integrated application uses the existing local CUDA environment; the standalone repository keeps CPU as default.
