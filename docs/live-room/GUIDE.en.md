# Room control, chat and message overlays

[中文完整方案](README.md) · [Architecture](ARCHITECTURE.md) · [Runbook](RUNBOOK.md) · [API](API.md) · [Acceptance](ACCEPTANCE.md)

Release `split-a4090-b3080-v1.2.0-room-admin` adds an operational web console to the accepted female-A / Lin Zhixia daylight-dorm system. A4090 retains O07 / OmniVoice, F07 / F5-TTS v1, MuseTalk FP16 batch 8 and the sole DSH/Humanity writer. B3080 receives the native stream and uses official Livehime for presentation and broadcast.

Open `/admin` on the existing avatar service. No login or additional server port is required. “Start local session” controls DSH interaction; public broadcasting remains an explicit operation in official Livehime.

![Actual deployed console](../media/room/admin-overview.png)

## Delivered controls

| Workspace | Capabilities |
| --- | --- |
| Overview | Optional muted live preview, A/B health, selected voice, title/topic/announcement, local-session lifecycle, explicit Echo/AI speech and current-request cancellation |
| Music | Three original instrumental WAV tracks, validated uploads, ordering, play/pause/seek/next/previous, repeat/shuffle, delete custom tracks, music/speech gain and automatic ducking |
| Visuals | Four image presets and six bounded sliders; three coordinated paper/sage/navy themes; independent chat, gift, message, caption, badge and announcement controls |
| Chat and messages | Live comment column, optional top scrolling text, gift/follow/paid-message notices, on-screen message cards, pins, next unanswered item and manually approved replies |
| Moderation | Recent 100-message inbox, search/type filter, hide/restore, answered flags, blocked names/words, clearly marked local tests and cleanup |
| Private agent | Existing persona and saved cloud channel, contextual private conversation, cancel/new session and explicit copy-to-speech draft |
| Operations | Real program/mixer observations, audit log, settings import/export, defaults and emergency mute/cancel |

The complete decoration is embedded in the existing program source. B's browser-material URL is:

```text
http://127.0.0.1:8020/output.html?output=platform&renderer=livehime&buffer_ms=4000&rev=room-v1.2
```

Use a 720×1280 canvas, source-internal audio, no monitoring, and mute desktop/microphone audio. Standalone transparent `/overlay?layer=chat`, `messages`, `gifts` or `all` layers are silent and have no playback authority. Disable the embedded layer before using separate copies.

## Design and implementation

Paper white, sage, muted blue and apricot accents complement the daylight dorm. The face zone remains clear; chat and message cards sit below it. Public feature documentation from [blivechat](https://github.com/xfgryujk/blivechat) and [bilive-chat](https://github.com/zclkkk/bilive-chat) informed the feature organization. This is a native implementation, with no copied assets or added containers.

RoomManager runs inside the existing DSH process. SQLite stores versioned settings, a bounded inbox, track index, private conversation and audit history. CAS revisions prevent stale pages overwriting new settings. Reconnecting SSE clients receive an authoritative snapshot without replaying old gift animations.

B uses the existing Web Audio output to mix streamed music with valid scheduled speech. Default music gain is 22%; valid speech ducks it to 23% of that gain with 90 ms attack / 650 ms release. Cancellation clears obsolete duck intervals. Background previews are muted and cannot acknowledge speech. Captions use approximate sample-progress paging, not ASR word alignment.

Private agent replies stay in the console until the operator copies one into a draft and explicitly submits speech. Private chat does not automatically create viewer-memory candidates. “New conversation” changes context, not secure disk deletion. The existing Humanity maintenance/deletion contracts remain intact.

Uploads support audio-only WAV/MP3/OGG/FLAC/M4A, 1 second–2 hours, at most 128 MiB, one upload at a time. Native ffprobe validates content; temporary files are removed on failure. No server-side media URL fetch is supported. The default library includes three original, procedurally generated WAV tracks and reproducible provenance/checksums.

## Validation and limits

96 Node tests including native Chrome, 46 Python tests and 27 native proxy routes passed. Five real local A→B speech cases completed with full sample receipts and natural ends. During that run, 119 observations averaged 24.991 FPS (minimum 24.650); audio underrun, missing-packet and decode-error deltas were zero. A 4,147,244-byte upload traversed B→A successfully, and official-player observations confirmed actual music ducking.

No public broadcast, paid gift, audience-CDN latency or fresh Douyin account integration was exercised. A first 413 upload failure is retained: B's actual service root was `receiver-b`, and updating its parent directory did not update the running receiver. Historical benchmark data, audio and evidence remain unchanged; this release adds separate evidence.

[Actual six-page screenshot tour (silent GIF)](../media/room/admin-tour.gif) · [Mobile screenshot](../media/room/admin-mobile.png). The GIF is a tour assembled from actual deployed-page screenshots, not a continuous action recording. Deployment stays entirely native Windows; do not start Docker, WSL or virtual machines. Close task-owned unused previews and tabs after inspection.
