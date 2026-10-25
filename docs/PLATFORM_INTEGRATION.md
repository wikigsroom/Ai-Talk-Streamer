# 直播平台接入 / Live platform integration

本方案将女A「林知夏」接入哔哩哔哩、抖音和提供 RTMP/RTMPS 推流地址的其他平台。运行于原生 Windows，复用本地 MuseTalk、MOSS 04 与 DSH + Humanity；文字模型继续使用演播台已保存的云端渠道。无需 Docker、WSL、云端数字人或云端语音。

**当前账号条件：已有直播账号和开播权限，尚无开放平台应用。** 因此，基础接入不依赖申请开放平台应用；官方弹幕接口作为可切换的适配器提供。平台的账号登录、推流码、应用密钥属于平台自身连接参数，网页与应用后端仍然无需管理员登录。

## 方案评估

| 平台 / 路径 | 画面与声音 | 互动输入 | 当前账号能否使用 | 适用情况 |
|---|---|---|---|---|
| B站：OBS + blivedm | OBS 浏览器源直接采集本地画面与声音，使用账号提供的 RTMP/RTMPS 地址推流 | 原生 Python blivedm Web 弹幕客户端；可填写自己的 B站 Cookie | 有推流信息即可发送画面；匿名弹幕的身份可能被平台打码 | 当前阶段优先使用，平台 ID 可用时支持观众记忆 |
| B站：OBS + 网页采集 | 同上 | 独立本地浏览器读取直播间新渲染的评论 | 无需开放平台应用；平台要求登录时，在独立窗口登录 | 不想填写 Cookie 或 Web 客户端暂时失效时 |
| B站：官方开放平台 | 同上 | `/v2/app/start`、项目心跳、官方消息长链和 `/v2/app/end` | 需要获批应用、开发密钥与主播身份码 | 后续正式应用接入 |
| 抖音：直播伴侣 + 网页采集 | OBS 窗口化投影作为直播伴侣窗口源；OBS 音频监听到桌面播放设备，再由直播伴侣采集 | 独立本地浏览器读取自己的直播间新评论 | 已有直播伴侣开播权限即可配置；网页登录按平台提示处理 | 无开放平台应用时的基础方案 |
| 抖音：已有推流地址 | OBS 直接推流，独立采集弹幕 | 网页采集 / 已有弹幕工具 / 官方回调 | 仅在账号实际提供有效第三方推流地址时可用 | 已获对应能力的账号；系统不生成或破解推流码 |
| 抖音：官方直播互动数据 | OBS 或直播伴侣输出不变 | 官方数据推送 HTTP 回调，本地原始报文验签、落库、去重 | 需要相应应用、挂载及评论数据权限 | 取得开放平台资格后替换采集输入 |
| 其他平台 | 填写该平台提供的 RTMP/RTMPS 服务器与推流码，复用同一个 OBS 场景 | 统一事件 HTTP 接口或现有 WebSocket 弹幕工具 | 取决于账号提供的推流与消息能力 | 后续接入视频号、快手或其他平台，不虚构通用弹幕权限 |

OBS 虚拟摄像头只提供视频。抖音基础方案单独处理音频，不能把“摄像头出现人物”视为“声音接入成功”。B站官方消息长链、抖音官方数据回调都存在独立的应用准入要求，普通开播权限不会自动获得这些权限。

## 实现组成

```mermaid
flowchart LR
  B["B站 Web / 官方长链"] --> E["平台事件规范化与 SQLite 去重"]
  D["抖音网页 / 官方回调"] --> E
  R["其他弹幕工具 HTTP / WebSocket"] --> E
  E --> Q["节流、过期与待回复队列"]
  Q --> H["DSH + Humanity：人格、上下文、分区记忆"]
  H --> L["已配置的云端文字模型"]
  L --> T["本地 MOSS 04 + MuseTalk"]
  T --> O["OBS 干净竖屏源"]
  O --> BILI["B站 / 通用 RTMP"]
  O --> P["窗口化投影 + 桌面音频"]
  P --> DY["抖音直播伴侣"]
  O --> A["本地连续样本播放确认"]
  A --> H
```

所有平台共用同一个人物、语音和对话生成队列，不为每个平台加载一份模型。OBS 硬件编码会额外使用少量显存；需要在当前 10GB RTX 3080 上按实际峰值验收，不能由“NVENC 是硬件编码”推断为零显存开销。

| 部件 | 源码 / 入口 | 职责 |
|---|---|---|
| 平台控制页 | [web/platforms.html](../web/platforms.html) | 保存连接参数、准备 OBS、检查链路、开停输出、管理弹幕和回复节奏 |
| 平台生命周期 | [manager.mjs](../backend/platforms/manager.mjs) | 接入现有 Bridge，控制平台输出、交互排队与本地会话 |
| 本地参数 | [config.mjs](../backend/platforms/config.mjs) | 私有配置落盘，读取接口不返回密钥与 Cookie |
| 平台事件账本 | [store.mjs](../backend/platforms/store.mjs) | 跨进程重启的去重、事件状态和输出所有权记录 |
| OBS 控制 | [obs.mjs](../backend/platforms/obs.mjs) | OBS WebSocket 5.x，场景准备、录制、投影与推流 |
| B站 Web 客户端 | [blivedm.mjs](../backend/platforms/blivedm.mjs)、[Python 适配器](../scripts/platform_blivedm.py) | 隔离的 CPU Python 环境，Cookie 通过 stdin 传递 |
| B站官方接口 | [bilibili.mjs](../backend/platforms/bilibili.mjs) | 签名、项目生命周期、二进制长链、压缩包解析和重连 |
| 网页评论采集 | [browser.mjs](../backend/platforms/browser.mjs) | 独立浏览器资料目录、只接收新评论、可改选择器、停止时关闭窗口 |
| 抖音官方回调 | [douyin.mjs](../backend/platforms/douyin.mjs) | 原始 body 验签、时间检查、批量事件转换 |
| 第三方弹幕工具 | [relay.mjs](../backend/platforms/relay.mjs) | WebSocket 输入及常见 Type/Data 消息适配 |
| 完整操作说明 | [部署](platforms/DEPLOYMENT.md)、[事件与记忆](platforms/EVENTS_AND_MEMORY.md)、[运行手册](platforms/OPERATIONS.md)、[验收](platforms/ACCEPTANCE.md)、[实机媒体](platforms/MEDIA.md) | 配置、启停、诊断与证据范围 |

## 使用顺序

1. 打开工作站的 `/platforms`。访问地址为 `http://<WORKSTATION_IP>:8010/platforms`。
2. 选择平台，保存自己的直播间公开链接。B站选择“OBS 直接推流”，填写平台提供的服务器与推流码；抖音没有推流地址时选择“直播伴侣采集画面”。
3. 点击“准备竖屏画面”。系统启动项目 OBS，创建 `AiTalk Vertical` 场景，使用 `AiTalk Avatar` 浏览器源，设置 720×1280、25 FPS 与人物声音。此步不公开开播。
4. 点击“检查连接”，确认人物、语音、AI 渠道与 OBS 就绪。正式开播前可先本地录制，核对声音、嘴型和帧率。
5. B站点击“开始向平台推流”；抖音点击“准备直播伴侣画面”，在直播伴侣选择 OBS 窗口化投影与相应桌面音频，核对后在直播伴侣开播。
6. 开始接收弹幕。第一次用网页采集时，可选择“打开房间并登录”。窗口位于运行采集的工作站；不接管个人浏览器。只有平台需要时才登录平台。
7. 在另一台设备的观众端检查实际画面、声音、平台延迟和评论回应。OBS 本地推流状态不等于观众端已验收。
8. 下播时结束平台输出，并停止弹幕采集。直播伴侣输出还需在直播伴侣自身结束。系统拥有的最后一路平台会话结束后，调用 DSH 的结束/排空流程，再进入既有的静默窗口与离线记忆整理。

### 同时使用 B站和抖音

OBS 原生主输出一次配置一个 RTMP 目标。可用 OBS 主输出给 B站，同时让抖音直播伴侣采集同一个 OBS 投影与声音；人物推理仍只有一份。两端看到相同的人物和回复。并行推流的上行带宽按两路实际码率之和计算，外加网络余量。

不通过反复修改 OBS 推流目标实现多路并行。多个 RTMP 目的地需要独立的转推器或多输出插件，属于不同的传输部署；本项目对“其他平台”提供可选择的主目标，不把单主输出称为任意多路转推。

## 保留的业务约束

应用仍为无鉴权模式。保留的数据格式校验、OBS 已有输出检查、单条语音队列、播放确认租约、广播版本号和记忆分区，是防止重复播报、破坏录制与记忆串线的业务一致性规则。

平台网页 DOM 可能变化，也可能需要平台登录或显示验证码。采集器报告 `WAITING_FOR_CHAT`、`ERROR` 或 `RECONNECTING`，不会把“浏览器进程存在”当作弹幕已到达。可以在设置中更新选择器，切换 B站 Web 客户端或官方接口；不调用外部签名售卖服务。

## 官方资料与开源来源

资料核对日期：2026-10-25。平台账号最终能使用哪些能力，以该账号实际显示的开播配置和开放平台授权为准。

- [B站开放平台项目开启、结束与心跳](https://open-live.bilibili.com/document/eba8e2e1-847d-e908-2e5c-7a1ec7d9266f)：获取 `game_id` 与长链信息，20 秒项目心跳，结束时调用 end。
- [B站消息长链协议](https://open-live.bilibili.com/document/657d8e34-f926-a133-16c0-300c1afc6e6b)：AUTH、30 秒长链心跳与压缩消息。
- [blivedm 上游](https://github.com/xfgryujk/blivedm)：MIT；固定提交 `3bf17fe862b8c2fc6bc04c81c3f0c5db95de93d6`，版本 1.1.7；上游明确未发布至 PyPI，本项目从官方 Git 仓库安装。
- [抖音直播伴侣官方下载](https://streamingtool.douyin.com/)：Windows 主播端画面和声音接入。
- [抖音直播间数据开放说明](https://developer.open-douyin.com/docs/resource/zh-CN/interaction/develop/server/live-room-scope/data-open/data-open-desc)：任务准入、评论/点赞/礼物回调、原始 body 签名及应答时限。
- [抖音互动工具开发者指南](https://developer.open-douyin.com/docs/resource/zh-CN/live-interactive-tools/development/tutorial/live-tool-guide)：直播伴侣互动数据需相应权限，不等同于普通账号任意读取。
- [OBS WebSocket 官方协议](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md)、[远程控制指南](https://obsproject.com/kb/remote-control-guide)、[虚拟摄像头指南](https://obsproject.com/kb/virtual-camera-guide)。

## English overview

The native Windows platform module reuses the existing local avatar, MOSS 04 speech and DSH + Humanity conversation/memory services. Bilibili uses an OBS RTMP/RTMPS output; Douyin can capture the same OBS program through its official Live Companion. Video and audio are configured separately for Companion capture.

Without an approved developer application, use Bilibili's pinned MIT-licensed `blivedm` Web client or the isolated browser collector. The Douyin browser collector reads newly rendered comments in the user's own room. Official Bilibili Open Live and Douyin callback adapters are also implemented, but they need the platform's application permissions and credentials. The UI and application API remain open, without an administrator login.

Platform events enter a persistent de-duplication ledger, a bounded expiring queue and the existing DSH speech pipeline. Stable user IDs are namespaced by platform and room; display names alone never create a persistent personal identity. Playback acknowledgements describe local output consumption, not verified delivery to the platform audience. See the linked deployment, operations and acceptance documents for configuration and evidence boundaries.
