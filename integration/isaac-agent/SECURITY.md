# 安全与数据边界 / Security and data boundaries

模型密钥与本机写入 token 仅保存在 private/。DSH 进程通过环境读取密钥，公开配置、README、截图和交付代码不得包含它们。仅连接操作者选择的模型服务。 / Credentials stay in private/ and the DSH process environment, never public artifacts. Connect only to the operator-selected model endpoint.

游戏与策略端口仅绑定 IPv4 loopback。GET 状态对本机进程可读；写操作需要 X-Isaac-Token，来自浏览器 Origin 的写操作被拒绝。不要把这些端口转发到公网。 / APIs bind IPv4 loopback. Local GET state is readable; writes require a token and reject browser origins. Do not forward the ports publicly.

原生桥可在指定游戏内执行组装后的控制代码，因此只使用可信来源并核对游戏进程身份。策略 agent 只有四个受限工具，没有任意代码或终端工具。 / The native bridge loads trusted controller code into the selected game; verify source/process identity. The strategy agent has only four bounded tools and no arbitrary code/terminal tool.

本机配置、存档、备份、日志和完整会话均不上传。真实存档校验失败时应停止，不重建基线掩盖差异。游戏解锁与状态变化必须来自正常输入。 / Keep machine config, saves, backups, logs and full sessions private. Stop on save mismatch; do not hide it with a new baseline. Progression comes from normal input.

报告问题请提供脱敏后的版本、状态与复现步骤；不要在 Issue 中粘贴密钥或完整会话。 / Report sanitized versions, state and reproduction steps; never keys or complete sessions.
