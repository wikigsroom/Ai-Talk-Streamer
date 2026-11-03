# Room API

[操作手册](RUNBOOK.md) · [架构](ARCHITECTURE.md)

MC正式节目新增的准备播放权/确认就绪协议见[正式播放就绪握手](../technical/mc-live-v1/正式播放就绪握手与故障诊断.md)。其路径为`/api/dsh/playback/claim`及`/api/dsh/playback/ready`，属于DSH播放接口；Room修订、音量与实际人声收据继续使用各自原契约。

所有路径都在现有 A8010 或 B8020 同源代理下，以 `/api/dsh/room` 为前缀；DSH 内部监听 3092。沿用用户要求的无登录应用模式。没有新增管理 token、角色或登录 Cookie。房间状态修订和播放消费者核对用于防止过期数据/错误回执，不是用户鉴权。

## 路由

| 方法 | 后缀 | 请求或响应 |
| --- | --- | --- |
| GET | `/state` | schema_version、version、revision、settings、music、tracks、board、最近 100 messages、agent job、player、broadcast、active、caption、storage_error |
| GET | `/events` | text/event-stream；snapshot/state/message/agent；重连先发送快照，不回放礼物动画 |
| POST | `/config` | `{expected_revision, patch}`；只修改指定组/字段 |
| GET | `/export` | `{schema_version:1,settings,exported_at}`；不含私聊/音频/密钥 |
| POST | `/import` | `{schema_version:1,expected_revision,settings}`；完整字段校验 |
| POST | `/reset` | `{expected_revision}`；恢复默认设置，不删除曲库和消息 |
| POST | `/music` | action=`play/pause/seek/next/previous/repeat/shuffle/order` |
| POST | `/tracks/upload?name=...` | 原始音频 bytes，非 multipart；返回 201 音频索引 |
| GET/HEAD | `/audio/{id}` | Content-Type、Content-Length、Accept-Ranges；合法单 Range 返回 206，不合法返回 416 |
| POST | `/tracks/delete` | `{id}`；仅自建曲目 |
| POST | `/messages` | action=`create/pin/unpin/feature/unfeature/hide/restore/handled/answered/next/clear_tests`；handled及旧answered只标记已处理 |
| POST | `/speak` | `{text,mode:"echo"或"chat",idempotency_key,message_id?}`；202 进入已有DSH请求链，可关联当前可用留言 |
| GET | `/agent` | 当前私聊会话最近 40 条 history 与 job |
| POST | `/agent` | `{action:"send",text}`、`{action:"cancel"}`、`{action:"new"}`；202，异步 job |
| POST | `/test-event` | `{type:"comment"或"gift"或"follow",text}`；本地显示测试，不生成正式回复 |
| POST | `/player` | 正式素材的 consumer_id 与受限 mixer 观测字段；拒绝非当前正式消费者 |
| GET | `/audit` | 最近 100 条后台操作审计 |
| POST | `/panic` | 取消当前及排队回复、暂停音乐、总静音 |

普通 JSON 请求最多 128 KiB；音频上传走独立流式路径，最多 128 MiB、每次一个。接口返回错误 code；页面展示该 code，不把失败伪装为保存成功。

## 示例

先 GET `/state`，取得当前 revision，再更新：

```json
{
  "expected_revision": 12,
  "patch": {
    "identity": {"title": "知夏的日光宿舍", "topic": "今天最开心的一件小事"},
    "audio": {"music_volume": 0.22, "ducking": true},
    "overlay": {"theme": "daylight", "max_comments": 3}
  }
}
```

音乐命令示例：

```json
{"action":"play","track_id":"daylight-notes"}
```

```json
{"action":"seek","seconds":10}
```

```json
{"action":"repeat","value":"all"}
```

```json
{"action":"order","ids":["daylight-notes","window-breeze","small-weekend"]}
```

留言示例：

```json
{"action":"create","text":"今天也一起，把平凡的小事过得有趣。","nickname":"导播留言","feature":true}
```

上墙已有消息用 `{action:"feature",id}`；置顶用 `pin`；清理测试只删除 test=true 的消息，不清除普通观众历史。`/speak` 必须有本地 LIVE 会话，不能绕过 DSH 生命周期或播放回执。

手工“已处理”、切换下一条、DSH入队及文本生成均不能标记answered。可选message_id关联留言，只有有效正式PCM完成事件及请求/utterance完成证明才将关联留言标为已播完；来源全部隐藏/屏蔽/移除时取消原请求。旧版未核验answered标记一次性迁移为handled，保留留言。MC任务及互动回应沿用同一链路，见[口播实现说明](../technical/mc-live-v1/任务结果与公开口播.md)；正式本地完成不代表观众CDN已经播放。

## 参数边界

| 组 | 字段范围 |
| --- | --- |
| identity | title≤40、topic≤80、announcement≤240 字符；show_virtual_label 布尔 |
| audio | music_volume 0–1；speech_volume 0–1.5；duck_level 0–1；attack_ms 20–1000；release_ms 100–3000；muted/ducking 布尔 |
| filters | brightness 0.65–1.35、contrast 0.7–1.4、saturation 0–1.6、warmth -0.5–0.5、softness 0–1.2、vignette 0–0.6 |
| overlay | theme daylight/paper/evening；mc_chat_side left/right（默认right，MC留言与礼物侧边）；opacity 0.3–1；font_scale 0.8–1.3；max_comments 整数 1–5；comment_lifetime 5–90 秒；danmaku_speed 6–24 秒；gift_seconds 3–20 秒；其余开关布尔 |
| moderation | blocked_words/blocked_names/blocked_users 各最多 200 条；非空、去重；普通项≤80、user_key≤100 字符 |

CSS 轻柔度是轻量画面模糊，不是皮肤分割美颜；冷暖是 CSS 色彩近似，不是物理色温模型。字幕按采样进度分页，不是逐字对齐。

MC横屏弹幕位置通过现有POST /config提交，例如patch为 {"overlay":{"mc_chat_side":"left"}}，同时带当前expected_revision。服务端持久化并通过现有SSE同步；旧配置缺字段补right，非法侧边返回400，过期修订仍返回409。位置控制只移动MC留言／礼物容器，不重建消息、触发口播或改变顶部飘屏方向。MC布局定义见[设计定稿](../design/mc-landscape-v1/定稿说明.md)；完整MC正式输出仍需单独实施和实机验收。

## 错误与恢复

`ROOM_CONFIG_CONFLICT_REFRESH`=409 过期修订；`AGENT_BUSY`=409 已有私聊生成；`ROOM_PLAYER_NOT_PROGRAM`=409 非当前正式消费者或过期回执；`AUDIO_UPLOAD_BUSY`=409 上传占用；`ROOM_BODY_TOO_LARGE`/上传超限=413；格式、范围、未知字段=400；不存在路由=404。其他 DSH 错误（例如 `BROADCAST_NOT_LIVE`）仍按既有状态机处理，先建立本地会话再提交。

## room-v1.3平台消息字段

MC分支024轮兼容增加platform_message_id、platform_fields和platform_deleted，既有Room HTTP及SSE路径不变，页面/API继续无应用认证。公共消息结构见[RoomMessage](../technical/mc-live-v1/contracts/game.schema.json)，完整来源和撤回语义见[平台事件来源与撤回](../technical/mc-live-v1/平台事件来源与撤回.md)。

025轮保存moderation过滤配置后立即复核游戏互动来源，撤回失效选票、重算建议当前支持，并沿用口播取消/来源复核；非过滤的换边/滤镜/声音配置不触发此完整扫描。后台区分历史累计、当前有效事件、可识别账号和身份未知事件。解除过滤不重投旧票、不重开已取消建议，也不提交游戏任务。完整语义、容量、旧数据和临时不可用处理见[建议支持与过滤联动](../technical/mc-live-v1/建议支持与过滤联动.md)；真实平台与声音仍须联合验收。

gift_name/gift_count缺依据时为null，不再默认礼物数量1。SC金额为整数分，角色为平台报告值，表情含文字替代和受限HTTPS图片；中继字段不能自报可信等级。未知值及其原因位于platform_fields.field_status/unknown_fields。原始平台UID不公开，现有稳定user_key继续用于关联。

平台SC撤回经采集器进入，不新增应用登录或观众控制入口。被撤回消息platform_deleted=true、hidden=true，既有messages恢复操作返回MESSAGE_PLATFORM_DELETED。已证明确实播完的历史answered保留；未播完的撤回不会制造answered。旧消息无字段来源时以未知投影，原存储内容保留。真实平台、官方直播姬和声音完成仍须单独验收。

## 隐私删除与待完成恢复

026轮沿用既有记忆删除接口，增加Platform/Room/Game持久删除投影。它清除原消息及其个人载荷，不等同SC撤回后的隐藏。跨库投影、删除账本或Humanity REMOVE未确认时，Room状态/SSE暂时返回空留言、空板卡个人内容及空字幕；只读状态与订阅可用，Room写入和平台采集返回503 `MEMORY_PRIVACY_PENDING`。完成后恢复显示实际保留消息。

同一删除operation_id原参数可重试，不增加代次。无法确认旧Room行归属返回`MEMORY_PRIVACY_COVERAGE_INCOMPLETE`，Humanity移除未确认返回`MEMORY_PRIVACY_MIRROR_PENDING`；状态保持待完成，不用同昵称推断账号。旧缓存/旧备份加载前重放删除计划；已删除事件即使原行清理后重来仍被丢弃，删除截止之后的新消息可正常进入。页面/API继续无应用认证。完整来源与边界见[多人记忆及删除恢复](../technical/mc-live-v1/多人回应记忆与删除恢复.md)。

## 观众历史维护

- `GET /api/dsh/platforms/retention`：固定保留规则、归属数量、隐私恢复状态、最后一次及最近20次运行。
- `POST /api/dsh/platforms/retention`：仅接受空对象`{}`，执行一次有界维护；禁止客户端传入cutoff/limit，非法请求400，维护/隐私恢复中503。
- `GET /api/dsh/platforms/status`：增加`history_retention`，保持免应用登录。

报告区分completed、remaining、failed、interrupted，数量为本次已确认结果；跨库失败保留阶段与待撤回来源，重试先补完撤票/支持/口播/快照。固定7天平台保留与Room7天/至少500/最多5000规则、来源保护和实际未验边界详见[维护契约](../technical/mc-live-v1/观众历史维护与账号归属.md)。
