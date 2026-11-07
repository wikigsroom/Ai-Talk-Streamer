# 操作与恢复 / Operations and recovery

## 模式与生命周期 / Modes and lifecycle

| 命令 / Command | 行为 / Behavior |
|---|---|
| `python launch_game.py` | 启动配置的唯一游戏，不选择存档、不启用自动控制 / Start only the configured game; no slot selection or automatic arming |
| `python manage_stack.py start` | 启动本地桥、策略 API、DSH；有存活角色时先暂停；观察模式 / Start services, pause a living run, remain in observation |
| `python manage_stack.py status` | 查看本地、DSH、真实暂停、槽和进度 / Read local/DSH status, real pause, slot and progression |
| `python manage_stack.py arm` | 经保护检查，启用本地控制与 DSH 自动判断，再正常恢复 / Verify guards, enable local+DSH, normally unpause |
| `python manage_stack.py arm-local` | 同样检查，只启用本地；关闭 DSH 自动判断 / Same guards, local only, DSH automatic off |
| `python manage_stack.py pause` | 请求普通暂停并检查帧稳定，再关闭自动输入和模型任务 / Require normal pause and stable frame before stopping input/model work |
| `python manage_stack.py stop` | 先确认暂停，再退出本套拥有的服务；游戏保留 / Pause first, stop only owned services, retain game |
| `python manage_stack.py restart` | 暂停、重启、保持观察 / Pause, restart, remain unarmed |
| `python manage_stack.py restart-controller` | 只重启本地控制与回调，保留 DSH；仍观察 / Restart local controller/callbacks, retain DSH, remain unarmed |

不要把“进程退出”当成“游戏暂停”。控制器停止、模型任务取消和正常游戏暂停是三件事。暂停验证失败时不会继续关闭当前控制器，避免留下无人接管的活角色。

Process exit, model cancellation and actual game pause are separate events. If stable normal pause cannot be acknowledged, shutdown does not proceed to stop the active controller.

## 常见故障 / Troubleshooting

| 现象 / Symptom | 检查与处理 / Check and recovery |
|---|---|
| `401 INVALID_API_KEY` | 地址可达但密钥未被该服务接受；修复服务鉴权或用隐藏输入更新密钥，随后重新探测。不要更换游戏逻辑 / Endpoint is reachable but rejects the key. Fix authorization or update the private key, then probe again |
| TCP/HTTP timeout | 先恢复模型主机网络与服务。DSH ready 不代表远端可用；可显式选择 `arm-local` / Restore network/service; host readiness is separate. Local-only is explicit |
| Node 版本过旧或 npm 找不到 | 使用 `setup_dsh.py --check --node ... --npm ...` 验证；不替换系统 Node / Supply native runtime paths; do not replace system Node |
| PowerShell 禁止脚本 | 使用 Python 主入口；不要修改系统策略 / Use Python entry points without changing system policy |
| 游戏白窗/冷启动缓慢 | 等待资源载入并观察日志；本机出现过数分钟冷启动，白窗本身不是已证实死锁 / Wait and inspect loading logs; a white cold-start window alone is not proof of deadlock |
| DSH 迟迟未 ready | 检查 `logs/services/` 与 `logs/dsh/`；启动器最多等 300 秒，超时不启用游戏 / Inspect local logs; readiness wait is capped at 300 seconds and never arms gameplay |
| 9532/9528/9529/9533 已被占用 | 启动器核对进程来源；未知进程保持原状。正常结束自己启动的重复实例 / Ownership is verified; unrelated listeners are left alone |
| 错误槽、ReadOnly 或原存档哈希变化 | 停止启用，正常暂停，检查真正的存档位置、Cloud 与基线；不要刷新基线来掩盖差异 / Do not arm. Inspect actual saves/cloud/baseline; never replace a baseline merely to hide differences |
| `state disconnected/stale` | 模型查询不能替代真实游戏连接；检查所选游戏、桥身份与状态帧 / Check selected game, bridge identity and telemetry; model queries do not establish a game connection |
| 旧计划被拒绝 | 换房、传送、重开、价格/背包变化后属正常保护；查询新机会 / Expected after context changes; obtain a new decision |
| 主动、药丸或特殊房没有 offer | 检查槽位、识别、已登记效果、安全/费用条件；不通过提示词绕过 / Check supported slot, known effect and admission conditions; do not bypass guards in prompts |
| 服务恢复后游戏仍暂停 | 这是预期行为。检查状态后显式 `arm` 或 `arm-local` / Expected. Check state and explicitly arm |
| 切出游戏后不推进 | 核实真实 `PauseOnFocusLost=0`，区分最小化/加载/正常暂停；不循环抢前台 / Check actual option and distinguish minimization/loading/pause; do not repeatedly force foreground |

## 模型配置更新 / Updating the model configuration

在游戏已暂停的状态下，停止本套服务，用 `configure_model.py --base-url ... --model gpt-6-luna` 隐藏输入密钥，再启动。不要把 API key 作为参数或环境截图发布。只向操作者选择的服务发送该密钥。

With the game normally paused, stop the stack, update the private configuration through the hidden-input helper, and start again. Never publish key-bearing arguments or environment captures. Send the key only to the operator-selected service.

`probe_model.py` 检查真实网关和工具传输，不修改游戏。当前已公开的探测证据省略服务地址和密钥。公开 README 使用示例地址，不能直接连接。

The gateway probe checks real chat/tool transport without acting on the game. Public evidence excludes endpoint addresses and credentials. README endpoint placeholders are not functioning services.

## 离线与真实模型回放 / Replay checks

常规回归不会接管游戏：

```powershell
python -B -X utf8 -m unittest discover -s tests -q
node --test tests/test_dsh_binding.mjs
```

真实 DSH 模型回放需要有效服务，并独占 9532；它是带模型调用的合成场景，不是自然游戏录像：

```powershell
# 先正常暂停，再停服务；保留暂停游戏。
python manage_stack.py stop
```

在终端 A 启动官方 DSH 宿主：

```powershell
python start_dsh.py
```

等待 9533 `/status` ready 后，在终端 B 执行：

```powershell
python verify_scenarios.py --decision-seconds 45 --output model-replay.json
```

The verifier starts its own labelled scenario service on 9532. It never attaches to Isaac. `observed` receipts prove legal submission only. When finished, stop terminal A normally, then use `manage_stack.py start` to restore the live stack in observation mode. Never run the verifier simultaneously with `run_strategy.py`.

真实游戏小范围复测：

```powershell
python verify_live.py --seconds 120 --output live-check.json
python record_demo.py --seconds 45 --mode local
```

这两个命令会按各自模式显式启用授权槽并在 `finally` 中请求普通暂停。录制只捕获游戏帧，不捕获桌面或系统音频。请求时长控制游玩循环；暂停确认、接口重试和清理会增加总耗时，不能当成严格硬实时停止保证。

Both commands explicitly arm the authorized slot and request normal pause in `finally`. Recording captures game frames only, without desktop or system audio. Loop duration excludes some acknowledgement/retry/cleanup work and is not a hard real-time stop guarantee.

## 数据与发布 / Data and publication

`private/`、`.dsh-home/`、`node_modules/`、本机配置、PID/IPC、日志、录制原帧、备份和存档由 `.gitignore` 排除。只有审查过的 `docs/media/` 与 `docs/evidence/` 进入仓库。原始会话可能包含完整游戏状态或服务错误，不应批量上传。

Private data, sessions, dependencies, machine config, IPC, logs, raw capture frames, backups and saves are excluded. Only reviewed media and sanitized evidence are published. Inspect staged content, including binary secret matches, before pushing.
