# DSH 直播适配

本目录的 fish、mood、speak-up 适配代码分别派生自
[dsh-fish-memory](https://github.com/Yuuyuko-uu/dsh-fish-memory)、
[dsh-feiyu-mood](https://github.com/Yuuyuko-uu/dsh-feiyu-mood)、
[dsh-speak-up](https://github.com/Yuuyuko-uu/dsh-speak-up)，原作者 **Yuuyuko-uu**。
这三个子目录继续采用各自完整保留的《Yuuyuko-uu 插件许可1.2》，不改变作者归属。

这里接入经过审阅的能力和源码片段，不声称安装了七套未经修改的桌面插件。
每个子目录保留固定提交、原文件摘要和许可。fish 保留相关度、重要度和半衰期排序，读取现有分区记忆；
mood 保留七维状态、饱和、三分之一步长及自然衰减，来源改为实际游戏事件；
speak-up 使用原始概率纯函数，投递到现有口播队列，只有官方源实际播完才更新说话时间。
不启动插件自己的更新器、计时宿主、网页部件、额外模型或记忆写入器。

soul 的 memory-recall.mjs 来自 Scorp1o117/dsh-soul-md，保留原始词项函数（MIT）；
人格正文由 configs/characters/female-a-mc-soul.md 提供，通过现有 DSH systemPrompt.section 接入，身份仍取 Humanity 已发布档案。
humanizer 保留 jiji262/humanizer-chinese 的完整 SKILL.md 与 MIT 许可，采用嵌入模式的表达审核规则。

memewiki 的 index.mjs 和只读词库取自 thawline/dsh-memewiki（MIT）；仅适配根目录定位并导出只读查询及关闭方法。
保留其 NOTICE：词库数据来源 cnmeme.wiki，不主张数据版权。Liujelly/dsh-memewiki 作为另一实现已审阅，
不重复部署第二份词库，也不把未部署的版本称为运行插件。
