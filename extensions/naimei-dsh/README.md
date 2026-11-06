# 奶妹 DSH 扩展集成

本集成中的 fish-memory、feiyu-mood、speak-up 副本分别派生自 [Yuuyuko-uu/dsh-fish-memory](https://github.com/Yuuyuko-uu/dsh-fish-memory)、[Yuuyuko-uu/dsh-feiyu-mood](https://github.com/Yuuyuko-uu/dsh-feiyu-mood)、[Yuuyuko-uu/dsh-speak-up](https://github.com/Yuuyuko-uu/dsh-speak-up)，原作者 **Yuuyuko-uu**。三个副本继续适用各自完整保留的 **Yuuyuko-uu 插件许可 1.2**；不受本仓库其他文件的宽松许可覆盖。修改包括直播适配接口、文本缓存释放、直播原文诊断关闭和归属说明，详见下表。

这是 `naimei` 分支的项目内集成。来源由 `sources.lock.json` 固定到提交，并逐文件记录 SHA256。完整接入、操作与验证范围见 [使用说明](../../docs/naimei/DSH扩展接入与使用20261107.md)。

| 编号 | 本地副本 / 上游 | 版本 | 对副本的修改 | 许可 |
| --- | --- | --- | --- | --- |
| 01 | [soul-md](https://github.com/Scorp1o117/dsh-soul-md) | 0.12.1 | 无；人格卡由项目配置提供 | [MIT](vendor/soul-md/LICENSE) |
| 02 | [fish-memory](https://github.com/Yuuyuko-uu/dsh-fish-memory) | 1.5.5 | 导出清理六组文本缓存的接口；直播模式关闭原文诊断；README 归属说明 | [Yuuyuko-uu 插件许可 1.2](vendor/fish-memory/LICENSE) |
| 03 | [feiyu-mood](https://github.com/Yuuyuko-uu/dsh-feiyu-mood) | 0.9.1 | 导出原有情绪计算与评估接口；直播模式关闭原文诊断；README 归属说明 | [Yuuyuko-uu 插件许可 1.2](vendor/feiyu-mood/LICENSE) |
| 04 | [speak-up](https://github.com/Yuuyuko-uu/dsh-speak-up) | 0.3.0 | 导出原有调度器供正式播报队列接管；README 归属说明 | [Yuuyuko-uu 插件许可 1.2](vendor/speak-up/LICENSE) |
| 05 | [memewiki-thawline](https://github.com/thawline/dsh-memewiki) | 0.1.20 | 无 | [MIT](vendor/memewiki-thawline/LICENSE) |
| 06 | [humanizer-chinese](https://github.com/jiji262/humanizer-chinese) | 1.0.0 | 无；完整 SKILL.md 保留，项目提供口播嵌入规则 | [MIT](vendor/humanizer-chinese/LICENSE) |
| 07 | [memewiki-liujelly](https://github.com/Liujelly/dsh-memewiki) | 1.0.0 | 直播模式强制关闭在线回退 | [MIT](vendor/memewiki-liujelly/LICENSE) |

上层适配器位于 `backend/dsh-bridge/extensions.mjs`，保留来源名称，使用上游实际模块及算法。没有把这七项声称为本项目原创，也没有把三个自定义许可插件改为 MIT。

上表 MIT 指对应代码许可。梗词库数据的原作者与 cnmeme.wiki 归属见保留的 [NOTICE](vendor/memewiki-thawline/NOTICE)；fish-memory 的分词数据保留了 [jieba 来源及 MIT 声明](vendor/fish-memory/lib/词典-来源.txt)。本集成不重新主张这些数据或原作者配图的版权。

## 兼容方式

项目继续使用原生 Windows 的 DSH `0.2.0-rc.2`、Humanity `0.1.17`、Node `24.22.1`。部分上游完整插件包要求 DSH `>=0.2.1-rc.2`，所以此处采用受测的直播桥接适配模式 `reviewed_stream_bridge_adapters`，没有把较新桌面插件包直接登记到旧版 Cordis 容器。

人格提示、记忆排序、情绪评估、主动搭话调度和两个本地词库都使用实际来源代码。存储、观众分区、工具授权和媒体播放回执仍由项目的直播桥接层负责。上游桌面管理页、自更新器、会话扫描器和独立记忆文件写入器没有挂载到本项目。

## 安装与更新

原生安装入口 `deployment/install_dsh.ps1` 在锁定依赖安装、Humanity 补丁完成后调用 `deployment/stage_naimei_dsh_extensions.py`，先校验所有来源文件，再复制到被忽略的 `tools/dsh/node_modules/@naimei/`。加载时再次校验运行副本。校验失败即停止加载。

固定源的重新汇集使用 `scripts/sync_naimei_dsh_extensions.py --upstream <已检出七个锁定提交的目录>`。该过程不运行上游安装脚本。更新来源提交需要重新审查、修改固定提交和补丁锚点、生成新锁文件并重跑验证。

## 体积与数据

本轮来源副本共 84 个文件、43,330,976 字节，包含原作者 README、许可、配套资源和两个 SQLite 词库；不含上游 Git 格式设置或模型权重。安装副本另占同等来源体积，原生 Node/npm 依赖另计。新增模型权重 **0 字节**。

thawline 词库 6,792 条，Liujelly 词库 6,668 条，标题重叠 6,668 条，合并去重后 **6,792 个标题**。查询只暴露一个 `search_meme_wiki` 工具，同标题保留两个来源标签、优先使用 thawline 定义；不同命中各自保留。词库来源内容只是参考数据。

本目录不保存声音参考、私有提示词转录、访问密钥、现场状态或聊天记录。
