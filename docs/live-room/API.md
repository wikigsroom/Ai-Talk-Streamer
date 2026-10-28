# Room API

[操作手册](RUNBOOK.md) · [架构](ARCHITECTURE.md)

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
| POST | `/messages` | action=`create/pin/unpin/feature/unfeature/hide/restore/answered/next/clear_tests` |
| POST | `/speak` | `{text,mode:"echo"或"chat",idempotency_key}`；202 进入已有 DSH 请求链 |
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

## 参数边界

| 组 | 字段范围 |
| --- | --- |
| identity | title≤40、topic≤80、announcement≤240 字符；show_virtual_label 布尔 |
| audio | music_volume 0–1；speech_volume 0–1.5；duck_level 0–1；attack_ms 20–1000；release_ms 100–3000；muted/ducking 布尔 |
| filters | brightness 0.65–1.35、contrast 0.7–1.4、saturation 0–1.6、warmth -0.5–0.5、softness 0–1.2、vignette 0–0.6 |
| overlay | theme daylight/paper/evening；opacity 0.3–1；font_scale 0.8–1.3；max_comments 整数 1–5；comment_lifetime 5–90 秒；danmaku_speed 6–24 秒；gift_seconds 3–20 秒；其余开关布尔 |
| moderation | blocked_words/blocked_names/blocked_users 各最多 200 条；非空、去重；普通项≤80、user_key≤100 字符 |

CSS 轻柔度是轻量画面模糊，不是皮肤分割美颜；冷暖是 CSS 色彩近似，不是物理色温模型。字幕按采样进度分页，不是逐字对齐。

## 错误与恢复

`ROOM_CONFIG_CONFLICT_REFRESH`=409 过期修订；`AGENT_BUSY`=409 已有私聊生成；`ROOM_PLAYER_NOT_PROGRAM`=409 非当前正式消费者或过期回执；`AUDIO_UPLOAD_BUSY`=409 上传占用；`ROOM_BODY_TOO_LARGE`/上传超限=413；格式、范围、未知字段=400；不存在路由=404。其他 DSH 错误（例如 `BROADCAST_NOT_LIVE`）仍按既有状态机处理，先建立本地会话再提交。
