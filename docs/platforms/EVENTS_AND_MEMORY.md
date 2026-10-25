# 平台事件、回复调度与记忆

## 输入合同

统一事件输入为 `POST /api/dsh/platforms/events`，应用无登录与令牌要求。该接口用于自己已运行的本地弹幕工具或适配器。官方抖音回调使用专门的原始报文入口，避免 JSON 重排破坏平台签名。

```json
{
  "platform": "bilibili",
  "room_id": "123456",
  "event": {
    "type": "comment",
    "event_id": "platform-message-id",
    "room_id": "123456",
    "user_id": "platform-user-id",
    "nickname": "观众昵称",
    "text": "上次我们聊到的那本书叫什么？",
    "timestamp": 1792926000000
  }
}
```

`events` 数组可替代单个 `event`，每次不超过 1,000 条。时间戳支持毫秒或秒；消息 ID 与平台、房间一起组成去重键。适配器应传平台原生 ID，不能用每次重试时新生成的随机 ID 代替。没有消息 ID 的来源会使用内容、用户、时间和采集会话生成退化键，无法承诺在上游任意重排或缺失时间戳时完美去重。

| 规范字段 | 语义 |
|---|---|
| `platform` | `bilibili`、`douyin` 或 `custom` |
| `room_id` | 平台房间命名空间，不能混用不同房间 |
| `event_id` | 平台原生消息 ID；浏览器缺少该值时使用采集会话内序号 |
| `type` | comment、gift、like、follow、enter、statistics、fansclub、live_start、live_end、other |
| `user_id` | 平台稳定用户标识；不允许用昵称替代 |
| `identity_quality` | `platform_id` 或 `display_only` |
| `occurred_at` | 平台事件发生时间，毫秒 |
| `received_at` | 本地接收时间，毫秒 |
| `source` | browser、blivedm、open_live、official_callback 或 local_relay |
| `request_id` | 回复进入 DSH 后写入，用于追踪本地语音结果 |

## 消息处理和拥塞

1. 在独立的 `state/platforms/control.sqlite3` 中以事务落盘。唯一约束覆盖 `(platform, room_id, event_id)`，进程重启不会清空去重依据。
2. 重复消息只增加重复计数，不再插入，也不再次生成语音。平台事件账本与 DSH 请求账本之间的重复投递使用固定 `idempotency_key=platform-<event_key>`，DSH 再执行一次幂等检查。
3. 默认仅评论进入回复队列。点赞、礼物、关注等事件记录为 `OBSERVED`，可查看统计，不自动逐条读礼物或点赞，也不将其伪装成观众说过的话。
4. 最多保留 50 条待处理消息，可配置到 200；超量输入记录为 `DROPPED/event_queue_full`。默认 45 秒过期，过期消息成为 `EXPIRED`，不追着读旧弹幕。
5. 全局最小回复间隔默认 8 秒，同观众间隔默认 15 秒。所有平台共用一条语音队列，不能为每个平台同时启动一段声音。网页手动输入优先于尚未分发的平台评论。
6. DSH 未就绪、人格渠道未验证、会话暂停、缺少有效播放确认者或已有语音在处理时，等待新一轮分发；等待期间继续计算过期时间。
7. 回复进入既有 `StreamState.accept → activate → 模型生成 → textReady → 本地 TTS → mediaMap → playback.receipt`，不绕过代际栅栏或停止屏障。

`QUEUED` 表示已交给 DSH，不等于已发送到平台。回复账本最终同步 COMPLETED、FAILED、EXPIRED、CANCELLED、INTERRUPTED 或 UNKNOWN 等状态。`COMPLETED` 的中文显示为“本地播完”。

## 观众身份与上下文

稳定身份采用：`viewer:<platform>:sha256([room_id,user_id])`。相同昵称不会合并身份；两家平台的相同数字 ID 也不会共享个人记忆。不同房间默认分开，不推测跨房间用户关联。

浏览器页面可能只显示昵称、平台可能对游客隐藏 UID。此时使用房间的公开输入路径，而不构造“昵称即身份”的长期个人档案。公共直播中的声音始终可能被所有平台的观众听到；记忆分区控制检索范围，不会把公开播报变成私聊。

原始评论作为 `input.accepted.text` 保存，平台、房间、消息 ID、昵称、身份质量与采集来源作为 `source` 元数据保存。元数据以数据形式进入当前请求的 `viewer_source`，不会作为系统指令、工具授权或人格修改命令执行。

当前请求只检索对应平台观众的已确认记忆及明确公开的角色/房间记忆。完整的助手话语仍以连续样本和自然结束的本地播放确认为依据；模型生成后尚未播出的内容不变成已经说过的话。

## 下播后的记忆

平台输出服务拥有的最后一路输出结束后，使用既有广播版本号调用 DSH 结束会话。先排空当前句，再产生唯一 `broadcast.ended` 水位；之后等待既有 2 分钟静默窗口，创建每个观众分区与公开分区的离线压缩任务。

压缩、冲突候选、合并、回滚、删除栅栏、夜间整理和预算继续遵守 [DSH + Humanity 方案](../DSH_HUMANITY.md)。不会把原始平台弹幕库当作未经核对的个人事实批量灌入 Humanity。未进入 DSH 的过期、过载、点赞和礼物事件也不会因为事后存在于平台账本中就被自动压缩成对话记忆。

为避免干扰已有会话：如果本地会话原本由网页启动，平台模块记录 `owned_broadcast=false`，结束平台输出时不擅自结束原网页会话。多个受本模块管理的平台同时使用一场会话时，最后一路结束才结束本模块创建的会话。

## 官方抖音回调

入口：`POST /api/dsh/platforms/douyin/callback`。必需请求头：`x-msg-type`、`x-nonce-str`、`x-roomid`、`x-timestamp`、`x-signature`。使用实际收到的 body 字节，按官方算法计算：

```text
prefix = 按头名升序拼接 x-msg-type、x-nonce-str、x-roomid、x-timestamp
signature = Base64(MD5(prefix + 原始body + callback_secret))
```

验签后同步写入事件账本即返回 2XX；模型、语音与播放都不在回调应答内执行。平台要求快速确认，因此不能等待一段 AI 回复完成才回包。过期或不匹配的原始报文返回明确错误；这是平台协议验证，与应用管理员登录无关。

公网抖音回调不能直接访问 ZeroTier 私网地址。正式接入时，使用已有公网 HTTPS 入口将**原始 body 和上述请求头**转发到本地入口；不要在云端执行语音、人物或 LLM 人格逻辑。公网转发、域名和应用权限必须按真实部署验证。
