# 双机实测、录像与验收范围 / Split-device acceptance

[中文部署手册](SPLIT_DEVICE.md) · [English deployment](SPLIT_DEVICE.en.md) · [机器可读证据](../evidence/split-device.json) · [媒体校验清单](../media/split-device-media-manifest.json)

## 已完成的实际部署

2026-10-26，4090作为A，当前原生Windows电脑作为B，通过现有虚拟网络完成真实音视频和业务交互。A运行MOSS04、MuseTalk FP16 batch8、完整48段动作库、DSH0.2.0-rc.2、Humanity0.1.17和Node24.22.1。B运行轻量原生接收服务、Chromium解码和已安装的官方直播姬，不加载人物/TTS模型。

两组MOSS模型及配套迁移文件共29项、23,872,292,036字节，逐文件SHA验证完成；沿用v04参考音频。A使用独立测试状态，旧3080正式记忆和公开直播未被本次测试接管。

![B接收控制台，A地址已隐藏](../media/split-receiver.png)

## 五段真实交互

该轮从 `2026-10-26T10:30:20Z` 左右开始，完整记录以JSON内时间为准。每段实际调用A的MOSS/MuseTalk，再经虚拟网络由B播放。前四段使用验收留言原文播报，第五段使用真实云端LLM与DSH人格/已播上下文。

| 场景 | 有效语音长度 | 输入到自然完成确认 | 有声节选 | 结果 |
|---|---:|---:|---|---|
| 01 欢迎和自我介绍 | 8.96秒 | 33.019秒 | [观看01](../media/split-s01.mp4) | 全部样本自然播完 |
| 02 较长说明 | 9.28秒 | 35.000秒 | [观看02](../media/split-s02.mp4) | 全部样本自然播完 |
| 03 同场暂停后恢复 | 6.72秒 | 27.755秒 | [观看03](../media/split-s03.mp4) | 场次ID保留，恢复后完整播完 |
| 04 自然回应 | 6.40秒 | 27.339秒 | [观看04](../media/split-s04.mp4) | 完整播完，图片和声音正常配对 |
| 05 云端人格与上下文 | 7.36秒 | 53.678秒 | [观看05](../media/split-s05.mp4) | 真实AI回复、完整播放确认 |

“输入到自然完成”包含排队、文本/语音生成、播放缓冲、语音本身和回执；它不是首音延迟。节选为原速播放，省略生成等待；完整录像保留等待。分机减轻设备竞争，不会使自回归TTS或云端等待变为零。

第五段的真实回复是：“我叫林知夏，刚才测试的是远端生成画面和声音、由本机接收的直播方式。”这确认了本轮身份与同场直播方式记忆；不将一轮确认扩展为完整20轮长期记忆验收。

![跨机接收的实际说话画面；GIF无声、原速](../media/split-response.gif)

## 播放和传输测量

| 项目 | 实测 |
|---|---|
| 人物生成/传输 | 720×1280、25FPS、NVENC H.264 |
| 视频目标码率 | 3Mbps，另加256kbps原样PCM与协议开销 |
| B实际呈现FPS中位数 | 24.883，195个逐秒样本 |
| 最后一个测量窗口FPS | 24.507 |
| 音频缓冲耗尽 | 0 |
| 媒体序号缺失 | 0 |
| 解码错误、跳过图像 | 0、0 |
| 最大收包间隔 | 190.8毫秒 |
| 接收缓冲目标 | 4秒 |
| 重连后 | 新消费者、新关键帧、实际出帧24.823FPS |
| 播放确认 | 五段有效样本与连续已播样本逐项相等，均有自然结束观察 |
| 弹幕去重 | 同一事件重复提交未再次播报 |

195个样本中有6个低于22FPS，包括初始/控制边界和显式暂停恢复；没有声称全程每秒都恒定25帧。普通新一轮输入在前句自然结束后保留安全待机媒体，已消除每轮重新缓冲导致的数秒定格；真实打断仍执行旧音频清空和generation屏障。

较早的一次360秒资源采样，A整机GPU显存峰值13,300MiB、GPU利用率峰值68%、编码利用率峰值1%。其时间窗口独立于最终一轮，不作为所有负载的峰值保证。人物日志记录到约45FPS推理吞吐，最终观看帧率以B呈现计数为准。

## 录像文件和查看入口

完整录像为 **189.758秒、720×1280、25FPS、H.264＋AAC**，已通过完整FFmpeg解码；解码后的音频RMS约0.0388，检出五段独立语音。MP4是B实际接收录像的格式转换，保留原时间关系，没有重配语音或补生成画面。

B正在运行的接收服务提供：

```text
http://127.0.0.1:8020/receiver/evidence/
http://127.0.0.1:8020/receiver/evidence/receiver-full.mp4
```

完整文件位于B项目的忽略目录 `outputs/split-device/receiver-full.mp4`，不随Git发布。五段精简MP4、原速GIF、人物截图和脱敏控制台截图随Git发布。录像页不自动启动媒体、不额外连接人物流，已验证HTTP Range返回206，便于拖动观看。

## 保留的失败与修正

初始JPEG跨虚拟网络约5FPS，不能满足观看要求，因此增加了共享NVENC H264。最初H264长测仍出现一次约2.5秒收包停顿，耗尽2.4秒缓冲；另有一轮在第四段未自然结束而被判定UNKNOWN，未将它伪记为成功。

修正包括：逐线程复用媒体映射HTTP连接池，默认缓冲增至4秒，H264队列不删除参考帧，断线后重取关键帧，闲置阶段保留安全的待机排队媒体。修正后的两轮五段测试均通过，最终轮证据与当前源码哈希关联。早期失败的摘要继续保留在证据JSON中。

## 自动检查

| 检查 | 结果 |
|---|---|
| Node测试 | 2026-10-27恢复修正后82通过、0失败、0跳过 |
| Python测试 | 34通过 |
| 原生HTTP代理/CORS/SSE/取消屏障 | 21条路由及相关契约通过 |
| B控制台、录像页与视频Range | 实际Chrome检查通过，自有上下文已关闭 |
| PowerShell入口 | 语法检查通过；B轻量环境安装、启动、停止/重启已执行 |
| 当前源码与历史证据 | 新增双机证据记录变更，不覆写旧3080/直播姬验收事实 |

## 官方客户端与正式切换边界

目前五段成功实录来自B的原生Chromium测试播放器。B原先运行官方直播姬6.3；已在保留原场景与设置备份后加入独立浏览器素材、源内音频，并静音桌面与麦克风。随后使用签名有效的官方8.11.1.11202程序，账号本人完成Windows管理员确认。该客户端的真实浏览器素材已连接到B网关，AudioContext为running；重连后实际媒体包头确认为H.264。新版独立使用部分`*_v2`画布字段，最终竖屏画布仍需在客户端中核验。

这次官方客户端尝试没有通过：Windows再次锁屏，观察到其呈现帧率约0～1.3FPS；第一段在170秒测试时限内未完成。服务器在16.622秒后已生成7.76秒音频，但从audio_ready到完整自然播放回执相隔171.715秒。后来收到124,160/124,160个完整连续样本与natural_end，也不足以把超时测试判为通过。该失败及时间线保存在`native_livehime`中；它没有覆盖先前成功的五段浏览器验收。

接收控制台新增客户端帧率、实际媒体编码和有限的播放诊断，便于辨认“连接成功但播放迟缓”。这些是运行观察，不能代替客户端录像或观众端验证。**B官方客户端的最终竖屏画布、有声本地录制仍未标记为完成。** 恢复持续可用的桌面后需要重新验收。

本地播放器的心跳、AudioContext运行和完整样本回执，不足以证明其位于官方客户端或观众已收到流。正式验收仍需要：B直播姬的真实有声录制；结束旧实例后的一致正式记忆迁移；有意公开开播后的观众弹幕→可听回复回环。本轮没有自动切换旧3080公开直播。

## 2026-10-27 恢复修正

桌面恢复可用后，旧素材仍停在0FPS。官方CEF日志持续记录`InvalidAccessError`：解码积压分支调用`WebSocket.close(1011)`，而浏览器只接受1000或3000～4999；因此旧页面未能按预期断开、清理和重连。先前的锁屏观察不能单独解释整个故障。

恢复分支改用4001；断线立即释放旧媒体队列。直播姬改为直接显示解码画布并将PCM送至Web Audio默认输出，交给素材源内音频捕获；请求软件H264解码，以排查旧CEF的硬解码停滞。预览保持原MediaStream路径。实际Chrome测试使用一帧自行生成的720×1280 Baseline Annex-B素材和已知PCM信号，验证了软件解码绘图、默认声音输出路径、解码积压后真实WebSocket重连、旧媒体清理及预览兼容；完整回归为82项Node、34项Python通过，自有浏览器上下文均已关闭。测试夹具不冒充女A模型生成录像。

新模式的`canvas_draw`帧率是画布更新计数，不能沿用上方旧录像的`video_presentation`指标解释。以上修正和自动检查也不替代官方客户端的有声录制，最终原生客户端验收仍需另附实际结果。

## English

Five real 4090→virtual-LAN→B speech cases passed, including duplicate rejection, pause/resume, a cloud personality/context reply and media reconnection. The final run measured a median24.883 presentedFPS, with zero audio underruns, missing packets or decode errors. All five utterances received complete contiguous-sample and natural-end acknowledgement. The actual189.758-second H264/AAC recording includes generation waits; linked excerpts are trimmed at original speed.

The official B-client source and its own audible local recording are separate acceptance gates. A genuine source was added with internal audio and muted desktop/microphone. The signed8.11.1.11202 client started after the account owner approved Windows elevation, and real packet headers confirmed H264 after reconnecting. Its locked-desktop attempt failed: approximately0–1.3 presentedFPS, a170-second timeout, and171.715 seconds between a7.76-second utterance becoming ready and its natural playback receipt. That failure remains explicit. The client's final portrait canvas and audible local recording are still unverified. Formal memory ownership and public broadcast remain unchanged until an intentional, consistent cutover.
