# 平台接入实机页面与录像 / Native platform evidence

本页展示原生 Windows RTX 3080 上的真实服务、OBS 浏览器源和本地 RTMP 接收结果。界面截图通过控制端的独立 Chrome 窗口拍摄，未拦截或模拟接口；拍摄结束已关闭相应浏览器上下文。它们不是 B站或抖音观众端截图。

控制页截图拍摄于最终测试结束后：本地测试输出与弹幕采集已经停止，平台私有配置已恢复。B站未填写推流参数，因此检查页正确显示“推流配置尚未就绪”；切换平台会清除前一平台的检查结果。

## 控制页面

![实际平台接入页面](../media/platform-native-rtmp-desktop.png)

![B站房间配置和弹幕连接](../media/platform-native-bilibili.png)

<img src="../media/platform-native-mobile.png" alt="390px 移动端实际页面" width="390">

## 视频与 GIF

- [带声音的原生推流预览](../media/platform-local-preview.mp4)：来自 OBS → 本机 FFmpeg RTMP 接收结果，保留实际 MOSS 04 语音。
- [平台页操作录屏](../media/platform-ui-interaction.mp4)：真实页面操作；此录屏不带人物声音。
- 完整录像在运行中工作站的 `/platform-evidence/platform-local-validation.mp4`，使用与演播台相同的 `8010` 端口；完整结果为 720×1280、25 FPS、H.264 + AAC。

![本地人物说话片段，无声 GIF](../media/platform-local-response.gif)

GIF 是实际录像的原速节选，不代表整场平台延迟。视频预览的裁剪位置和来源哈希记录在[媒体清单](../media/platform-media-manifest.json)。

## 实际覆盖范围

| 项目 | 本次证据说明 |
|---|---|
| 软件环境 | 原生 Windows、OBS 31.1.2、720×1280、25 FPS、本地 MOSS 04 / MuseTalk、云端文字渠道 |
| 消息输入 | 本地统一事件接口提交带平台身份的验收事件；B站真实房间 595139 另行验证 WebSocket 与心跳连接 |
| 五项场景 | B站事件原文播报、重复消息只播一次、抖音事件原文播报、暂停时保留消息并在同场恢复、真实 AI 回复播报 |
| 播放确认 | 四次实际语音均需 DSH 收到连续样本自然结束确认，不能仅凭已生成音频判定完成 |
| 音频检查 | 解码后非静音，检查 AAC 包时间戳；连续时间戳不等同于证明任何平台观众端毫无卡顿 |
| 真实平台开播 | 未填写推流码、未登录抖音账号，尚未向真实房间公开推流或验收观众端新评论 |
| 官方应用接口 | 已做签名、二进制包与生命周期测试；尚无获批应用，因此没有宣称真实官方事件到达 |

平台页保留先前诊断的失败与中断事件，成功测试不会抹去账本历史。`COMPLETED` 表示本地指定播放端播完，不表示平台 CDN 或远端观众已经收到。

完整机器验收记录见[平台证据](../evidence/platform-integration.json)。此前 DSH 的历史证据保留原日期、原来源哈希与原范围；本次新增接入使用独立证据记录变更及复验，未将此前未做的 20 轮记忆验收改为通过。

## English

These are captures of the actual native Windows installation and a loopback RTMP recording. Four real MOSS utterances and the duplicate/pause/resume checks exercise the local event-to-speech pipeline; the AI case uses the saved cloud text channel. Bilibili room connectivity is real, while test comments are explicitly injected local events. No external platform audience, account broadcast, approved developer application or Douyin login is claimed. The source/asset hashes and exact measured results are available in the linked evidence manifests.
