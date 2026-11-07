# 发布内容 / Published contents

本次更新保留目标仓库已有的上游初始提交与 MIT 许可证，不重写历史。 / This update preserves the existing upstream initial commit and MIT license without rewriting history.

公开内容为源码、锁文件、测试、双语文档及经过审查的媒体和脱敏证据。private/、完整会话、依赖、个人配置、备份和存档由 .gitignore 排除。 / Public contents are source, locks, tests, bilingual docs, reviewed media and sanitized evidence. Private/session/dependency/machine/save data are excluded.

发布前执行本地回归、Node 绑定测试、文档链接/媒体检查、实际密钥逐文件扫描、原存档和冻结版本完整性检查。实际结果见 [验证报告](VALIDATION.md)。 / Local tests, bindings, links/media, private-value scanning and save/frozen integrity checks are recorded in validation.

GitHub Actions 只运行 Windows 离线回归，不启动游戏、不访问模型、不需要密钥。 / GitHub Actions runs Windows offline checks only, without game/model/credentials.

正式版自动发布另由 [RELEASING.md](RELEASING.md) 说明；仓库任务令牌只用于上传和发布审查后的附件，不启动游戏、不访问模型。 / Final-release automation uses a repository task token only for verified assets and publication, without game/model access.
