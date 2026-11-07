# 当前验证与证据 / Validation and evidence

审查日期：**2026-11-07，Asia/Taipei**。版本：native130-dsh / 0.1.0。可机器读取的脱敏记录见 [audit-2026-11-07.json](evidence/audit-2026-11-07.json)。服务状态是检查时点的快照。

Audit date: **2026-11-07, Asia/Taipei**. Build: native130-dsh / 0.1.0. The sanitized JSON record separates current checks from earlier tests. Availability is a point-in-time observation.

## 结论 / Findings

| 项目 / Component | 本次结果 / Current result | 可得出的结论 / Meaning |
|---|---|---|
| 发布副本离线回归 / Publication regressions | **606 passed**，约 10.9 秒；包含当前控制器和仍有效的上游行为回归 / 606 passed in about 10.9 seconds, including retained upstream behavior tests | 已检查对应离线行为；不等于自然实机覆盖 / Offline checks, not universal live coverage |
| DSH 绑定 / DSH binding | **4/4 passed**，原生 Node 24.22.1 / Four passed | 短编号、身份隔离、过期和幂等约定有效 / Short refs, isolation, expiry and idempotency |
| 新机器依赖 / Fresh dependencies | 按锁文件在发布目录原生安装 Python 依赖，Lua 5.3 编译回归通过 / Pinned Python dependencies installed natively in the publication checkout; Lua 5.3 compilation tested | 未使用容器或虚拟机；没有携带本机依赖二进制入库 / No local container/VM or checked-in dependency binaries |
| 本地实机 / Live local control | 45 秒请求，187 个原生捕获帧，5 房间，正常暂停 / 45-second request, 187 native captures, five rooms, acknowledged pause | 本地链路可运行；角色实际掉血，不宣称稳定通关 / Working local path; damage occurred, no reliable-win claim |
| 后台 / Background operation | 36/41 状态采样为后台，有连续后台帧推进；5 次采样为前台 / 36 of 41 samples background, five foreground, with consecutive background frame advance | 具备后台推进证据；这段录制并非全程后台 / Background progression demonstrated, not an entirely background recording |
| 官方 DSH 宿主 / Official DSH host | ready，单 agent、4 工具，结束时 automatic=false / Ready, one agent, four tools, automatic off afterward | 本地宿主可用；不代表远端模型可用 / Host ready does not verify inference |
| 新服务鉴权 / Migrated gateway | `/models` 和 `/chat/completions` 返回 **401**；服务返回 `INVALID_API_KEY` / Both endpoints return 401; service reports INVALID_API_KEY | 地址已可达，原密钥尚未被该服务接受；需要服务端恢复鉴权 / Reachable endpoint, current key rejected; authorization must be restored |
| 新服务 DSH 回放 / Migrated DSH replay | route 合成场景 **0/1 合法提交**，没有工具调用 / Synthetic route 0/1 legal submission, no tool calls | 当前无法完成新服务端到端判断；不能使用历史 9/12 冒充当前成功 / Current end-to-end test unavailable; earlier 9/12 is not current success |
| 原存档 / Original saves | **411 个 `.dat` 哈希不变** / 411 unchanged hashes | 受保护的原存档未变化；授权测试槽正常产生游戏进度 / Protected originals unchanged; authorized slot has normal progress |
| 冻结版本 / Frozen build | **277 文件不变** / 277 unchanged files | native129 冻结产物未修改 / Frozen native129 preserved |

本次恢复游戏后的授权状态是第 3 槽、`ReadOnly=false`。本地录制从第一层房间 84 开始，经过房间 71、72、85、59 等，结束在房间 59。生命从 6 降到 4 半心，帧从 21147 增到 22251；真实暂停后帧稳定。没有添加生命、道具、解锁或更改房间来制造成功。

The authorized live run was slot 3 with `ReadOnly=false`. It started on floor 1, room 84, visited rooms including 71, 72, 85 and 59, and ended in room 59. Health fell from six to four half-hearts; the frame advanced from 21147 to 22251. A normal stable pause was acknowledged afterward. No health/items/unlocks/rooms were edited to manufacture success.

## 网关切换前的历史证据 / Earlier evidence before gateway migration

这些测试真实使用了官方 DSH 和模型，但属于此前服务可用时的结果，不描述新服务当前状态。 / These used official DSH and the real model while the previous gateway was available. They are historical, not proof of current migrated-service availability.

| 回放领域 / Domain | 在 45 秒内合法提交 / Legal within 45 s | 耗时 / Elapsed |
|---|---|---|
| 主动 / active | 否，超时 / No, timeout | ≥45 s |
| 一次性主动 / active_special | 是 / Yes | 16.52 s |
| 拾取 / pickup | 否，超时 / No, timeout | ≥45 s |
| 药丸 / pill | 否，超时 / No, timeout | ≥45 s |
| 卡牌 / card | 是 / Yes | 25.02 s |
| 路线 / route | 是 / Yes | 6.91 s |
| 交易 / deal | 是 / Yes | 10.23 s |
| 炸弹 / bomb_entry | 是 / Yes | 17.27 s |
| 星象房 / planetarium | 是 / Yes | 33.21 s |
| 骰子房 / dice | 是 / Yes | 13.16 s |
| 献祭 / sacrifice | 是 / Yes | 9.83 s |
| 地形 / terrain | 是 / Yes | 10.24 s |

共 **9/12**，成功提交耗时 **6.9–33.2 秒，中位数 13.16 秒**。超时是被期限截断的数据；不能把约 45 秒叫作模型完整响应 P95，也不能把 9/12 称为“75% 通关率”。每类一个合成场景，不足以估计该类总体成功率。

Total: **9/12** legal submissions. Successful latency: **6.9–33.2 seconds, median 13.16 seconds**. Timeouts are censored observations, not completed-response latency percentiles. One labelled synthetic case per domain cannot estimate domain-wide performance or win rate.

此前自然实机另有两条证据：

- 硬币目标消失且资源/库存变化，回执为 `succeeded`；控制器挂起后约 5 秒正常暂停，恢复后没有自动继续。 / A coin disappeared with a resource/inventory change and a succeeded receipt; controller suspension caused normal pause after about five seconds, without automatic resume.
- 短编号路线从房间 71 到 84，真实房间变化被核验，生命保持 6 半心。模型选了已访问的安全房，说明能执行，不能证明探索策略最优。 / A short-reference route moved from 71 to 84 with health unchanged at six half-hearts. The agent chose a previously visited safe room: execution proof, not optimal exploration.

## 本次发现并修复 / Findings fixed in this audit

- Node/npm、Python 启动路径绑定个人机器：改为 PATH/显式参数和 Python 主入口。 / Remove personal runtime paths through discovery/explicit parameters and Python entry points.
- 首次安装需要目标 Mod 文件已存在：改为验证来源与游戏、创建目标、仅备份已有文件。 / Fresh deployment now creates the target and backs up existing files only.
- 缺少新机器完整存档初始化：增加原目录复制、哈希验证、槽隔离、链接/递归目标拒绝和不覆盖已有配置。 / Add verified full backup, slot isolation, link/recursive-destination rejection and no config overwrite.
- 模型故障时模式不够明确：增加 `arm-local`，使用相同的槽/存档/暂停保护。 / Add explicit local-only arming with the same guards.
- 发布副本带入旧测试和缺失常量：补齐版本化卡牌枚举；保留仍有效的上游行为测试；移除已删除 provider 的测试，以及要求旧直接炸弹 API 的源码字符串断言，由普通输入/行为回归覆盖。 / Include versioned card constants; retain valid upstream behavioral tests, remove removed-provider cases and obsolete source-string assertions that required legacy direct bomb APIs, and rely on current normal-input/behavior regressions.
- 旧 CI 使用 Linux 且未安装 Lua/Windows 依赖：更新为 Windows 离线检查，不接触游戏和模型。 / Update CI to Windows offline tests with native/Lua dependencies, no game or model.
- 公开文档与模式冲突：统一为当前 native 模式，保留上游许可证，隔离个人配置与原始会话。 / Align docs with native mode and exclude private configuration/sessions while retaining attribution.

## 未解决的边界 / Remaining limits

新服务鉴权依赖服务端恢复，本次没有通过修改本地安全检查绕过。15 秒模型回放期限在取消/排空后耗时约 24.1 秒；计划授权仍受本地期限约束，但宿主清理不是硬实时。因此不能承诺所有模型任务都在设置秒数内退出。

Gateway authorization requires service-side recovery; local guards were not bypassed. A 15-second replay budget took about 24.1 seconds including cancellation/draining. Local plan deadlines still bound authorization, but host cleanup is not hard real time.

自然稀有房间、更多道具/角色/槽位、长期探索质量和多局通关收益仍需测试。见 [ROADMAP](ROADMAP.md)。GitHub Actions 的远端运行结果应以仓库实际状态为准；本报告中的通过数来自本地原生执行。

Rare natural rooms, more items/characters/slots, exploration quality and multi-run benefits remain unverified. See the roadmap. Test counts here are from local native execution; remote GitHub Actions results must be checked separately.
