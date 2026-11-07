## 变更说明

<!-- 说明改了什么，以及为什么需要这项变更。 -->

## 验证

- [ ] `python -m compileall -q src`
- [ ] `python -m unittest discover -s tests -v`
- [ ] 已说明未进行的实机验证

## 安全检查

- [ ] 未提交 API Key、日志、存档或个人路径
- [ ] 未新增公网暴露的监听地址
- [ ] Lua 状态协议变化已同步 Python 模型和测试
