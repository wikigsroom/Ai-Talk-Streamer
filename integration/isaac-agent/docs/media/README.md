# 实机素材来源 / Media provenance

这些素材来自 **2026-11-07 原生 Windows、Repentance 1.7.9b、第 3 槽、native130-dsh 纯本地模式**。没有使用生成式图像或伪造状态。 / Captured on 2026-11-07, native Windows, Repentance 1.7.9b, authorized slot 3, native130-dsh local-only mode. No generated gameplay or fabricated state.

| 文件 / File | 来源与范围 / Source and scope |
|---|---|
| [local-gameplay.mp4](local-gameplay.mp4) | 45.16 秒，968×550，H.264，原始捕获时间间隔保留；仅游戏画面，无音频 / 45.16 s, 968×550 H.264, original variable capture intervals, game only, no audio |
| [local-gameplay.gif](local-gameplay.gif) | 上述视频 24–38 秒，14 秒原速，720×409，6 fps 输出 / Original-speed 14 s excerpt, source 24–38 s, 720×409, 6 fps output |
| [gameplay-local.png](gameplay-local.png) | 原生帧缓冲约 32.86 秒时的真实战斗帧，968×550 / Actual native combat framebuffer at about 32.86 s |
| [dashboard-local.png](dashboard-local.png) | 当前服务的真实只读页面；捕获时录制已结束，游戏已暂停 / Actual read-only live service page after recording, game paused |
| [manifest.json](manifest.json) | 以上文件大小、SHA-256 与媒体探测 / File sizes, SHA-256 and media probe results |

45 秒测试请求结束后额外进行了真实暂停确认，总验证耗时 45.92 秒。187 张源帧约为 4.16 fps，属于低帧率观察录像，不代表游戏自身更新频率。GIF 输出为 6 fps，不改变原始时间速度。

The 45-second request took 45.92 seconds including pause acknowledgement. The 187 source frames yield approximately 4.16 fps capture, not the game's update rate. GIF resampling to 6 fps preserves playback speed.

录制经过 5 个房间；生命由 6 到 4 半心；36/41 采样为后台，另有前台采样。因此这些媒体展示可运行的本地控制与部分后台推进，**不展示当前新网关 DSH 成功、不展示完整通关，也不证明通过率提升**。

Five rooms were observed; health fell from six to four half-hearts; 36 of 41 samples were background. The media demonstrate local control and background segments, **not a current migrated-gateway DSH success, a completed run or a win-rate improvement**.

观察页面使用本机无界面浏览器捕获，任务结束后页面、context 和浏览器均已关闭。未录入桌面其他窗口、密钥、服务地址或个人路径。原始逐帧图和日志保留本地，不入库。

The dashboard was captured with a local headless browser; pages, context and browser were closed afterward. Other desktop windows, keys, endpoint addresses and personal paths are excluded. Raw capture frames/logs remain local.
