# Optional local CUDA geometry worker

This optional accelerator computes swept trajectory distances for the existing
deterministic combat rules. It does not run a language model, read game memory,
authorize pickups, issue inputs, or replace DSH. CPU-only operation remains the
default; keep the original strategic provider and save-protection workflow.

Use an existing native Windows x64 Python environment with NumPy and CUDA-enabled
PyTorch. No new game DLL is required. The supported game remains the pinned x86
Repentance version. Start the worker separately before explicitly opting in:

```powershell
& 'C:/path/to/existing/cuda-python.exe' isaac_gpu_worker.py --port 9536 --health-port 9537
```

Wait for `http://127.0.0.1:9537/health` to return `ready: true`. For the in-memory
native controller, evaluate the following config immediately before the generated
controller source, in the existing authorized install pathway:

```lua
_G.ISAAC_GPU_GEOMETRY={enabled=true,port=9536,deadline_ms=8}
```

Leaving this global unset preserves the CPU path. Do not bypass the normal
observation-only startup, writable slot-3 binding, DSH fencing, ordinary inputs,
or confirmed-pause lifecycle. Stop the worker after the game is safely paused.
`ISSAC_STOP_FILE` can name the owner-created stop-request file for graceful exit.

The native client sends one persistent binary loopback request per combat update.
Each request contains nine candidate forecasts, eleven points per trajectory,
initial-position and first-vulnerable-step metadata. FP64 CUDA Graph kernels are
prewarmed into 16/64/256-track buckets. A 32-byte little-endian header fences the
sequence, game frame, seed, room, stage, count and horizon; the response must echo
every identity byte. The wire format is defined by `HEADER` in the worker and
`string.pack` in `gpu_geometry.lua`. All coordinates are bounded to ±8192.

No stale response is reused. Socket/protocol/numeric errors or the total 8 ms
budget trigger the original CPU calculation and a one-second reconnect cooldown.
Counts above 256 keep all threats on CPU. Native float32 and FP64 distances can
differ slightly: candidates within 0.25 pixels of a collision radius use the
original native formula. Bounce trajectories, immunity, TNT, lasers, floors and
the final native safety checks remain active.

The integrated planner keeps fewer than four threats on CPU, because the
measured communication overhead exceeds the saved arithmetic in tiny rooms.
Payload numbers are packed in one bulk call. The worker uses a high-priority
CUDA stream to reduce queuing alongside avatar inference; this cannot preempt
an already executing kernel and is not a latency guarantee. Both client modules
are included in the source-sync list as well as the in-memory controller.

Run CPU/Lua contract regressions with the standard test suite. With the worker
already ready, use `python tools/verify_gpu_geometry.py` to compare the actual TCP
and CUDA output with an independent scalar oracle, including immunity and
between-sample crossings. This synthetic check is not an actual-game frame-rate
claim. Report real Lua timings, GPU successes/fallbacks, render intervals, avatar
and recording coexistence separately. Worker memory counters exclude CUDA driver
context; measure total process/device use as well.

The worker binds loopback only and accepts no code or game actions. GPU use is an
arithmetic implementation choice, not a new inference provider. Preserve MIT
attribution and the existing native Windows-only constraints.

Measured fixed-input timings, fallback counts and validation scope: [GPU02 validation](GPU_VERIFICATION_20261110.md).
