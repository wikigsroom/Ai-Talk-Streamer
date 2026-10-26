"""Rebuild the visual report from the sanitized, frozen evidence snapshot.

Native Windows: python -X utf8 devtools/build-performance-report.py
Requires matplotlib, reportlab and Pillow. No network or model calls.
"""
from pathlib import Path
from datetime import datetime
import base64,csv,html,json,statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak,KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT

REPO=Path(__file__).resolve().parents[1]
OUT=REPO/'docs/analysis/2026-10-27';D=json.loads((OUT/'data/evidence.json').read_text(encoding='utf-8'))
CHART=OUT/'charts';CHART.mkdir(exist_ok=True)
FONT=Path('C:/Windows/Fonts/msyh.ttc');FP=FontProperties(fname=str(FONT))
plt.rcParams.update({'font.family':FP.get_name(),'axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#C6D0DE','axes.labelcolor':'#35465C','xtick.color':'#54657A','ytick.color':'#35465C','figure.facecolor':'white','axes.facecolor':'white','savefig.facecolor':'white'})
P={'ink':'#172A45','muted':'#68788C','cloud':'#4167B4','tts':'#167D8D','buffer':'#B5792C','queue':'#A4AFBD','play':'#D2DFEE','fog':'#F3F6FA'}
R=[r for r in D['requests'] if r['cohort']=='public'];C=[r for r in D['requests'] if r['cohort']=='official'];H=[r for r in D['requests'] if r['cohort']=='historical'];S=D['cohorts']['public'];M=S['metrics']
def f(x,n=2):return '-' if x is None else f'{x:.{n}f}'
def save(fig,name):
 fig.savefig(CHART/(name+'.png'),dpi=165,bbox_inches='tight');fig.savefig(CHART/(name+'.svg'),bbox_inches='tight');plt.close(fig)
def chart_latency():
 fig,ax=plt.subplots(figsize=(11,4.6));left=[0.]*7
 for key,label,color in [('dispatch_queue_s','派发 / 排队',P['queue']),('llm_or_echo_s','云端 LLM',P['cloud']),('tts_adapter_s','完整语音就绪',P['tts']),('buffer_to_receipt_s','媒体 / 缓冲 / 回执',P['buffer']),('first_to_complete_s','已开始后的播报',P['play'])]:
  values=[r[key] for r in R];ax.barh([r['case'] for r in R],values,left=left,label=label,color=color,height=.6);left=[x+y for x,y in zip(left,values)]
 for i,r in enumerate(R):
  ax.plot(r['collector_to_first_s'],i,'|',color=P['ink'],markersize=18,markeredgewidth=1.5)
  ax.text(r['collector_to_complete_s']+.7,i,f"{r['collector_to_first_s']:.1f} / {r['collector_to_complete_s']:.1f}s",va='center',fontsize=9)
 ax.set_xlim(0,85);ax.invert_yaxis();ax.set_xlabel('A 采集器收到弹幕之后的秒数；竖线 = 首次正样本播放回执');ax.legend(loc='upper center',bbox_to_anchor=(.47,1.18),ncol=3,frameon=False);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True);fig.tight_layout();save(fig,'reply-timeline')
def chart_tts():
 fig,ax=plt.subplots(figsize=(11,4.4));xs=range(7);g=[r['moss_generation_s'] for r in R];codec=[r['moss_codec_s'] for r in R];other=[r['tts_adapter_s']-g[i]-codec[i] for i,r in enumerate(R)]
 ax.bar(xs,g,color=P['tts'],label='MOSS 自回归生成 / GPU');ax.bar(xs,codec,bottom=g,color=P['cloud'],label='音频 codec / CPU');ax.bar(xs,other,bottom=[a+b for a,b in zip(g,codec)],color=P['queue'],label='适配 / 编码 / 其他等待')
 ax.plot(xs,[r['audio_seconds'] for r in R],'o-',color=P['buffer'],label='产出语音时长',lw=1.5)
 for i,r in enumerate(R):ax.text(i,r['tts_adapter_s']+.7,f"RTF {r['moss_rtf']:.2f}",ha='center',fontsize=9)
 ax.set_xticks(list(xs),[r['case'] for r in R]);ax.set_ylabel('秒');ax.set_ylim(0,39);ax.legend(ncol=2,frameon=False,loc='upper left');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True);fig.tight_layout();save(fig,'tts-generation')
def chart_receiver():
 rows=D['render']['series'];fig,axs=plt.subplots(2,1,figsize=(11,4.7),sharex=True,gridspec_kw={'hspace':.2})
 axs[0].plot([r['elapsed_s'] for r in rows],[r['fps'] for r in rows],color=P['tts'],lw=1);axs[0].axhline(25,color=P['queue'],ls='--',lw=.8);axs[0].set_ylabel('Canvas 更新 FPS');axs[0].set_ylim(23.8,26)
 axs[1].plot([r['elapsed_s'] for r in rows],[r['buffer_ms']/1000 for r in rows],color=P['buffer'],lw=1);axs[1].axhline(4,color=P['queue'],ls='--',lw=.8);axs[1].set_ylabel('音频缓冲 / s');axs[1].set_ylim(3.9,4.1);axs[1].set_xlabel('官方客户端五段验收内的相对秒数 / 317 次采样')
 for ax in axs:ax.grid(alpha=.15)
 save(fig,'receiver-stability')
def chart_capacity():
 fig,axs=plt.subplots(1,2,figsize=(11,3.6));names=['A4090','B3080'];res=D['resources']
 for j,(key,den,label) in enumerate([('gpu_used_mib',1024,'GPU 显存 / GiB'),('ram_used_gib',1,'整机 RAM / GiB')]):
  used=[res[n]['summary'][key]['mean']/den for n in names];total=[res[n]['gpu_total_mib']/1024 if j==0 else res[n]['ram_total_gib'] for n in names]
  axs[j].barh(names,total,color='#E7EDF4',height=.5,label='容量');axs[j].barh(names,used,color=[P['tts'],P['cloud']],height=.5,label='下播后平均占用')
  for i,(u,t) in enumerate(zip(used,total)):axs[j].text(u+.5,i,f'{u:.2f} / {t:.2f}',va='center',fontsize=10)
  axs[j].set_xlim(0,72);axs[j].set_xlabel(label);axs[j].invert_yaxis();axs[j].spines['left'].set_visible(False)
 fig.tight_layout();save(fig,'resource-capacity')
def chart_sampling():
 fig,axs=plt.subplots(2,1,figsize=(11,4.6),sharex=True)
 for role,color in [('A4090',P['tts']),('B3080',P['cloud'])]:
  rows=D['resources'][role]['series'];axs[0].plot([r['elapsed_s'] for r in rows],[r['cpu_percent'] if r['cpu_percent'] is not None else float('nan') for r in rows],color=color,label=role,lw=1.5);axs[1].plot([r['elapsed_s'] for r in rows],[r['gpu_power_watts'] for r in rows],color=color,label=role,lw=1.5)
 axs[0].set_ylabel('整机 CPU / %');axs[0].set_ylim(0,105);axs[0].legend(frameon=False);axs[1].set_ylabel('GPU 功耗 / W');axs[1].set_ylim(0,125);axs[1].set_xlabel('各自采样开始后的秒数；两台采样窗口错开约 54 秒')
 for ax in axs:ax.grid(alpha=.15)
 fig.tight_layout();save(fig,'post-offair-sampling')
def chart_rss():
 fig,axs=plt.subplots(1,2,figsize=(11,3.4))
 for ax,role,color in zip(axs,['A4090','B3080'],[P['tts'],P['cloud']]):
  groups=D['resources'][role]['process_groups'];labels=[p['role'].replace('Livehime-process-tree','直播姬进程组').replace('avatar-or-worker','人物 / 辅助进程') for p in groups];values=[p['rss_gib']['mean'] for p in groups]
  ax.barh(labels,values,color=color,height=.55);ax.invert_yaxis();ax.set_xlim(0,10);ax.set_xlabel(f'{role} 进程 RSS / GiB')
  for i,v in enumerate(values):ax.text(v+.1,i,f'{v:.2f}',va='center',fontsize=9)
 fig.tight_layout();save(fig,'process-memory')
for method in [chart_latency,chart_tts,chart_receiver,chart_capacity,chart_sampling,chart_rss]:method()

def mdtable(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(str(x) for x in r)+' |' for r in rows])
cycle_rows=[['采集 / 派发 / 排队',f(M['dispatch_queue_s']['mean']),f(M['dispatch_queue_s']['min'])+' - '+f(M['dispatch_queue_s']['max']),'A 采集 received_at 至 request.thinking'],['云端 LLM 与人格上下文',f(M['llm_or_echo_s']['mean']),f(M['llm_or_echo_s']['min'])+' - '+f(M['llm_or_echo_s']['max']),'request.thinking 至 text_ready；非首 token 延迟'],['完整语音就绪',f(M['tts_adapter_s']['mean']),f(M['tts_adapter_s']['min'])+' - '+f(M['tts_adapter_s']['max']),'text_ready 至 audio_ready；含服务与适配'],['媒体 / 缓冲 / 回执',f(M['buffer_to_receipt_s']['mean']),f(M['buffer_to_receipt_s']['min'])+' - '+f(M['buffer_to_receipt_s']['max']),'audio_ready 至第一个已接受正样本回执'],['首次播放后至完整播完',f(M['first_to_complete_s']['mean']),f(M['first_to_complete_s']['min'])+' - '+f(M['first_to_complete_s']['max']),'第一个正样本回执至 playback.completed']]
request_rows=[[r['case'],r['created_at_local'][6:],r['reply_characters'],f(r['llm_or_echo_s']),f(r['tts_adapter_s']),f(r['buffer_to_receipt_s']),f(r['collector_to_first_s']),f(r['collector_to_complete_s']),r['status']] for r in R]
resource_rows=[]
for role,res in D['resources'].items():
 s=res['summary'];resource_rows.append([role,f(res['gpu_total_mib']/1024),f(s['gpu_used_mib']['mean']/1024),f(s['ram_used_gib']['mean'])+' / '+f(res['ram_total_gib']),f(s['cpu_percent']['mean'])+' / '+f(s['cpu_percent']['median'])+' / '+f(s['cpu_percent']['max']),f(s['gpu_util_percent']['mean']),f(s['gpu_power_watts']['mean'])])
scheduling=[['弹幕派发轮询','1,000 ms','有活跃回复或已有排队时不再接入下一条'],['最小回复启动间隔','8,000 ms','从上次进入队列起计；不是额外固定等待'],['同观众冷却','15,000 ms','基于当前采集身份；脱敏身份不足以长期识别'],['平台事件有效期 / 容量','45,000 ms / 50 条','过期标为 EXPIRED；不保证所有弹幕都会回复'],['DSH 活跃 / 待处理','1 / 4','一房间只允许一个有效发声任务'],['DSH 排队 TTL / 活跃期限','180 s / 300 s','与平台 45 s TTL 是不同层级'],['LLM / TTS 超时','90 s / 120 s','超时失败并保留账本，不伪造完成'],['MOSS 串行服务','1 活跃，至多 4 已登记请求','当前上游单任务，未压测并发吞吐'],['MOSS 分段 / token','70 字 / 每段最多 800 token','分段全合成后才返回完整 WAV'],['音频 / 视频节拍','16 kHz 单声道；25 FPS','24 kHz TTS 波形重采样，媒体回执按有效样本确认'],['A 到 B 音频缓冲','4,000 ms','用约 4 s 启动等待换取抗网络抖动'],['播放心跳 / 进度回执','1,000 ms / 250 ms','实际有效租约 30 s；恢复时以代次隔离旧音频'],['下播 drain 上限','30 s','自然结束必须收到连续样本与 natural_end'],['维护轮询 / 静默窗口','5 s / 下播后 120 s','开播会打断或延迟后台压缩，不在直播期提交'],['每日 / 每周维护','03:30 / 周一 04:10','Asia/Taipei；启动补查过去 12 h 的计划点'],['维护并发 / 单块限制','1 / 200 事件、24 KB、重叠 2 事件','每次运行至多 8 次模型调用，每日 20 次'],['维护重试 / 租约','最多 5 次；5 s 指数退避至 300 s','模型超时 90 s，租约 120 s，心跳 15 s'],['预算耗尽 / 渠道不可用','延迟 1 h / 60 s','一小时后只是重查；日额度未重置仍可能继续延迟']]
priorities=[['P0','修复记忆维护失败并保留失败原因','今日 20/20；当前 DEFERRED / budget；旧任务 6 个 extraction_failed','先做结构化返回与来源引用校验，再按失败类别有限重试；清理预算后验证真实持久事实','不应直接加大额度掩盖重复失败'],['P0','公开开播状态对账','05:41:23 平台 PREPARING 后 UI 曾仍显示推流','周期读公开直播状态，并关联直播姬结束事件；发现不一致立即显著提示','不自动重开被平台终止的直播'],['P1','让首句尽快生成并播出','MOSS 全音频 RTF 1.95；TTS 占首播等待约 62.2%','比较保持音色的短句队列与真正流式声码器；保留语音连续性与取消栅栏','目标尚未验证，不能承诺秒回'],['P1','评估本地 codec 的 GPU 路径','当前 CPU codec 平均 4.33 s；A 有显存余量','隔离测试该模型 codec GPU 兼容、音质、总延迟与峰值；完整回归后再替换','能否加速及提升幅度尚未测量'],['P1','根据回复长度控制等待','19 - 75 字对应 10.96 - 32.97 s 完整语音准备','先验证 20 - 40 字首句，加后续补充；不能截断语音或虚报完成','本报告没有修改内容策略'],['P2','自适应接收缓冲','稳定阶段 4 s；长时到达间隔最大 551.5 ms','以 4 s 为基线测试 2 s，再分网络条件对比欠载与首播等待','理论可少约 2 s，不等于已实现'],['P2','统一 trace ID 与采样','MOSS UUID 与 DSH request_id 不同；CPU 有 100% 离群点','贯穿 trace ID、单调时钟阶段打点、每秒 NVML / CPU；区分直播、生成、待机窗口','本次 MOSS 使用经过 32 对匹配校验的分析关联'],['P2','测观众真实端到端延迟与礼物','本次未验证礼物；未测 CDN 观众端音画起点','下一场设置独立观看端，统一时钟标记、音画检测与免费礼物事件留证','当前 34.10 s 仅截止官方客户端播放回执']]
limits=[
'主结论以本场 7 条真实 blivedm 弹幕为样本；不是大并发、长周期 SLA。经验 P95 为线性插值描述，7 条样本不能预测稳定尾延迟。',
'首次播放是官方直播姬嵌入源已接受的正样本回执。它包含回执发送间隔与传输，不能精确定位扬声器物理出声，也不含 B站 CDN 和观众播放器延迟。',
'主延迟使用 A 设备收到事件与 A 收到回执的同机时钟。平台时间只作参考：曾出现平台到采集器 -212 ms，不能把它解释成负网络耗时。A / B / 平台未做严格时钟同步。',
'五段官方验收含 4 条 Echo + 1 条云端 Chat，不能用其较低平均值替代全部 AI 对话延迟。测试脚本的轮询耗时与 A 账本起止不同，也不能混用。',
'历史 20 条保留全部异常：H04 状态 UNKNOWN、只确认了 80,640 / 102,400 样本；H20 从 audio_ready 到正回执 159.913 s。它们来自较早 B 本机调试，不代表当前 B3080 稳定窗口。',
'资源采样是下播后、模型常驻且预览媒体继续运行的 60 s 窗口。每台 30 条，CPU 第一条弃用后为 29 条；不代表直播 / TTS 峰值。A CPU 仍有 100% 离群点，原值保留，原因未归因。',
'NVIDIA 整卡占用、PyTorch allocated 峰值、进程 RSS、整机已用 RAM 口径不同。RSS 可能含共享页，不能简单相加当作独占物理内存。功耗为整卡瞬时采样，不是电费或训练能耗。',
'317 次 FPS 为 Canvas 更新计数；不是显示器实际呈现 FPS、MuseTalk 离线吞吐或观众 CDN FPS。零欠载是该采样范围计数，并非未来零卡顿保证。',
'MOSS 关联采用日志先后顺序，再校验全部 32 条回复字数及音频有效样本时长；原适配器没有直接记录同一个 trace ID。当前生成阶段平均值具备这一关联边界。',
'input_tokens / output_tokens 来自渠道返回的 usage。已知计数可以累加；2 次维护 usage 未知，费用、缓存命中、云端排队与首 token 细分未采集。6000 是上下文估计预算，不是提供方实际总输入的硬上限。',
'本次没有持续记录口型批次耗时、实时 CPU / GPU 全程曲线、显存分进程 NVML 峰值、上行直播编码码率、观众礼物或观众视频录制；缺项按未测列出。',
'公开报告只含案例编号、时间、长度、用量与状态；不含对话正文、观众昵称、身份哈希、Cookie、推流密钥或渠道密钥。原始私有导出保留在项目 outputs，未提交仓库。']
overall=sum(r['collector_to_complete_s'] for r in R);occupied=sum(r['accept_to_complete_s'] for r in R)
long=D['resources']['B3080']['receiver_longrun'];pm=long['player_metrics'];band=long['media_bytes']*8/pm['audio_clock_seconds']/1e6
md=f'''# 女A / 林知夏：双机直播周期与性能分析

数据日期：2026-10-27，Asia/Taipei (UTC+08:00)。本场已由用户下播，采集器已停止，内部会话 ENDED，A 的模型保留常驻。此文档是冻结快照，不会实时刷新。

[交互可视化](report.html) · [PDF](report.pdf) · [逐条 CSV](data/requests.csv) · [资源 CSV](data/resource-samples.csv) · [完整测量 JSON](data/evidence.json)

## 结论与样本

本场 7 条真实弹幕全部完成。A 收到弹幕至官方直播姬首次正样本播放回执平均 **34.10 s**，中位 **33.46 s**，范围 **20.32 - 51.70 s**；至整句播完平均 **44.40 s**，范围 **24.68 - 67.48 s**。此前三条的约 31.81 s 是子样本；本报告扩大到全部七条，因此平均值不同。

等待主要在完整语音生成：平均 21.21 s，占首次播放等待约 {M['tts_adapter_s']['sum']/M['collector_to_first_s']['sum']*100:.1f}%；云端 LLM 平均 7.72 s，占约 {M['llm_or_echo_s']['sum']/M['collector_to_first_s']['sum']*100:.1f}%；媒体、缓冲与回执约 4.69 s。画布连续输出和 AI 回复开始速度是两个问题。

{mdtable(['分组','条数','完成','首次回执均值 / s','完整完成均值 / s','说明'],[[name,D['cohorts'][key]['total'],D['cohorts'][key]['completed'],f(D['cohorts'][key]['metrics']['collector_to_first_s']['mean']),f(D['cohorts'][key]['metrics']['collector_to_complete_s']['mean']),detail] for key,name,detail in [('public','R01 - R07 实播','真实弹幕，全为 Chat'),('official','C01 - C05 官方客户端验收','4 Echo + 1 Chat'),('historical','H01 - H20 较早调试','B 本机等旧路径，1 UNKNOWN，保留异常')]])}

当前 A 账本在本次导出日期内保留 32 条：31 COMPLETED、1 UNKNOWN。不是对整个项目所有历史直播的穷尽审计。五段脚本墙钟完成耗时分别为 38.857 / 32.621 / 26.955 / 23.353 / 39.910 s；下表与图统一用 A 账本，避免混入脚本轮询与跨机时钟差。

## 当前运行架构

```mermaid
flowchart LR
  D[公开直播间弹幕] --> A[A4090: blivedm + DSH / Humanity]
  A --> L[云端 gpt-6-luna]
  L --> T[A4090: MOSS 04 语音]
  T --> V[A4090: MuseTalk FP16 batch8 + NVENC]
  V -->|虚拟局域网 H264 + PCM| B[B3080: 原生轻量接收器]
  B --> J[官方直播姬: 浏览器素材 + 源内音频]
  J --> P[B站分发至观众]
  J -->|有效样本播放回执| A
```

A 为 48 GB 4090、约 64 GB RAM，承担模型、状态、语音、口型、融合、媒体编码与采集；B 为 10 GB 3080、约 64 GB RAM，仅接收、软件 H264 解码、Canvas / WebAudio 播放及官方推流。B 不加载人物 / TTS 模型。旧 B 的模型进程已停，415 个状态文件已独立归档，未自动合并到 A。原本本机 B 接收器已停，不重复推流。

人物是女A / 林知夏，沿用日光宿舍与 48 个动作素材，720 x 1280、25 FPS；身体动作来自素材库，实时推理用于口型与融合。A MuseTalk FP16 batch8；MOSS04 明朗亲和，NF4 4-bit / BF16 compute、FP32 CPU codec。DSH 0.2.0-rc.2、Humanity 0.1.17 通过连接层提供人格与记忆投影，native_humanity_tools=false，不能称为全部原生 Humanity 功能已开启。Node v24.22.1。

## 回复周期：收到弹幕到完整播完

![七条弹幕分阶段时间线](charts/reply-timeline.png)

{mdtable(['阶段','平均 / s','范围 / s','精确定义'],cycle_rows)}

首次回执平均 = 0.485 派发 + 7.717 LLM + 21.208 完整语音 + 4.693 媒体与回执 = 34.103 s。之后平均 10.299 s 完成播报，总周期 44.403 s。首次回执前已消耗少量音频样本，所以完整播放余量与音频总时长不严格相等。

{mdtable(['案例','本地入账时间','回复字数','LLM/s','TTS/s','缓冲回执/s','首播/s','完成/s','状态'],request_rows)}

单房间只发一个回复，以这七条平均完整周期粗略折算，持续服务能力约 **{60/M['collector_to_complete_s']['mean']:.2f} 条/分钟**。这是由样本周期推算的排队规划值，不是并发压力测试或平台观众数上限。增加 pending=50 不会提高生成速度；高频弹幕在 45 s TTL 下会过期。

## 语音生成周期

![语音生成与产出时长](charts/tts-generation.png)

本场共合成 {sum(r['reply_characters'] for r in R)} 字、{sum(r['audio_seconds'] for r in R):.2f} s 语音；MOSS 服务 wall 总计 {sum(r['moss_wall_s'] for r in R):.3f} s，整体加权 **RTF {S['weighted_moss_rtf']:.3f}**。RTF = 合成墙钟秒 / 产出音频秒；1.95 表示合成 10 s 音频约需 19.5 s，当前语音引擎没有达到边生成边实时播放的速度。

平均 MOSS GPU 自回归生成 16.019 s、CPU codec 4.328 s、服务 wall 20.364 s。服务 wall 之外还有约 {statistics.mean(r['tts_adapter_other_s'] for r in R):.3f} s 适配、清理、传输与准备；具体子项未独立打点。wall 在进入串行锁前计时，可能包含锁等待；本次上游一次只投递一个活跃请求。

{mdtable(['案例','回复字数','分段','音频/s','GPU生成/s','CPU codec/s','服务wall/s','RTF','PyTorch峰值/MiB'],[[r['case'],r['reply_characters'],r['moss_parts'],f(r['audio_seconds']),f(r['moss_generation_s']),f(r['moss_codec_s']),f(r['moss_wall_s']),f(r['moss_rtf']),f(r['moss_peak_allocated_mib'],1)] for r in R])}

代码先取得整段 WAV 再上报 audio_ready；即使按 70 字分成多段，也会先合成完并拼接后返回。R03 / R06 分成 2 段。当前 4 s 接收缓冲是在完整语音已生成后发生，不能用画面稳定 25 FPS 证明语音低延迟。MOSS 三次保留启动记录分别为 70.970 / 62.823 / 60.795 s；当前最后一次约 60.795 s，不属于逐次回复耗时。

## 画面、音频与传输稳定性

![五段验收接收端曲线](charts/receiver-stability.png)

官方直播姬真实浏览器源五段窗口：{D['render']['sample_span_s']:.3f} s、317 次采样；Canvas 均值 {D['render']['canvas_fps']['mean']:.3f} FPS，中位 25.285，范围 24.466 - 25.390；音频缓冲均值 {D['render']['audio_buffer_ms']['mean']/1000:.3f} s，范围 {D['render']['audio_buffer_ms']['min']/1000:.3f} - {D['render']['audio_buffer_ms']['max']/1000:.3f} s。媒体欠载 / 缺包 / 解码错误 / 主动跳帧均为 0，窗口内最大到达间隔 91.8 ms。重复请求拒绝、暂停恢复、云端人格回复均通过。

延长观察至下播后：同一接收器 1 次上游 WebSocket 连接、0 上游错误，媒体时钟累计 {pm['audio_clock_seconds']/60:.2f} 分钟，仍为 0 欠载 / 缺包 / 解码错误 / 跳帧；最大到达间隔升至 551.5 ms，缓冲末值 {pm['audio_buffer_ms']/1000:.3f} s。此窗口包括待机预览和公开停播，不能当作同等时长的公开直播成功证明。

累计网关媒体 {long['media_bytes']/1e9:.3f} GB / 媒体时钟 {pm['audio_clock_seconds']:.2f} s，粗算 {band:.3f} Mbps；这是 A 到 B H264 + PCM 的平均负载，未含完整 TCP / WebSocket 等线缆开销，不是 B 到平台的推流码率或网络峰值。配置视频目标 3 Mbps，PCM 16 kHz x 16 bit 单声道理论 0.256 Mbps。

## 资源占用：下播后的常驻与预览

![整卡显存与整机内存](charts/resource-capacity.png)

**采样窗口严格标为下播后**：A {D['resources']['A4090']['start_local']} 开始，B {D['resources']['B3080']['start_local']} 开始，各运行约 60 s、2 s 目标间隔，30 份 GPU / RAM 样本；CPU 首条无稳定区间，剔除后各 29 条。两窗口错开约 54 s，不是同步负载对比。

{mdtable(['设备','GPU容量/GiB','已用显存/GiB','RAM已用/总GiB','CPU均/中/峰%','GPU均%','GPU均功耗/W'],resource_rows)}

A 整卡常驻 13,302 MiB，约 12.99 GiB / 47.99 GiB，剩余约 35 GiB。B 约 1,252 - 1,255 MiB，约 1.22 GiB / 10 GiB。MOSS 本场 PyTorch allocated 峰值约 6,382 - 6,397 MiB，仅是 TTS 进程分配器的逐次峰值，不能与整卡 13,302 MiB 相加。旧 B 模型退出前后 9,613 -> 1,223 MiB，释放 8,390 MiB，约 8.19 GiB。

此前另一段 360 s 的 A H264 验证采到 GPU 利用率峰值 68%、NVENC 1%、显存 13,300 MiB；它不覆盖本次完整实播，不能代替本场峰值。本场逐秒直播 GPU / CPU 峰值未完整采集，按未测处理。

![下播后采样曲线](charts/post-offair-sampling.png)

A CPU 均值 14.27%、中位 7.8%、峰 100%；100% 离群点保留，未能归因到模型。A GPU 仍仅 0 - 1%，说明这个采样窗口没有持续 TTS 生成。B GPU 3 - 5%，整卡功耗约 107 W，高于 A 的约 53 W 待机采样值；不能据此宣称 3080 推流更耗能，也不能把低利用率等同于低显存或低延迟。

## 进程与调度占用

![分组进程RSS](charts/process-memory.png)

{mdtable(['设备','进程分组','平均 RSS / GiB','平均整机 CPU / %'],[[role,p['role'],f(p['rss_gib']['mean'],3),f(p['cpu_host_percent']['mean'],3)] for role,res in D['resources'].items() for p in res['process_groups']])}

进程 CPU 由 psutil 单核口径除以逻辑 CPU 数转换为整机比例：A 80 逻辑 / 40 物理，B 48 逻辑 / 24 物理。RSS 分组只识别采样开始时的相关进程，不是完整进程树归属审计，不能求和作为系统总占用。ComfyUI 留在两机内存中，本轮未调用、未加载新模型；不要归为直播模型独占开销。

{mdtable(['机制','当前值','实际行为'],scheduling)}

实时媒体边：A 口型 / 融合随有效音频样本推进，NVENC 编码一份共享 H264 流；B 接收后软件解码并在 Canvas / WebAudio 播放，再由官方直播姬独立编码公开流。生成结束不等于播放结束，完整样本确认和 natural_end 才将请求写为 COMPLETED。中断 / 重连按 runtime_epoch、generation 与播放权威隔离，旧音频不能写成当前完成。

## 云端用量与上下文

{mdtable(['案例','LLM阶段/s','输入token','输出token','已结算调用'],[[r['case'],f(r['llm_or_echo_s']),r['input_tokens'],r['output_tokens'],r['model_calls']] for r in R])}

7 条实播前台调用 usage 均已结算，共 41,745 input / 292 output tokens；加 1 条官方 Chat 验收，当日保留的前台为 49,122 / 330。不能从此推算渠道费用，价格和缓存细分未采集。有效策略上下文估计 6,000 tokens、输出最多 256 tokens、最终播报最多 160 字；提供方实际单次输入 635 - 7,821 tokens，估算预算不等于总提示词硬截断。

## 平台状态与下播记忆

公开直播姬日志时间：05:10:19 返回开播成功，05:10:23 连接媒体；05:41:23.308 收到平台 PREPARING，随后媒体流停止。其后直播姬界面曾仍显示推流，而公开查询接口已未开播，用户也确认不能观看。未采集到平台停止的具体原因，不能归因为审核、网络或硬件。用户重开后公开接口记录 06:15:13；R07 在 A 06:23:11 入账并完整播完。用户后来下播，内部在 A 06:30:03.942 结束。不同设备时间未严格对齐，这些是各来源日志时间，不据此推断毫秒级跨端间隔。

本次内部会话从 A 05:06:34.040 到 06:30:03.942，约 83 分 30 秒；期间包含公开平台中断，**不是连续公开直播时长**。直播姬状态、应用会话状态、公开房间状态需要分别对账。

下播后 2 分钟静默窗口于 A 06:32:03.942 到期。截止 A {D['maintenance']['observed_utc']}，本场压缩任务状态 **DEFERRED / budget**，not_before=2026-10-26T23:34:19.928Z，即本地 07:34:19.928。20 / 20 当日维护调用额度已耗尽，下一次是重查，不承诺届时完成；若额度未恢复将继续延迟。

当前全部保留维护任务 10 个：3 COMPLETED、6 FAILED (extraction_failed，重试 5 次)、1 DEFERRED (budget)。6 个失败来自较早的 3 场压缩及其 daily_merge 重试。当前库持久事实 memory_entries=0，摘要版本 6 个（3 segment + 3 broadcast），不能将“上下文可回复”表述为“本场长期事实记忆整理成功”。官方五段验收的 post_broadcast job 在 05:04:23.304 已提交摘要，但新增持久候选数为 0。

{mdtable(['日期','调用范围','已计调用','已知输入token','已知输出token','usage未知调用'],[[r['date'],r['scope'],r['counted_calls'],r['input_tokens_known'],r['output_tokens_known'],r['usage_unknown_calls']] for r in D['maintenance']['daily_usage']])}

当前只用公开弹幕上下文。blivedm 脱敏 identity_quality=display_only，没有可验证稳定 viewer_id，不做跨场个人身份记忆。A 是唯一在线状态写入者；B 旧历史归档不自动混入。

## 可执行优化顺序（本报告未部署这些变更）

{mdtable(['优先级','项目','数据依据','下一步实现与验收','边界'],priorities)}

## 证据边界与缺项

'''+ '\n\n'.join(f'{i}. {s}' for i,s in enumerate(limits,1))+f'''

## 全量案例索引

交互网页可以筛选全部 32 条。H 是历史调试，C 是当前官方客户端验收，R 是本场真实弹幕。UNKNOWN 的完成耗时留空，不伪造 0 或成功。

{mdtable(['案例','分组','入账本地时间','模式','字数','首回执/s','完成/s','RTF','状态'],[[r['case'],r['cohort'],r['created_at_local'],r['mode'],r['reply_characters'],f(r['collector_to_first_s']),f(r['collector_to_complete_s']),f(r['moss_rtf']),r['status']] for r in D['requests']])}

## 可重建与来源

- 运行时代码：`{D['runtime_commit']}`；报告前仓库文档：`{D['documentation_base_commit']}`。
- 数据：A SQLite 只读事务导出 requests / stream_events / utterances / playback_receipts，平台事件 occurred_at / received_at，MOSS JSON 日志，B 官方源 317 份指标，A/B 原生 psutil + nvidia-smi 待机采样。
- 主要公式：首回执 = A 首个 accepted 且 played_samples > 0 的时间 - A 平台事件 received_at；完成 = playback.completed - received_at；TTS = audio_ready - text_ready；LLM = text_ready - request.thinking。
- P95 为排序后线性插值；样本数见各图与 JSON；历史 UNKNOWN 不进入完成周期统计。
- 从仓库根执行 `python -X utf8 devtools/build-performance-report.py`，仅使用 `data/evidence.json` 重建图、网页、Markdown 和 PDF，不访问机器、模型或平台。依赖 matplotlib / reportlab / Pillow，中文字体 Microsoft YaHei。
- 私有来源导出 SHA-256：

{mdtable(['私有导出标识','SHA-256'],D['provenance']['hashes'].items())}

本报告没有新开播、没有新增直播录制、没有修改模型精度或调度策略。最终打开的报告页为用户交付页；用于验证的浏览器会话已关闭。
'''
(OUT/'report.md').write_text(md,encoding='utf-8')

template=(REPO/'devtools/performance-report.html').read_text(encoding='utf-8')
def table_html(headers,rows):return '<div class="table-scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table></div>'
replacements={'@@EVIDENCE@@':json.dumps(D,ensure_ascii=False,separators=(',',':')).replace('</','<\\/'),'@@SCHEDULE@@':table_html(['机制','当前值','行为'],scheduling),'@@PRIORITIES@@':table_html(['优先级','项目','依据','实现与验收','边界'],priorities),'@@LIMITS@@':'<ol>'+''.join('<li>'+html.escape(x)+'</li>' for x in limits)+'</ol>','@@RESOURCES@@':table_html(['设备','显存总GiB','已用GiB','RAM已用/总GiB','CPU均/中/峰%','GPU均%','GPU功耗W'],resource_rows)}
for key,value in replacements.items():template=template.replace(key,value)
for name in ['reply-timeline','tts-generation','receiver-stability','resource-capacity','post-offair-sampling','process-memory']:
 template=template.replace('@@CHART:'+name+'@@','data:image/png;base64,'+base64.b64encode((CHART/(name+'.png')).read_bytes()).decode())
assert '@@' not in template
(OUT/'report.html').write_text(template,encoding='utf-8')

# PDF is intentionally paginated so every topic remains a useful printed leaf.
pdfmetrics.registerFont(TTFont('YaHei',str(FONT),subfontIndex=0))
pdfmetrics.registerFont(TTFont('YaHeiBold','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
STYLE={'body':ParagraphStyle('body',fontName='YaHei',fontSize=9.2,leading=15,textColor=colors.HexColor(P['ink']),spaceAfter=7,wordWrap='CJK'),'h1':ParagraphStyle('h1',fontName='YaHeiBold',fontSize=22,leading=29,textColor=colors.HexColor(P['ink']),spaceAfter=14),'h2':ParagraphStyle('h2',fontName='YaHeiBold',fontSize=13,leading=20,textColor=colors.HexColor(P['tts']),spaceAfter=9),'caption':ParagraphStyle('caption',fontName='YaHei',fontSize=8,leading=12,textColor=colors.HexColor(P['muted']),spaceAfter=8),'cell':ParagraphStyle('cell',fontName='YaHei',fontSize=7.6,leading=11,wordWrap='CJK',textColor=colors.HexColor(P['ink']))}
story=[]
def para(text,style='body'):story.append(Paragraph(html.escape(text).replace('\n','<br/>'),STYLE[style]))
def heading(title,kicker=None):
 if story:story.append(PageBreak())
 if kicker:para(kicker,'caption')
 para(title,'h1')
def figure(name,height=215):
 from PIL import Image as PILImage
 path=CHART/(name+'.png');im=PILImage.open(path);w,h=im.size;scale=min(510/w,height/h);story.append(Image(str(path),width=w*scale,height=h*scale));story.append(Spacer(1,8))
def grid(headers,rows,widths=None):
 cells=[[Paragraph(html.escape(str(v)),STYLE['cell']) for v in row] for row in [headers]+list(rows)]
 table=Table(cells,colWidths=widths or [510/len(headers)]*len(headers),repeatRows=1,hAlign='LEFT');table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E6EDF5')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#BDCADB')),('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#DEE5EF')),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]));story.append(table);story.append(Spacer(1,9))
heading('一句话，如何抵达直播间','女A / 林知夏     实播测量档案     2026.10.27')
para('A4090 负责人物与语音，B3080 负责接收与官方直播姬。复盘收到弹幕、云端对话、完整语音生成、媒体播放和下播记忆的每一个周期。')
figure('reply-timeline',240)
grid(['7 条真实弹幕','平均首次回执','平均完整完成','语音加权 RTF'],[['7 / 7 完整播完','34.10 秒','44.40 秒','1.95']])
para('首播等待约 62.2% 来自完整语音准备。播放源稳定约 25 FPS，但当前语音服务需要先生成整段 WAV；两者对应不同性能问题。')
para('下播后的状态：内部会话已结束，弹幕采集已停止，模型保持常驻。记忆维护仍 DEFERRED / budget，不能称为长期事实整理已完成。')
para('截止官方直播姬正样本播放回执；不含平台 CDN 与观众端延迟。报告为冻结快照。','caption')
heading('测量对象与口径','范围 / 时钟 / 数据完整性')
grid(['分组','样本','完成','首次均值/s','用途'],[['本场真实弹幕',7,7,'34.10','主性能结论'],['官方客户端验收',5,5,'22.83','4 Echo + 1 Chat'],['较早调试',20,19,'30.57','含异常，不混入主均值']],[100,45,45,80,240])
para('当前 A 日期内留存 32 条记录：31 COMPLETED，1 UNKNOWN。完整逐条表见附录和 CSV；公开数据不包含对话正文或观众身份。')
para('主要时间都取 A：平台采集 received_at、状态事件、A 收到 B 播放回执。同机时间相减可避免跨机器时钟差；平台 occurred_at 只作参考，曾与 A 出现 -212 ms 差值。')
grid(['计时项','起点','终点'],[['首次播放回执','A 采集器 received_at','首个 accepted 且 played_samples > 0 的回执'],['完整回复','A 采集器 received_at','playback.completed'],['LLM 阶段','request.thinking','utterance.text_ready'],['完整语音准备','utterance.text_ready','utterance.audio_ready'],['缓冲与回执','utterance.audio_ready','首个正样本回执'],['RTF','MOSS wall seconds','除以有效音频 seconds']],[100,170,240])
para('首次回执不是扬声器物理起音时间。官方五段脚本墙钟值含轮询与跨设备计时，和 A 账本有差异；本报告的周期对比统一用 A。经验 P95 采用线性插值，7 条小样本仅用于描述。')
heading('当前双机职责','原生 Windows / 虚拟局域网 / 无 OBS')
grid(['组件','A4090','B3080'],[['硬件','48 GB GPU；约 64 GB RAM；80 逻辑 CPU','10 GB GPU；约 64 GB RAM；48 逻辑 CPU'],['模型','MOSS04 + MuseTalk FP16 batch8','不加载 TTS / 人物模型'],['对话状态','DSH / Humanity 连接层、SQLite 唯一写者','只转发、渲染和消费回执'],['媒体','720 x 1280 / 25 FPS；48 动作素材；NVENC','软件 H264 解码；Canvas / WebAudio'],['链路','共享 H264 + PCM -> 虚拟局域网','8020 轻量接收 -> 官方直播姬 -> 平台'],['声音','MOSS24k WAV -> 16k PCM','浏览器素材源内音频；桌面 / 麦克风静音']],[80,215,215])
para('A：女A / 林知夏，日光宿舍，MOSS v04 明朗亲和。NF4 4-bit / BF16 compute，FP32 CPU codec。DSH 0.2.0-rc.2，Humanity 0.1.17，Node v24.22.1。native_humanity_tools=false；人格与记忆由项目连接层整合。')
para('B 旧推理进程已经退休，415 个旧状态文件归档保留，未混入 A。先前本机接收器已关闭。身体动作使用预生成素材，口型与融合随当前语音推进，不是每次完整生成一个新身体视频。')
para('MOSS 启动冷加载留存 70.970、62.823、60.795 秒；当前采用模型常驻，冷加载不计入每次回复。')
heading('七条真实回复的完整周期','首回执与整句结束分别统计')
figure('reply-timeline',215)
grid(['案例','字数','LLM','TTS','媒体','首播','完成'],[[r['case'],r['reply_characters'],f(r['llm_or_echo_s']),f(r['tts_adapter_s']),f(r['buffer_to_receipt_s']),f(r['collector_to_first_s']),f(r['collector_to_complete_s'])] for r in R],[48,40,78,78,78,94,94])
para('单位：秒。首播平均 34.103，中位 33.457，最慢 51.695；完整平均 44.403，最慢 67.479。首次之前派发均值仅 0.485 秒，低流量场景没有显著排队积压。')
para('一次只发一条，以样本平均周期估算约 1.35 条 / 分钟。队列容量只限制积压，不提高合成速度。该数字是规划估计，尚未经持续高流量压力测试。')
heading('语音为何生成得慢','完整 WAV / GPU 自回归 / CPU codec')
figure('tts-generation',230)
grid(['案例','音频/s','GPU生成','CPU codec','服务wall','RTF'],[[r['case'],f(r['audio_seconds']),f(r['moss_generation_s']),f(r['moss_codec_s']),f(r['moss_wall_s']),f(r['moss_rtf'])] for r in R],[60,90,90,90,90,90])
para('总音频 73.04 秒，服务 wall 142.547 秒；加权 RTF 1.9516。平均生成 16.019 秒、codec 4.328 秒；再加约 0.844 秒适配等准备，完整 TTS 为 21.208 秒。')
para('70 字分段用于控制 KV-cache，并不提供流式播放：每段都完成后才拼接返回。R03、R06 是两段。MOSS 日志 UUID 与 DSH ID 不同，本报告按先后顺序关联，并校验全部 32 组字数与音频时长一致。','caption')
heading('接收与播放是否稳定','官方嵌入源的 317 次采样')
figure('receiver-stability',250)
grid(['指标','五段窗口','延长观察，包含下播预览'],[['Canvas FPS','中位 25.285，范围 24.466 - 25.390','末值约 25.34'],['欠载 / 缺包 / 解码错 / 跳帧','全部 0','全部 0'],['最大媒体到达间隔','91.8 ms','551.5 ms'],['缓冲','均值 4.011 s','末值 3.629 s'],['观察范围','163.819 s，5 条用例','媒体时钟累计 114.40 min']],[130,190,190])
para(f'同一接收器仅 1 次上游 WebSocket，0 上游错误。累计网关媒体约 2.797 GB，按媒体时钟粗算 {band:.3f} Mbps；不是公开推流码率，未含全部线缆开销。')
para('Canvas 更新 FPS 不能代替显示器实际呈现帧率、口型模型吞吐或观众画质。预览持续稳定也不能证明房间仍在公开直播。')
heading('显存、内存与整卡功耗','下播后采样，模型与预览仍常驻')
figure('resource-capacity',190)
grid(['指标','A4090','B3080'],[['整卡显存平均','13,302 MiB / 约 12.99 GiB','1,252.43 MiB / 约 1.22 GiB'],['整机 RAM 平均','21.25 / 63.90 GiB','11.66 / 63.89 GiB'],['整机 CPU 均 / 中 / 峰','14.27 / 7.8 / 100 %','8.21 / 8.1 / 9.1 %'],['GPU 利用率均 / 峰','0.87 / 1 %','4.07 / 5 %'],['整卡功耗平均','52.97 W','106.96 W'],['采样本地开始','06:43:17','06:42:23']],[150,180,180])
para('各 60 秒，30 份 GPU / RAM，29 份有效区间 CPU。A CPU 的 100% 离群点原值保留，原因未归因；两机窗口错开约 54 秒，不能做严格同步因果对比。')
para('MOSS PyTorch allocated 单次峰值约 6,382 - 6,397 MiB；是 TTS 分配器峰值，不是整卡峰值。此前另一段 360 秒 A 验证记录到 GPU 利用率峰值 68%，显存 13,300 MiB，不能冒充本场全程峰值。')
para('旧 B 模型退休前后 9,613 -> 1,223 MiB，释放 8,390 MiB。模型退出显著释放了 B 显存，但当前 4090 的完整语音等待仍受生成路径限制。')
heading('常驻进程与采样异常','RSS 与整机使用量分开理解')
figure('process-memory',180);figure('post-offair-sampling',210)
para('A MOSS RSS 约 8.61 GiB，GPU worker 3.46 GiB，人物辅助 0.97 GiB，DSH 0.118 GiB；A ComfyUI 另占约 2.80 GiB。B 直播姬进程组约 0.324 GiB、接收器约 0.014 GiB，B ComfyUI 约 3.05 GiB。')
para('RSS 可能包含共享页，不能相加当作独占 RAM。进程 CPU 从单核百分比除以逻辑 CPU 数转换；这里只识别采样开始时的相关进程。ComfyUI 本轮未被调用。')
heading('实时调度的所有节拍','队列 / 超时 / 音视频 / 播放确认')
grid(['机制','当前值','行为'],scheduling[:13],[115,130,265])
para('低流量场景的 dispatch 平均 0.485 秒。8 秒与 15 秒是防连发门槛，并非每个阶段额外叠加的固定等待。平台 TTL 45 秒与 DSH TTL 180 秒属于不同层级；pending 50 不能保证 50 条都被播报。')
heading('下播维护与云端调用预算','已实现的调度与当前实际结果')
grid(['机制','当前值','行为'],scheduling[13:],[105,150,255])
para('本场 A 06:30:03.942 结束，06:32:03.942 满足静默窗口。截止 A 06:51:19，当前任务 DEFERRED / budget，not_before 为本地 07:34:19.928。今日维护已计 20 / 20；一小时后只是重查，日额度未重置仍会继续延迟。')
para('当前保留 10 个维护任务：3 完成、6 失败、1 延后。6 个旧 extraction_failed 达到 5 次尝试；当前 memory_entries=0、summary_versions=6。上下文可对话不等于长期事实压缩已成功。本场没有新增可验证的持久事实。')
grid(['日期 / 范围','调用','输入token已知','输出token已知','未知usage'],[[r['date']+' / '+r['scope'],r['counted_calls'],r['input_tokens_known'],r['output_tokens_known'],r['usage_unknown_calls']] for r in D['maintenance']['daily_usage']],[190,50,100,100,70])
heading('前台上下文与平台中断','云端用量与运行状态不混为一项')
grid(['案例','LLM / s','输入token','输出token','回复字数'],[[r['case'],f(r['llm_or_echo_s']),r['input_tokens'],r['output_tokens'],r['reply_characters']] for r in R],[70,100,120,120,100])
para('7 条真实弹幕共 41,745 input / 292 output tokens，均已结算。6000 是上下文估计预算，提供方实际总输入包含提示模板等，单次达到 7,821；缓存细分与价格未采集，不推算费用。')
grid(['来源时间 / 本地','事件','含义'],[['B 05:10:19','开播 API 成功','随后媒体连接成功'],['B 05:41:23.308','平台 PREPARING','客户端媒体停止；界面与公开房间状态曾不一致'],['平台 06:15:13','用户手动重新开播','公开接口恢复 LIVE'],['A 06:23:11','R07 入账','已完整回复'],['A 06:30:03.942','内部 ENDED','按用户下播收尾，采集停止，模型常驻']],[130,130,250])
para('内部会话 83 分 30 秒，包含公开中断，不能称为连续公开直播时长。没有采集到平台终止的具体原因。应增加公共状态对账，不自动重启平台主动终止的直播。')
heading('下一步怎么优化','数据支持的顺序；本次未修改运行策略')
grid(['级别 / 项目','依据','下一步验收'],[[p[0]+' / '+p[1],p[2],p[3]+'。'+p[4]] for p in priorities],[125,155,230])
heading('范围与未测项','保留异常，避免过度结论')
for i,item in enumerate(limits,1):para(str(i)+'. '+item,'caption')
for index,subset in enumerate([D['requests'][:16],D['requests'][16:]],1):
 heading('全部案例，含历史异常 ('+str(index)+'/2)','H = 较早调试，C = 当前官方验收，R = 实播')
 grid(['案例','本地入账','模式','字数','首回执/s','完成/s','RTF','状态'],[[r['case'],r['created_at_local'],r['mode'],r['reply_characters'],f(r['collector_to_first_s']),f(r['collector_to_complete_s']),f(r['moss_rtf']),r['status']] for r in subset],[35,113,38,30,65,65,48,116])
 para('首回执与完整完成均采用 A 同机时钟；UNKNOWN 的完成时间留空。历史异常未删除或当作零值计入。','caption')
heading('数据来源与复现','只读导出 / 完整性校验 / 无新增直播录制')
para('数据来自 A SQLite 状态账本与平台账本、MOSS 合成日志、B 官方嵌入源指标，以及原生 Windows psutil / nvidia-smi 下播后采样。全部导出是只读事务，不复制正在写入的数据库文件。')
para('运行时代码 '+D['runtime_commit'],'caption');para('报告前文档版本 '+D['documentation_base_commit'],'caption')
para('MOSS 分析关联并非原生 trace ID；按日志顺序一一对应，并验证全部 32 条字数与有效音频时长。当前没有微批口型推理耗时曲线，不能编造每帧计算时延。')
for name,digest in D['provenance']['hashes'].items():para(name+'\n'+digest,'caption')
para('重建：在仓库根执行 python -X utf8 devtools/build-performance-report.py。仅消费 data/evidence.json，不访问模型或直播平台。交互网页、CSV、图表 PNG / SVG 与 Markdown 同目录归档。')
para('本报告完成后，验证浏览器已关闭；仅保留交付报告页。没有新增直播录制，没有修改模型精度、调度政策或公共开播状态。')
def footer(c,doc):
 c.saveState();c.setStrokeColor(colors.HexColor('#D6DFEB'));c.line(42,35,553,35);c.setFont('YaHei',7);c.setFillColor(colors.HexColor(P['muted']));c.drawString(42,23,'女A / 林知夏   |   A4090 + B3080   |   2026-10-27 冻结数据');c.drawRightString(553,23,str(doc.page));c.restoreState()
pdf=OUT/'report.pdf';doc=SimpleDocTemplate(str(pdf),pagesize=(595.28,841.89),rightMargin=42,leftMargin=42,topMargin=40,bottomMargin=48,title=D['title'],author='Ai-Talk-Streamer measurement report',pageCompression=1)
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(json.dumps({'report_directory':str(OUT),'public_requests':len(R),'all_requests':len(D['requests']),'artifacts':['report.html','report.pdf','report.md','data/requests.csv','data/resource-samples.csv','data/evidence.json'],'charts':6},ensure_ascii=False))
