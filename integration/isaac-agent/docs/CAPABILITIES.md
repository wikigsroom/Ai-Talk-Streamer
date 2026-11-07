# 决策、响应期限与覆盖 / Decisions, deadlines and coverage

**Jev 不是当前任何操作的必要依赖。即时控制必须由本地执行，Luna 只处理可等待的意图选择。 / No operation requires Jev in this build. Immediate control is local; Luna handles deliberative intent selection.**

“控制周期”是执行器重新检查动作的频率；“判断期限”是一个机会允许模型思考多久。两者不能互换。下面的 45 秒来自当前配置，并不代表各种决策存在统一的生理或物理响应要求。早期成功模型样本耗时 6.9–33.2 秒，所以不能用于瞬时救命。

A control cycle is how often the executor revisits an action. A decision deadline is how long an opportunity remains valid. The default 45 seconds is a configured budget, not a physical requirement shared by every decision. Earlier successful model samples took 6.9–33.2 seconds and cannot serve as emergency reactions.

| 决策 / Decision | 何时触发 / Trigger | 模型期限 / Model deadline | 控制周期下限与即时责任 / Local execution granularity | Luna 判断 / Luna suitability | 自然实机证据 / Natural live evidence |
|---|---|---|---|---|---|
| 主动 / Active | 可用充能、已知机制；战斗主动仅在战斗中 / Ready known active; combat item only in combat | 默认 45 秒；危险/状态变化可提前失效 / 45 s default; context can invalidate earlier | 普通键单次/边沿；状态与危险逐帧检查 / Normal one-shot/edge input, per-frame safety | 非紧急取舍可以；即时保命不可以 / Yes for non-emergency choices | 本次未覆盖全部主动 / Not all actives covered |
| 一次性/重骰/传送 / Special active | 有目标且安全 / Relevant target and safe context | 45 s default, configurable 5–60 | 单次输入，执行后重新观察 / One shot, then observe again | 可以，但未知机制拒绝 / Yes; unknown semantics rejected | 稀有自然样本不足 / Limited rare live samples |
| 拾取组合 / Pickup | 清场、安全、目标可达 / Clear safe room and reachable target | 45 s default | 目标一次选择，接近与避险逐帧 / Select target once; per-frame approach/safety | 可以；没有完整协同数据库 / Yes; incomplete synergy knowledge | 历史硬币拾取成功 / Earlier real coin pickup |
| 药丸 / Pill | 已识别、效果支持、槽 0 / Identified supported pill in slot 0 | 45 s default | 普通口袋键单次，核对效果 / One pocket input and effect check | 已识别非紧急效果可以 / Yes for identified non-emergency effects | 尚无全部效果自然覆盖 / No exhaustive live coverage |
| 卡牌/符文 / Card/rune | 已知槽 0 物品；满足战斗/安全条件 / Known slot-0 item in valid context | 45 s default | 单次输入，传送立即作废旧上下文 / One input; teleport invalidates context | 可以；危险/未知效果拒绝 / Yes; dangerous/unknown effects excluded | 尚无全部效果自然覆盖 / No exhaustive live coverage |
| 房间路线 / Route | 清场后出现有效门 / Valid doors after clear | 45 s default | 目标门一次选择；逐帧走位 / Choose door once, move locally per frame | 可以；需评估循环与探索收益 / Yes; looping/utility remain concerns | 历史 71→84 成功；本次本地经过五房 / Earlier DSH 71→84; current local five-room sample |
| 天使/恶魔 / Deal | 已知门/物品与费用 / Known door/item and cost | 45 s default | 接触前复核支付后余量 / Recheck reserve before contact | 普通 Isaac 已知费用可 / Yes for known ordinary-Isaac payments | 自然实机仍不足 / Limited natural evidence |
| 炸弹开路 / Bomb entry | 有炸弹、可达放置点和候选 / Bomb available and executable placement | 45 s default | 放弹单次；撤离/爆炸范围逐帧 / One bomb input, per-frame evacuation | 预算取舍可，撤离不可 / Budget yes; evacuation no | 稀有自然验证未齐；隐藏元数据优势 / Incomplete live coverage, metadata advantage |
| 星象房 / Planetarium | 已发现可进入房间 / Discovered enterable room | 45 s default | 门口路径与钥匙复核 / Local door path/key recheck | 可以，不能预言随机生成 / Yes, no prediction of generation | 自然样本不足 / Limited natural evidence |
| 骰子房 / Dice | 已知点数和机关 / Known face and trigger | 45 s default | 走上机关前复核，触发后重建状态 / Recheck before contact; rebuild state after trigger | 可以，破坏性效果需谨慎 / Yes, destructive outcomes need care | 自然样本不足 / Limited natural evidence |
| 献祭房 / Sacrifice | 已知计数与生命预算 / Known count and health budget | 每次付款前一轮 45 s / 45 s before each payment | 每次只支付一次，再检查 / One payment, then reassess | 可以；不允许无限连献 / Yes, no unbounded repetition | 自然样本不足 / Limited natural evidence |
| 地形 / Terrain | 安全上下文中存在宏观路线选择 / Safe macro routing opportunity | 45 s for route choice | 通行与相位每个游戏回调帧；无固定 ms 保证 / Crossing and phase checks each game callback frame, no fixed-ms guarantee | 绕路/资源可以，穿刺时机不可以 / Route/budget yes; timing no | 本地有标注地刺回归，非所有房型 / Labelled local regressions, not all rooms |
| 躲弹/瞄准/蓄力释放 / Dodge, aim, charge release | 战斗中的即时危险与武器状态 / Immediate combat and weapon state | 不调用模型 / No inference | 每个游戏输入/更新回调帧；不能用网络判断替代 / Every local input/update callback frame | 不适合当前延迟 / Unsuitable at observed latency | 本地规则与武器回归；无通用最优保证 / Local regressions, no universal optimum |

游戏帧率、暂停、加载和录制开销会改变墙钟时间，因此不把“1 帧”硬写成对所有环境都成立的 16.7 ms。本地宏观调度为 6 Hz，状态最少间隔 3 帧，DSH 机会检查为 250 ms；这些都不等于相同频率的模型推理。

Frame rate, pause/loading and capture overhead affect wall-clock timing. A frame is therefore not promised to equal 16.7 ms on every setup. Macro scheduling is 6 Hz, telemetry is at least three frames apart and DSH opportunity polling is 250 ms; none is the inference rate.

## 限制 / Restrictions

- 主动/口袋槽 0 执行，槽 0–3 读取。普通 Isaac 的已知生命成本先实现；其他角色和未知支付保守拒绝。 / Execute slot 0, observe slots 0–3. Known ordinary-Isaac health costs first; other semantics rejected.
- 未知药丸不预揭示；道具机制是登记子集，完整库存不等于完整协同理解。 / No advance revelation of pills. Full inventory does not imply exhaustive synergy knowledge.
- Bible 对 Satan 的致死使用被本地拒绝；未知冲刺、复杂瞄准等不构造可执行 offer。 / Bible-on-Satan is rejected; unsupported dash/aim mechanics are not offered.
- 等待选择只放行免费普通路线与本地战斗，不默认消费钥匙、炸弹、生命或进入可选特殊房。 / Wait permits free ordinary routes/local combat, not implicit resource spending or optional special-room entry.
- 回放中有该领域候选并合法提交，只证明接口可表达；不能替代自然游戏中的发现、进入、执行与效果验证。 / A legal replay submission proves expressibility, not natural discovery, entry, execution or outcome.
