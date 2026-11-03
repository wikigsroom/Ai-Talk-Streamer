# MC横屏直播间定稿 v1.0

日期2026-10-29；分支mc；版本1.0.0；修订04；状态DESIGN_FROZEN。后续按本版布局和风格实施。

默认：1920×1080全屏游戏、右下264像素圆形人物、最多4条向上滚动的B站观众留言。**后台支持留言左侧／右侧切换，默认右侧；留言与礼物一起换边，人物始终右下。** 保留320×180横窗和顶部飘屏备选，不恢复精选提问卡。

系统级接入、模型分工、硬件与实施验收见 [MC完整总方案](../../MC直播总方案.md)。本目录仍是布局及素材设计定稿，不表示完整MC运行已实现。

开发时使用 [技术方案 v1.0](../../technical/mc-live-v1/README.md) 中的各端模块、接口、控制协议、媒体与验收契约；布局坐标仍以本目录引用的权威JSON为准。

- [定稿说明与后续约束](定稿说明.md)
- [唯一布局配置](../../../configs/layouts/mc-landscape-v1.json)／[详细评估与实施路径](横屏直播间设计评估.md)
- [交互样稿](preview.html)：人物、留言方式、左右位置、四种状态、示例消息、保护范围与720P。
- [右侧留言](preview-play-1080.png)／[左侧留言](preview-left-1080.png)／[左侧720P](preview-left-720.png)／[后台位置选项](preview-backend-position-control.png)
- [横向人物布局](preview-landscape-1080.png)／[人物局部对比](avatar-comparison.png)／[横向飘屏](preview-flying-1080.png)
- [后台联动证据](backend-position-verification.json)／[布局检查](preview-verification.json)
- [B站留言姬开源选型](B站留言姬开源选型.md)／[素材规范](人物素材重制规范.md)／[2段待机＋48手势改编计划](motion-reframe-plan.csv)

后台入口为 /admin → 画面与包装 → 统一直播包装 → MC 弹幕位置。配置字段overlay.mc_chat_side已接入保存、枚举校验和Room实时同步；web/mc-chat-position.js负责位置投影，不重建消息或媒体。

样稿默认离线，左右切换只用于本地查看。显式以room_control=1并与Room API同源打开时，样稿读取后台设置，禁用本地左右选择；本轮通过隔离的本机测试服务验证此链路。

人物仍是现有静态参考的取景演示，游戏是原创占位图，留言为虚构示例。新人物视频、完整MC正式媒体输出和B站真实联合运行尚未实施；设计定稿与这些运行验收分别记录。

重建派生配置、占位图和动作计划：在项目根目录运行 python -X utf8 -B docs/design/mc-landscape-v1/build_design.py。构建脚本读取权威JSON生成layout-spec.json/js，避免两套坐标。capture-preview.cjs使用本机Chrome重建布局截图；所有创建的页面、上下文和测试服务在结束后关闭。
