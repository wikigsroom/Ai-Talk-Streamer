# Isaac DSH Strategy 0.1.0

Repentance 1.7.9b 的 DSH 策略插件。配合 native130-dsh 本地控制服务使用，不单独控制游戏。

兼容官方 DSH 0.2.2-rc.1、Node >=24.9。Cordis 注入 agents / agentLoop / tools / systemPrompt / sessions，使用官方 agents.create、followup、whenIdle 和 concludeTurn。只有一个策略 agent；每四轮换一个短会话，局内状态保存在本地控制服务。

工具：`isaac_get_decision`、`isaac_get_state`、`isaac_lookup`、`isaac_submit_plan`。查询含新鲜度和局/房/桥身份；提交必须引用本地 offer 和显式资源预算。agent 不获得文件、终端、控制台、任意按键或游戏修改工具。

模型只提交 A1/A2 等 offer_ref；插件将短编号绑定到本轮真正观察到的完整上下文和幂等编号。这样避免长哈希抄写错误，同时仍拒绝过期、换房和上一轮授权。decision_binding.mjs 有独立 Node 回归测试。

每轮先由插件实时预取和绑定决策，再随事件传给模型。信息充分时一次模型往返即可调用 submit_plan；完整状态查询、机制检索和主动刷新决策仍可使用。预取不授权执行，本地在提交和实际输入时继续复核。

先启动主程序的 9532 API，给 DSH 进程提供 `ISAAC_BRIDGE_TOKEN` 环境变量。插件默认连接 http://127.0.0.1:9532，自己的状态接口在 9533；两者只监听本机。模型路由名 isaac-lan，模型 gpt-6-luna；路由与模型密钥由宿主配置，不写入插件包。

本项目用 `setup_dsh.py` 安装本地 file 依赖，`start_dsh.py` 以独立 DSH_HOME 和 sdk-minimal profile 挂载。tgz 提供官方 `dsh.bundle.patch` 元数据；其他 DSH profile 可通过官方 `dsh plugin --profile <名称> add <包路径.tgz>` 安装，再配置同名模型路由和环境变量。其他 profile 的默认工具权限应单独检查；本插件创建的 agent 始终只允许上述四个工具。

启动默认关闭 automatic，操作者经第 3 槽核验后才开启。控制接口需要本机 token。游戏即时战斗、蓄力、躲弹、地刺时机仍由本地执行。未知药丸不揭示；未知机制不构造动作。当前只直接操作主动槽 0、口袋槽 0；全部槽可读。献祭与生命交易先只支持普通 Isaac 的已知生命语义。

12 类回放的合法提交率不等于策略最优率，更不等于实机通关率。实际范围以主项目 docs 和 evidence 报告为准。
