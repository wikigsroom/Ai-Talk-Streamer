# 贡献指南 / Contributing

使用原生 Windows、CPython 3.13 与 Node >=24.9；不使用本地 Docker、WSL 或虚拟机。 / Use native Windows, CPython 3.13 and Node >=24.9; no local Docker, WSL or VM.

```powershell
python -m pip install -r requirements-native.lock.txt
python -m unittest discover -s tests -q
node --test tests/test_dsh_binding.mjs
```

修改游戏观察时同步状态模型与协议；新动作必须包含费用、上下文 guard、普通输入执行、效果核验和失效测试。 / Observation changes must update models/protocols. New actions need costs, context guards, normal-input execution, outcome checks and invalidation tests.

自然实机测试仅在授权槽执行；先完整备份并建立基线。所有有动作的验证结束后必须确认正常暂停。不要通过改血量、道具、房间、解锁或存档来制造测试成功。 / Live tests require an authorized slot and a verified backup/baseline. Confirm normal pause afterward. Do not manufacture success through state/save edits.

请在 PR 描述区分离线回归、合成模型回放与自然实机验证，并列出未覆盖范围。截图、会话和日志提交前检查凭据与个人路径。 / Distinguish unit tests, synthetic model replay and natural live evidence in PRs. Review media/logs for credentials and personal paths.

保留原作者许可证和来源。代码贡献按 MIT 发布；不要分发游戏资源。 / Preserve attribution. Code contributions use MIT; do not distribute game assets.
