# 架构与接口 / Architecture and interfaces

## 控制分层 / Control layers

| 组件 / Component | 职责 / Responsibility | 不承担 / Excluded |
|---|---|---|
| `native_bridge.py` / `.js` | 附加唯一指定进程；读取 Lua 状态；传递普通菜单键；捕获原生帧 / Attach the selected process, read Lua state, deliver normal menu keys, capture native frames | 不扫描其他安装、不改变前台 / No attachment to other installations or forced foreground |
| `build_native_controller.py` | 将六个游戏侧源文件组装成内存输入回调 / Assemble six sources into in-memory input callbacks | 不执行 RegisterMod、FireTear、属性修改或解锁写入 / No RegisterMod, tear spawning, stat edits or unlock writes |
| `mods/IsaacJev/` | 即时避险、射击/蓄力、地形、输入租约；发布观察 / Immediate safety, weapons, terrain, input lease, telemetry | 不等待模型完成才能避险 / Never waits for inference before dodging |
| `src/isaac_jev/runtime.py` | 现有本地策略、候选与路线 / Local policy, candidates and routing | 实时 provider 固定 local，shadow 关闭 / Real-time provider remains local; shadow is off |
| `strategy.py` / `strategy_server.py` | 状态缓存、12 类机会、预算/上下文验证、效果回执 / Cache, offers, validation and effect receipts | 不在帧路径请求模型 / No model network call on the frame path |
| `dsh-host/isaac-plugin/` | 官方 DSH 单 agent、4 工具、短编号绑定、事件驱动 / Official DSH agent, four tools, short references, event-driven turns | 无任意终端、文件、Lua、按键工具 / No arbitrary terminal, file, Lua or key tools |

Frida attaches to the tested 32-bit game and schedules Lua evaluation through the existing native bridge. Normal action callbacks are the only gameplay execution path. This is state-assisted automation, not a vision-only agent. Source `main.lua` retains upstream Mod form for compatibility; the generated native bundle replaces its registration and removes direct firing/movement fallbacks.

## 状态与新鲜度 / State and freshness

`isaac_get_state` 支持 13 个主题：`state`, `health`, `inventory`, `effects`, `history`, `actives`, `pockets`, `map`, `room`, `enemies`, `bosses`, `pickups`, `resources`。每次查询附带连接状态、帧和上下文。生命以半心为单位；药丸未识别时保持未知。

The 13 topics expose health in half-hearts, inventory/effects, recent room observations, actives and pockets, discovered map, room and floor identity, enemies/bosses, pickups and resources. Unknown information remains unknown. Active and pocket slots 0–3 can be observed; only slot 0 is currently executable. State comes from a local cache refreshed by normal telemetry, not a synchronous model-side native RPC.

地图公开列表过滤未发现房间，但旧 `bomb_walls` 候选使用相邻隐藏房引擎数据。这个信息优势必须在任何比较中披露，后续严格盲玩模式需要独立开关和测试。

The public map list filters unseen rooms, but legacy `bomb_walls` candidates consult adjacent hidden-room engine metadata. That advantage must be disclosed; a strict blind-exploration mode remains future work.

## 一次完整决策 / A complete decision

1. 本地依据当前状态构造有效 offers，记录局种子、重开、楼层、维度、房间、桥实例、背包与目标身份。 / Construct offers with run, restart, floor, dimension, room, bridge incarnation, inventory and target identity.
2. 官方 DSH 插件读取并绑定真实决策，附上相关机制、成本和上下文。 / Fetch and bind the authoritative decision before inference.
3. Agent 使用 `isaac_get_state` 或 `isaac_lookup` 按需补充信息；信息充分时直接提交一次。 / Query only when needed; submit directly when sufficient information is attached.
4. `DecisionBinding` 将 `A1` 等短编号解析为本轮完整身份和幂等计划号。 / Resolve the short reference to the exact observed identities and idempotent plan ID.
5. 本地拒绝过期、换房、库存变化、价格变化、费用不足、未知生命语义、失联和危险抢占。 / Reject stale context, inventory/price changes, insufficient budget, unknown health semantics, stale state or danger preemption.
6. 输入执行与意图分开；仅在生命、充能、目标、房间等相应状态变化后确认效果。 / Execute normal input separately from intent; acknowledge the relevant observed effect.

```json
{
  "offer_ref": "A2",
  "reason": "保留生命，选择当前可执行的免费路线 / preserve health and take a valid free route",
  "budget": {"coins": 0, "keys": 0, "bombs": 0, "health_half_hearts": 0},
  "execution_seconds": 12
}
```

该示例不能直接用于实际操作：A2 的含义依赖本轮绑定；预算必须覆盖该 offer 的实际费用。负数商店价格表示生命成本，不是免费。 / This example is not reusable authorization: A2 is turn-specific and the budget must cover the actual offer. Negative shop prices represent health costs, never free items.

## 期限与回执 / Deadlines and receipts

| 项目 / Item | 当前约定 / Current behavior |
|---|---|
| 即时控制 / Immediate control | 游戏本地逐帧；Python 宏观调度 6 Hz；状态发布最少间隔 3 帧 / Per-frame game-local checks, 6 Hz Python macro scheduling, telemetry at least three frames apart |
| 事件检查 / Event check | DSH 每 250 ms 检查机会；这不是模型调用周期 / DSH checks every 250 ms; this is not the inference period |
| 判断期限 / Decision deadline | 默认 45 秒，可设 5–60 秒；无新机会不调用 / Default 45 seconds, configurable 5–60; no new opportunity means no call |
| 输入执行 / Execution | 默认 12 秒，最多 20 秒；每次输入复核 / Default 12 seconds, capped at 20, with local rechecks |
| 输入租约 / Input lease | 1.5 秒；旧输入不无限持续 / 1.5 seconds; stale input cannot persist indefinitely |
| 控制器失联 / Controller loss | 游戏侧在约 5 秒后请求普通暂停；必须观测稳定帧 / Game-local logic requests normal pause after about five seconds; stable pause must be observed |
| 会话 / Sessions | 一个 agent，每四轮换短会话；局内历史留在本地 / One agent, session rotation every four turns, local run history retained |

`observed`: 只在回放校验，不执行游戏。`accepted`: 真实计划已接收，尚未证明效果。`succeeded`: 相应效果已观测。`failed`/失效/超时表示没有成功证明，不允许据此重复消耗一次性资源。

`observed` validates replay only. `accepted` queues a live plan. `succeeded` records the relevant observed effect. Failure/expiration does not authorize retrying an irreversible action.

## 本机端口 / Loopback ports

| 端口 / Port | 接口 / Interface |
|---|---|
| 9528 | 游戏原有状态/输入桥 / Existing game telemetry and input bridge |
| 9529 | 本地控制面板 / Legacy local controller panel |
| 9532 | 只读观察页；`/status`, `/query?topic=...`, `/decision`, `/events?after=...`, `/lookup?kind=...&id=...`, `/host-status`；授权 POST `/plan`, `/control` |
| 9533 | DSH 状态 `/status`；授权 `/control`, `/run`, `/cancel` / DSH status and operator control |

Mutation endpoints require `X-Isaac-Token`; browser-origin writes are rejected. Services bind IPv4 loopback. GET state is intentionally readable by local processes: do not expose these ports externally. `host-status` returns an explicit field allowlist, omitting private session IDs and raw provider errors.

## 扩展流程 / Extending the system

新增机制先完善游戏观察，再登记已知语义和能力，再构造带预算/身份 guard 的 offer，最后加入普通输入执行和效果检测。先用回放验证过期、资源、上下文与重复提交，再做授权槽自然实机测试。不能只添加模型提示词就宣称支持。

For a new mechanic, add observation, known semantics and capabilities, guarded/budgeted offers, normal-input execution and effect detection. Test stale state, costs, context and idempotency in replay before authorized natural live testing. Prompt changes alone do not establish support.
