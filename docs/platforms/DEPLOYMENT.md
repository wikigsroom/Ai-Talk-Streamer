# 原生 Windows 部署与平台配置

## 目录和依赖

在数字人现有项目根目录操作，3080 为 `C:\dev\虚拟数字人直播`，控制端为 `E:\dev\sandbox\虚拟数字人直播`。所有新增程序、日志、浏览器状态与证据均保存在项目下。

| 路径 | 内容 | 是否提交 Git |
|---|---|---|
| `backend/platforms/`、`web/platforms.*` | 平台后端和界面 | 是 |
| `configs/platforms.private.json` | 推流码、Cookie、开发密钥及连接配置 | 否；读取 API 不返回私有值 |
| `state/platforms/control.sqlite3` | 平台事件与输出状态 | 否 |
| `cache/platforms/bilibili/`、`douyin/` | 项目独立浏览器资料和平台登录状态 | 否 |
| `runtime/platforms/` | CPU-only Python blivedm 环境 | 否 |
| `tools/dsh-browser/` | 固定版本 Playwright Core，不下载重复浏览器 | 否 |
| `tools/obs/` | 现有原生 OBS 便携版 | 否 |
| `tools/douyin-companion/` | 官方直播伴侣的项目内解包目录 | 否；不重新分发客户端 |
| `tools/7zip/`、`downloads/platforms/` | 项目内解包工具、官方程序下载 | 否 |
| `outputs/platforms/recordings/` | 本地验收录制 | 否；选定证据另存 docs |
| `.setup/platforms/` | 安装凭据、OBS 修改前备份 | 否 |

安装脚本使用自己所在的项目根目录：

```powershell
Set-Location -LiteralPath 'C:\dev\虚拟数字人直播'
& '.\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe' -X utf8 -B .\scripts\install_platform_runtime.py
```

如网络需要已配置代理，可添加 `--proxy http://<YOUR_PROXY_HOST>:<PORT>`。Python 依赖安装到独立环境，不升级人物或语音环境里的 PyTorch、Transformers、CUDA 等依赖。浏览器采集复用工作站已有 Chrome/Edge，每个平台最多一个项目窗口，停止时关闭自己的上下文。

blivedm 必须从官方 Git 仓库的固定提交安装，不执行 `pip install blivedm`，避免安装同名非官方 PyPI 包。

## B站基础配置

1. 在 B站自己的直播中心确认房间、分区和当前账号开播方式，获取平台实际提供的推流服务器与推流码。
2. 在平台页选择 B站，填写房间号或链接，以及服务器和推流码。不要把推流码拼进公开文档。
3. 选择 `blivedm`，有稳定观众 ID 需求时可填写自己账号的 Cookie。留空允许按上游支持的匿名能力尝试接收；平台隐藏 UID 时只能公开上下文处理。
4. 如 Web 客户端被平台变更影响，切换本地浏览器采集，打开独立窗口处理平台登录。采集只读取新评论，不回放刚打开网页时已有的历史评论。
5. 准备 OBS、检查链路，先录制，再正式点击推流。

## 抖音基础配置

本次工作站已准备官方 **13.1.1** x64 直播伴侣。安装包与解包后的主程序均通过 Windows Authenticode 验证，发布者为 `Douyin Vision Co., Ltd.`；实际入口为 `tools/douyin-companion/app/直播伴侣.exe`。未替主播登录或开播。

需要在另一套原生 Windows 项目准备时，可运行：

```powershell
& '.\runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe' -X utf8 -B .\scripts\prepare_douyin_companion.py
```

脚本从官方入口获取客户端，使用固定版本 7-Zip 26.05 在项目内解包，支持 `app.7z` 与 `app-64.7z` 安装载荷，不执行全局安装、不安装驱动。可通过 `--proxy` 使用自己的现有代理。已有安装包和 7-Zip 可复用；下载失败时保留日志与已有文件，不把失败当成准备完成。

安装凭据在 `outputs/platforms/setup/douyin-companion.json`，包括安装包 SHA-256、两处签名和实际应用相对路径。该准备步骤不证明客户端已登录、平台权限已获批或声音已经在观众端播放。

1. 从 [官方页面](https://streamingtool.douyin.com/) 获取 Windows 直播伴侣，使用具备权限的主播账号登录。
2. 平台页选择抖音，保存自己的 `live.douyin.com` 房间链接，画面方式选择“直播伴侣采集画面”。没有推流地址时不填写或编造地址。
3. 点击“准备竖屏画面”，再点击“准备直播伴侣画面”。系统打开 OBS 的窗口化 Program 投影，并将人物声音设置为监听和输出。
4. 在直播伴侣添加窗口源，选择该 OBS 投影；按 9:16 布局铺满，避免裁掉头部或手部。人物源为 720×1280，25 FPS，主观感受不能通过把输出帧率设为 60 FPS 来提高。
5. 在 OBS 高级音频设置中确认人物源的监听目标是一个实际可用的 Windows 播放设备；直播伴侣选择相同设备的桌面声音。关闭直播伴侣中不需要的麦克风、重复桌面源和背景浏览器声音。播放一段测试语音，确认伴侣电平表和观众回放均有声音。
6. 如使用虚拟音频线，选择已安装且实际可用的设备，分别核对输入/输出方向；本方案不默认安装内核驱动。仅使用 OBS Virtual Camera 不能传输人物声音。
7. 在直播伴侣自己确认开播。平台页“直播伴侣已开播”只是主播手动确认，不是平台 API 已验证直播状态。
8. 弹幕选择本地浏览器采集。登录窗口位于 3080 上，不是当前观看网页的电脑；通过现有远控处理平台提示。后台采集关闭声音和视频资源加载，减少不必要的显存与网络开销。

## 官方应用接入

### B站

获批后填写应用 ID、Access Key、Access Secret、主播身份码，选择“B站官方开放平台”。输入和 OBS 输出彼此独立：有官方弹幕权限不自动获得开播权限，有开播权限也不自动获得官方弹幕权限。

适配器实现开启项目、20 秒项目心跳、30 秒消息长链心跳、不同长链节点轮换重连、zlib/Brotli 批量消息解析与结束项目清理。应用结束必须调用 end，不能只断开 WebSocket。

### 抖音

选择“抖音官方数据回调”，设置官方推送配置中的签名密钥。获批应用必须按平台流程建立/挂载数据推送任务，并具有需要的评论或礼物数据权限。系统提供回调消费端，不冒充任意账号都能创建任务。

公网接入仅需一个原始 HTTP 转发入口；业务计算仍在本地。必须保留 body 原字节及 `x-*` 签名请求头。使用 HTTPS 域名、TLS 和平台规定的回调配置，网络连通与官方应用回调需在该账号上实际验证。

## OBS 配置

系统复用项目 OBS WebSocket 端口 4457。已有 OBS 自身的 WebSocket 密码由本地配置文件自动读取，不显示在平台页面，不要求用户再输入一层管理员凭据。

准备动作仅在 OBS 未推流、未录制且未开虚拟摄像头时修改画布，先保存修改前的画面和场景信息到 `.setup/platforms/`。新增独立 `AiTalk Vertical` 场景与 `AiTalk Avatar` 源，不删除已有场景。

画布与输出：720×1280、25 FPS；初始 H.264 NVENC、5,000 Kbps 视频、160 Kbps 音频；人物浏览器源由 OBS 控制音频，音量 -3dB。应依据账号实际限值和网络上行调整码率，不将该初始值视为所有平台唯一规定。

若现场已在推流，不能通过网页“准备”覆盖现有输出。一次只配置一个 OBS 主推流目标；已有输出不能被另一个目标静默接管。
