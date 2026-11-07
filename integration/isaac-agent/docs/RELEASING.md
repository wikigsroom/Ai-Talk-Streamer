# 正式发布流程 / Final release process

正式版以 `vMAJOR.MINOR.PATCH` 标签为准。项目、宿主和插件版本必须一致。构建只读取指定提交中的受 Git 跟踪文件；不读取工作目录里的存档、密钥、会话或依赖。 / Final releases use vMAJOR.MINOR.PATCH tags, with matching project/host/plugin versions. Builds read the committed Git tree, excluding local private/runtime data.

## 本地准备 / Local preparation

```powershell
python -m unittest discover -s tests -q
node --test tests/test_dsh_binding.mjs
python tools/build_release.py --version v0.1.0 --ref HEAD --output artifacts/release
```

`build_release.py` 验证正式版号、必需文件、包内容、ZIP 完整性、插件成员与可疑凭据，再输出源码整包、插件 tgz、中英发布说明、逐文件清单和 SHA-256。所有源码均来自同一提交。 / The builder verifies version, required files, archive/plugin content and credential-like patterns, then emits source, plugin, notes, manifest and checksums from one commit.

`docs/releases/v0.1.0.md` 是该版本的发布说明来源。构建本身不会操作游戏或创建 GitHub Release。 / Versioned notes are the release-body source. Building neither operates the game nor publishes externally.

## GitHub 发布 / GitHub publication

先推送包含发布流程的主分支，再推送对应的注解标签；不要移动已经发布的标签。 / Push the release tooling to the default branch, then its annotated version tag. Never move a published tag.

```powershell
git push origin main
git tag -a v0.1.0 -m "Agent Gameplay Isaac v0.1.0"
git push origin v0.1.0
```

`Publish final release` 在 GitHub 托管的 Windows runner 上执行离线回归和构建，使用仅该任务的仓库 `GITHUB_TOKEN` 上传附件。它先创建草稿、核对附件，再发布为 `draft=false`、`prerelease=false`、Latest。这个流程不调度本机 Docker、WSL 或虚拟机。

The workflow runs offline tests/builds on a GitHub-hosted Windows runner, then uses its repository token to upload and verify assets before final publication. It does not run local virtualization, the game or model inference. The published result has draft=false, prerelease=false and Latest status.

中途失败保留草稿，避免不完整附件被当成正式成品。可在 Actions 中以相同已存在标签手动重跑；已发布版本不会被脚本覆盖。 / Failures leave a draft. Rerun with the same existing tag through Actions; published releases are not overwritten.

已有合法仓库 token 的维护者也可使用环境变量执行同一发布器：

```powershell
python tools/publish_release.py --repo wikigsroom/agent-gameplay-isaac --version v0.1.0 --directory artifacts/release
```

Token 只从 `GH_TOKEN` / `GITHUB_TOKEN` 环境读取，不作为参数或日志发布。 / Tokens are read only from environment variables, never arguments or logs.

## 发布后核验 / Post-publication checks

确认标签解析到构建提交、公开 Release 已发布且非预发布、五个附件齐全。下载附件，重新计算 SHA-256，与 `SHA256SUMS.txt` 和清单核对。 / Verify the tag commit, published/non-prerelease state, all five assets, and downloaded SHA-256 values against the checksum file and manifest.
