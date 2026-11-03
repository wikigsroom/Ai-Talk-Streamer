# B站留言姬／弹幕姬开源选型

检索日期2026-10-29；分支mc。这里的对象是直播观众留言显示与弹幕采集，不是编码推流客户端。通过搜索引擎检索，再读取项目README、Wiki、发布页，并用GitHub公开REST API核对Star、归档状态与许可证字段。数据快照见[repository-research.json](references/repository-research.json)，Star是抓取时数值，后续会变化。

## 1. 按Star从高到低排序

| 编号 | 仓库 | Star | 类型／本项目用法 | DSH原生插件？ | 状态与取舍 |
|---|---|---:|---|---|---|
| 1 | [xfgryujk/blivechat](https://github.com/xfgryujk/blivechat) | 2,760 | 浏览器留言栏、样式、模板和插件参考 | 否；它有自己的插件体系 | MIT；本轮主要视觉与CSS结构参考 |
| 2 | [Tsuk1ko/bilibili-live-chat](https://github.com/Tsuk1ko/bilibili-live-chat) | 1,489 | 纯Web留言与礼物展示参考 | 否 | MIT；当前要求开放平台模式，不把旧免配置说法作为承诺 |
| 3 | [xfgryujk/blivedm](https://github.com/xfgryujk/blivedm) | 1,416 | Python WebSocket弹幕采集库 | 否；当前项目已有采集适配 | MIT；建议沿用现有单采集入口，仍需校验锁定版本 |
| 4 | [iwxyi/MagicalDanmaku](https://github.com/iwxyi/MagicalDanmaku) | 1,230 | 历史多功能场控／弹幕工具 | 否 | API标GPL-3.0；已归档且作者公告终止，不作为新方案基础 |
| 5 | [DoodleBears/blivechat](https://github.com/DoodleBears/blivechat) | 396 | blivechat的历史分支／样式生态 | 否 | MIT；最近推送2024-03，不能默认与原版CSS兼容 |
| 6 | [Beats0/bilive-danmaku](https://github.com/Beats0/bilive-danmaku) | 247 | Windows／macOS桌面弹幕姬 | 否 | MIT；可参考操作者看弹幕与穿透交互，非首选节目浏览器层 |
| 7 | [piko017/Bilibili_danmu](https://github.com/piko017/Bilibili_danmu) | 3 | 神奇弹幕旧代码副本 | 否 | API标GPL-3.0；仅记录检索结果，不因Fork存在而认为上游继续维护 |
| 8 | [UncleChair/blivechat-community-template](https://github.com/UncleChair/blivechat-community-template) | 1 | 原版blivechat的社区DOM模板插件参考 | 否；属于blivechat插件 | MIT；可研究模板适配，但Star少，不作为采集与调度基础 |

排序不等于推荐等级：blivedm排名第3却是现有项目最直接的采集复用点；已停运项目即使Star较高也不进入候选实施链路。这8项是针对本次留言姬要求的定向检索，不替代之前MC／无人深空仓库的调查表。

许可证列仅记录API字段，不表示已经导入项目代码；本轮没有安装、运行或复制这些仓库的实现。原创CSS只依据公开DOM选择器另行编写。

## 2. 关键一手依据

| 来源 | 本轮确认的内容 | 对设计的影响 |
|---|---|---|
| [blivechat README](https://github.com/xfgryujk/blivechat/blob/dev/README.md) | 连续评论展示、身份高亮、自定义HTML与插件、当前身份码接入说明 | 采用昵称／身份／正文分层；接入不能照搬过时房间号教程 |
| [blivechat CSS参考](https://github.com/xfgryujk/blivechat/wiki/自定义CSS参考) | 普通消息标签、author-type、blc-guard-level、付费消息结构和表情样式 | 原创候选CSS采用这些公开选择器 |
| [blivechat 自定义HTML模板](https://github.com/xfgryujk/blivechat/wiki/自定义HTML模板) | 自定义消息DOM扩展入口 | 作为未来外接皮肤适配参考，不假定所有旧皮肤兼容 |
| [Bilibili Live Chat README](https://github.com/Tsuk1ko/bilibili-live-chat/blob/master/README.md) | 当前仅支持开放平台、自己的直播间；线上站点有反代依赖 | “纯Web”不等于任意房间免身份接入；本项目走统一后端 |
| [blivedm README](https://github.com/xfgryujk/blivedm) | 弹幕协议库支持Web和开放平台接口 | 与本项目现有采集器核对，避免两套采集 |
| [bilive-danmaku README](https://github.com/Beats0/bilive-danmaku/blob/master/README.md) | 桌面弹幕、穿透、部分自定义样式和朗读选项 | 操作员参考可用；正式人物链路不再加自动朗读 |
| [神奇弹幕状态公告](https://github.com/iwxyi/MagicalDanmaku/blob/master/README.md) | 作者2025-12-25宣布终止并保留历史归档 | 从可实施候选中排除 |

本轮以开源项目的一手文档和公开选择器为结构依据，满足“寻找开源方案或参考网图”的要求。未下载直播间网图、复制付费皮肤、登录真实直播间或向公共服务提交房间身份信息。没有将未能视觉检查的远程截图描述为已经完成实机考察。

## 3. 推荐落点

**现有blivedm采集 → 当前Room事件 → 原创MC留言显示／DSH候选输入。**

采用blivechat的消息层级和可定制思路，视觉重新设计为知夏的浅蓝、植物绿和木色。先复用当前项目的数据流，而非独立启动另一个包含自动回复、TTS和场控的整套工具。

两条备选路线：

| 路线 | 可用性 | 代价 |
|---|---|---|
| 项目内原创MC渲染器，推荐 | 对现有事件、字幕和单播放端控制最明确 | 需要补齐角色元数据、撤回、表情、真实流量验收 |
| 独立本地blivechat＋原创皮肤 | 对人工主播更快获得成熟留言栏；平台连接仍需配置 | 需解决和DSH重复采集、删除同步、窗口透明与版本兼容；未经本轮验证 |

本轮交付的是第一条路线的离线视觉原型，以及第二条路线可研究的CSS候选。CSS决定外观，不会凭空获得平台事件、可信身份或DSH工具能力。

默认4条连续评论向上滚动；圆形人物与留言的小头像呼应。SC进入同一流，礼物最多一条小通知。保留两行横向弹幕作为替代模式。没有“AI正在看的留言”卡。

## 4. 接入时明确需要补齐的字段

最少保留事件ID、平台和房间、可信用户ID、昵称、事件类型、发生／接收时间、测试标记。按需要扩展服务端核验过的角色、舰队等级、头像、表情、礼物ID／数量、SC金额与撤回目标。

当前采集器只有普通弹幕／礼物／SC的部分字段；Room公开投影也会丢弃未知字段。因此先扩展后端契约再启用对应徽章，未知时不显示。SC类型与金额分别判断，不把任何木色消息都当付费。

去重、审核和隐藏先在统一入口执行，再投影给显示端与DSH。断线重连不把历史内容当新消息；屏蔽或撤回能从屏幕移除。头像加载失败用本地占位，不影响文字到达。礼物按用户ID而非昵称合并，避免同名用户混算。这些都是实施要求，当前样稿仅展示外观与有界运动。
