# Split-device inference and official Bilibili Livehime

[中文完整操作手册](SPLIT_DEVICE.md) · [Acceptance](SPLIT_DEVICE_ACCEPTANCE.md) · [4090 target](../RTX4090.md)

Run **MOSS 04, MuseTalk, DSH and Humanity on device A**, and run **the official Bilibili Livehime client on device B**. A and B communicate over the existing virtual LAN. This implementation uses native Windows Python and Node processes throughout.

The 4090 target retains female-A / Lin Zhixia, the daylight dorm, all 48 motion clips, MuseTalk FP16 batch 8, and 720×1280 at 25 generated frames/s. The configured cloud LLM supplies text reasoning and memory extraction. Media inference stays on A.

## Responsibilities

| Component | Device A | Device B |
|---|---|---|
| Local TTS and avatar models | MOSS 04 and MuseTalk | None |
| Personality and canonical memory | One DSH/Humanity writer | Proxied access only |
| Comment ingestion and event ledger | Native platform adapters and SQLite | Official platform UI |
| Transport | One shared 3 Mbps NVENC H.264 stream plus lossless PCM | Lightweight Python gateway, hardware decoding |
| Browser composition and final broadcast | No Livehime client required | Official Livehime browser material, source audio, final encoding/upload |

A still performs a fixed-function NVENC encode for transport. It does not perform B's final broadcast encode. B does not load Torch, CUDA, TTS or avatar models. This avoids transferring large JPEG images over the virtual network.

## Addresses

Replace `REMOTE_4090_HOST` with A's actual virtual-LAN address.

| Address | Location |
|---|---|
| `http://REMOTE_4090_HOST:8010` | A studio and application API |
| `http://127.0.0.1:9880` | A local MOSS service |
| `http://127.0.0.1:3092` | A local DSH service |
| `http://127.0.0.1:8020/receiver/` | B receiver dashboard |
| `http://127.0.0.1:8020/output.html?output=platform&renderer=livehime` | B's official Livehime browser source |
| `http://127.0.0.1:8020/platforms` | B controls A's local platform session |
| `http://127.0.0.1:8020/memory` | B accesses A's personality and memory |

The B gateway preserves one local origin for pages, HTTP, SSE and WebSocket. Loopback is a trustworthy browser context for WebCodecs. Direct remote HTTP may not provide that context. The gateway has one saved upstream origin and never selects another upstream from an incoming URL.

Application access remains open, without administrator login, tokens or roles. The Bilibili client's own account login is separate.

## Prepare A

The actual A deployment has native media environments, both MOSS model sets, the registered v04 reference, the complete avatar bank, Node 24.22.1, DSH 0.2.0-rc.2 and Humanity 0.1.17. A clean machine must first follow the [native media deployment](../DEPLOYMENT.md) and [MOSS migration](RTX4090_MIGRATION.md). The commands below activate an existing installation; they do not install missing MOSS models.

The Git checkout and the runtime root can be separate. `git pull` alone does not update a running installation. Copy only reviewed application paths, back up replacements, preserve private files and state, then install the adapters.

```powershell
Set-Location -LiteralPath 'C:\dev\虚拟数字人直播'
$InferencePython = Join-Path (Get-Location) 'runtime/livetalking/Scripts/python.exe'
& $InferencePython -X utf8 -B deployment/activate_moss.py --voice v04 --batch-size 8
& $InferencePython -X utf8 -B deployment/deploy_dsh.py
& $InferencePython -X utf8 -B scripts/configure_split.py --isolated-state state/female-a-4090
& .\Start-Inference.ps1 -PythonExe $InferencePython
```

Use an isolated state directory for validation while the old 3080 remains the formal memory owner. Omit `--isolated-state` to preserve the current policy's state path after an intentional, consistent cutover. The configuration helper refuses an active A broadcast and backs up its changed files. It retains channel credentials and platform secrets, selects receiver placement, and sets the playback lease timeout to 30 seconds.

Startup order is avatar, MOSS, then DSH, avoiding overlapping model-loading peaks. The launcher opens no browser or official client and starts no public broadcast. MOSS retains NF4/BF16 computation with the FP32 CPU codec; a larger GPU does not automatically change that implementation or remove autoregressive waiting time.

## Prepare B

B needs native Python 3.10+, official Livehime and a Chromium engine with H.264 WebCodecs support. No media model installation is required.

```powershell
Set-Location -LiteralPath 'E:\dev\sandbox\虚拟数字人直播\Ai-Talk-Streamer'
& .\Install-Receiver.ps1 -PythonExe 'C:\Python313\python.exe'
& .\Start-Receiver.ps1 -Upstream 'http://REMOTE_4090_HOST:8010' `
    -ClientExecutable 'D:\Program Files (x86)\bililive\livehime\livehime.exe'
```

The installer creates `runtime/receiver` and installs only aiohttp 3.13.3 and psutil 7.2.1. Temporary files and caches remain in the project. An existing compatible Python may be supplied directly with `-PythonExe`.

Configuration is saved in ignored `configs/receiver.private.json`. The receiver binds only to B loopback. Stop it before changing its upstream. `Start-Receiver.ps1 -Stop` terminates only the recorded receiver process after checking executable, script and process creation time; it does not stop A or the public platform stream.

Open `/receiver/` on B, check A's health, and launch the configured official client. Login happens in B's client using the owner's account; A's account files are not copied.

## Configure official Livehime on B

1. Select a portrait canvas, 720×1280. Final encoding may be 30 FPS; the avatar itself remains 25 FPS.
2. Add one browser material using B's output URL above, width720 and height1280.
3. Enable the material's internal audio, set its level to100%, and verify it in Livehime's mixer and an actual local recording.
4. Mute desktop audio and microphone to avoid feedback, duplicate speech and unrelated computer sounds.
5. Use `renderer=preview` for any standalone preview. It is muted and does not claim playback authority. Close unused previews after checking.
6. On `/platforms`, save `client_location=receiver`, prepare the output, then start the local interactive session.
7. Verify picture, actual audio and mouth timing in a local recording before starting the public broadcast.

`COMPANION_READY`, application `LIVE`, and browser heartbeat are local readiness states. They do not establish that official Livehime is publicly streaming or that viewers have received the media. Browser tests and the official client's own recording are separate acceptance steps.

## Transport and interruption rules

The default stream is H.264 Baseline level3.1, 720×1280, 25FPS, 3Mbps CBR, GOP50, noBframes, low-delay NVENC. The encoder must return exactly one packet with the matching input PTS. PCM is unchanged mono16kHz/16bit, 640samples per40ms packet, approximately256kbps in addition to the video and protocol overhead.

The binary header is three little-endian uint32 values: sequence, video length and sample rate. H.264 video starts with `AVC1`, a little-endian keyframe flag, then AnnexB data. The matching PCM follows. Control maps precede their media packets.

WebCodecs decodes shortly before presentation; picture and sound share the AudioContext clock. Default buffering is4seconds. `buffer_ms` accepts800–10000 for deliberate tuning. More buffering increases interaction delay; it cannot overcome an arbitrarily long outage. JPEG remains a compatibility/diagnostic fallback, explicitly selected by `codec=jpeg`. On the measured virtual network it delivered about5FPS, so JPEG fallback does not meet the smooth-playback gate.

The sender never removes PCM to catch up. H.264 references are also retained. A receiver more than125packets behind is disconnected instead of receiving a broken dependency chain. Reconnection obtains a new keyframe. Cancellation clears old queued media and maps, resets the decoder, and requests a keyframe.

Before emitting valid speech, A persists its media sample mapping. B confirms only a contiguous played prefix; natural completion requires every valid sample and natural source endings. Runtime epochs, generation barriers, lease IDs and transport IDs remain enforced. A cancelled `ended` event cannot become a successful playback acknowledgement.

Only one `renderer=livehime` source should act as output authority. The gateway attaches B's receiver ID and client-presence metadata; A ignores A-side Livehime heartbeats without a receiver ID in split mode. This identifies topology, not the browser container or the public audience.

## Session lifecycle and memory ownership

Pausing retains the broadcast ID, cancels active audio, and prevents new dispatch. Resume changes the runtime epoch and obtains a fresh lease. A broken B connection causes reconnection and authority recovery; incomplete speech is not automatically repeated or remembered as fully spoken. Stopping B alone does not end official streaming or A's business session.

End public streaming in the official client, close the comment input, and end/drain the local session. A then seals events, observes the quiet window, compresses the session, updates projections, and runs durable daily/weekly work according to the [DSH specification](../DSH_HUMANITY.md). B may be closed while A maintains memory. If A is shut down, persisted jobs resume at its next startup.

The current 4090 test state and the old 3080 formal state remain separate. Formal cutover requires ending the old session, stopping its writer, transferring a consistent SQLite backup plus deletion ledger/projection/personality metadata, replaying deletion barriers, and starting exactly one authority on A. Do not copy an active SQLite main file alone. Stop A before rollback to the old writer. See the [migration runbook](RTX4090_MIGRATION.md).

## Repeatable acceptance and troubleshooting

`devtools/validate-split-device.mjs` runs five real A→B cases: greeting, longer explanation, pause/resume, conversational reply, and cloud personality/context. It also checks duplicate rejection and socket reconnection. It records actual received sound/video, samples browser metrics, restores interaction settings, ends only its own session, and closes its owned Chromium context. It never starts public streaming. Use a new evidence directory on every run.

```powershell
$env:SPLIT_EVIDENCE_DIR = Join-Path (Get-Location) 'outputs/split-device/five-cases-new'
& 'PATH_TO_NATIVE_NODE_24\node.exe' devtools/validate-split-device.mjs
```

Required media gates: five naturally completed utterances, complete sample acknowledgement, 720×1280, stable presentation≥22FPS, zero audio underruns, missing packets or decode errors, and recovery on a new keyframe. Official Livehime's recorded audio and public viewer-comment→audible-reply validation remain additional gates.

If the B page cannot connect, check A8010 and the saved virtual-network upstream. If H264 is absent, verify loopback origin and VideoDecoder support. If audio breaks during speech, inspect buffering, arrival gaps and A packet-delay logs; never hide it by dropping samples. If replies start late, inspect actual MOSS and cloud timings. If B has sound but the official recording does not, inspect source audio routing, mixer levels, desktop audio and microphone settings.

The receiver status also reports `media_codec`, identified from actual packet headers, and `player_fps`, derived from the same consumer's reported frame counter. Livehime uses `output_mode=direct_canvas_audio`: it displays the decoded canvas and connects PCM to `AudioContext.destination` for the material's internal audio capture. This removes the additional canvas-capture/MediaStream/video stage in offscreen CEF. Its `fps_source=canvas_draw` measures canvas updates. Muted previews retain the original MediaStream path and report `fps_source=video_presentation`. Neither counter establishes official encoder or audience frame rate. The gateway retains only allowlisted, finite, nonnegative diagnostics and does not forward arbitrary diagnostic fields to A.

The earlier browser overload branch incorrectly called `WebSocket.close(1011)`, which browser JavaScript rejects. It now uses application code4001. A disconnected player immediately releases queued sound and decoded frames, then reconnects on a fresh keyframe. Reload the source or restart the client after updating. A real native-Chrome fixture verifies direct audio output, decoder-overload reconnection, disposal of old media and preserved preview presentation.

Livehime requests `prefer-software` WebCodecs decoding to isolate the old CEF hardware-decoder stall; previews retain their hardware preference. This changes B's H264 decoder preference and leaves A's model precision, resolution and NVENC unchanged. Configuration acceptance alone is not playback proof. Additional audio-clock and decoder-queue diagnostics support native acceptance. A4001 decoder failure clears old media and reloads the page after5seconds, allowing updated code to load; ordinary network failures reconnect the current page.

These observations do not prove official-client recording or audience delivery. Keep B's desktop available for native-client acceptance. The prior locked-desktop attempt failed its timeout, and later logs identified the persistent decoder-recovery error as an additional failure. Version8.11 also uses separate `*_v2` canvas settings, so verify the real portrait recording instead of inferring it from legacy configuration fields.

Implementation: `scripts/receiver_service.py`, `receiver_control.py`, `configure_split.py`, `integration/stream_encoder.py`, `local_broadcast.py`, `viewer_buffer.py`, `web/local-stream.js`, `backend/platforms/livehime.mjs` and `manager.mjs`. The [Chinese runbook](SPLIT_DEVICE.md) expands configuration fields, exact states, failure behavior, memory cutover and the complete source map.
