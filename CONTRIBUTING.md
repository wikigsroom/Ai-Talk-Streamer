# Contributing / 开发与提交

[README](README.md) · [中文说明](README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md)

Keep the native Windows runtime and the optional cloud-text boundary explicit. Do not introduce Docker/WSL, a cloud media fallback or an automatic public stream as an implicit dependency. Changes to gestures must preserve matching body/face/mask frame indices and reviewed asset provenance.

保持原生 Windows 运行方式与可选云端文本边界。不得隐式引入 Docker/WSL、云端音视频兜底或自动公网开播。修改动作时必须保证身体、人脸、蒙版索引一致，并保留审核来源。

| Directory / 目录 | Edit for / 修改内容 |
| --- | --- |
| `integration/` | Installed runtime modules / 运行模块集成源 |
| `web/` | Studio and galleries / 演播台及图库页面 |
| `deployment/` | Download, environment, upstream patches and readiness / 部署与适配 |
| `scripts/` | Service lifecycle, asset preparation, generation and OBS verification / 服务、素材及验收 |
| `configs/` | Public examples, source locks, portable workflows and reference manifests / 公开配置与清单 |
| `devtools/`, `tests/` | Repository checks, documentation captures, media and scheduling tests / 仓库验证、录制与测试 |
| `docs/` | Bilingual operational documentation and curated evidence / 文档与脱敏证据 |

Edit `integration` and `web`, then apply the installation scripts to a disposable native checkout of the locked upstream sources. Do not treat edits inside ignored `src/` as a submitted patch. Preserve upstream license text and originals when changing patch logic. Keep both root READMEs consistent with user-visible behavior.

修改集成源与网页后，在可回退的原生上游检出中应用补丁；忽略目录 `src/` 内的临时修改不等于已提交集成。保留上游许可及补丁前原件，确保中英文 README 与实际行为一致。

Before committing:

```powershell
python -X utf8 devtools/verify-repository.py
python -m unittest discover -s tests -v
node --check devtools/capture-studio.cjs
# With ffprobe installed:
python -X utf8 devtools/verify-repository.py --media
```

For media/runtime changes, repeat the affected actual browser/OBS scenario. A passing syntax check is not evidence of live lip quality or speech recovery. For documentation captures, `npm ci` installs the pinned Playwright Core; use installed Chrome, not an extra browser download. The script closes its own tabs/context in `finally`; close any other unused tabs you opened manually.

修改推理或媒体时应复测受影响的真实浏览器/OBS 场景，不能以语法检查替代音画验收。截图工具使用已安装 Chrome，无需再下载浏览器；它负责关闭自身上下文，手动打开的无用标签也需关闭。

Do not commit model weights, installed programs, caches, decoded avatar banks, `channel.env`, OBS configs/passwords, device-control settings, private API requests or raw recordings. Selected source media are intentional Git assets; avoid adding duplicate large exports. Verify every changed asset's manifest hash and review decision. Do not retroactively mark newly generated material as accepted without review.

不要提交权重、安装程序、缓存、整库解码帧、密钥、OBS 密码、设备控制配置、私有请求或原始录屏。选用素材属于有意入库的资源；避免重复大文件，变更后更新哈希和审核记录。

Report validation scope honestly: repository-only checks, CPU installation checks, GPU preprocessing and real live acceptance are separate observations. Hosted CI does not install the GPU stack. See [Testing](docs/TESTING.md).
