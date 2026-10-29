# Project operation constraints

- Work only inside this project. Use native Windows/Python/Node; never start Docker, WSL or virtual machines.
- **Read `configs/deployment-target.json`, `configs/deployment-targets.json` and `docs/deployment/DEVICE_BRANCHES.md` first.** `main` is shared source and cannot start inference. Device branches are `deploy/rtx3080` and `deploy/rtx4090`; each owns its release pointer and state path. Never use a remembered device default.
- Before inference deployment/start, run `scripts/deployment_target.py`. Git branch, source receipt, GPU, batch and DSH state must agree. Copied runtimes require `.setup/deployment-origin.json`; do not fabricate or manually switch this receipt to bypass a mismatch.
- RTX3080: native same-host K02 FP16 batch4, O07/F07, sole DSH writer, loopback receiver and official Livehime. Read `docs/deployment/RTX3080_K02_RELEASE.md`. Five local cases passed; this is separate from public/CDN acceptance.
- RTX4090: A4090 inference FP16 batch8 plus B3080 receiver-only. Read `docs/deployment/BASELINE_K02.md`, `docs/deployment/SPLIT_DEVICE.md` and `docs/RTX4090.md`. K02 activation and candidate cleanup on4090 remain pending. The user paused4090 control until notified; branch creation does not resume it.
- A4090+B3080 means B3080 receives media without loading avatar/TTS; it is different from the native3080 inference branch. The receiver stays under `receiver-b`, uses its own loopback8020 and official-source audio. Do not create an additional audible output consumer.
- Preserve female-A / 林知夏, original daylight dorm, the full48-gesture bank, O07 OmniVoice and F07 F5-TTS v1. Retain shared MuseTalk/Whisper/VAE weights. Preserve retained Kokoro/Melo/F5/Omni models and all historical measurements/media. Do not download new candidates or restore MOSS.
- Retire only dedicated K03/K04/K05 installations through the scoped cleanup script when the device is authorized and reachable. Repository branches do not establish that remote deletion has happened.
- Public pages/APIs stay free of application authentication as requested. Platform identity verification and cloud-provider protocol remain external requirements.
- Bilibili output uses official Livehime, not OBS. Do not start public broadcasting for a local test. Keep unresolved public-state reconciliation, audience-CDN timing and memory-maintenance gates visible.
- Keep one authoritative DSH/Humanity writer per installation. Never mix `.setup`, live SQLite state, deletion ledgers, channel keys or platform credentials across device branches. Transfer persistent state with a consistent backup only under an explicit migration plan.
- Private operator chat does not automatically speak or create viewer memories. Official-source playback receipts advance speech completion; admin/preview/overlay pages are not playback authorities.
- Preserve unrelated apps and GPU jobs. Source sync must not stop an active broadcast or restart models. Close this task's unused browser tabs/contexts.
- Publish reviewed source/assets and sanitized evidence only. Keep private configs, state, cached models, runtimes, signed URLs, credentials and process registries out of Git.
