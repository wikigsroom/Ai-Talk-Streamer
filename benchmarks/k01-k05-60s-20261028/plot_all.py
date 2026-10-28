"""Final figures from five measured records; never fills a pending value with zero."""
import json,os
from pathlib import Path
P=Path(__file__).resolve().parent
os.environ['MPLCONFIGDIR']=str(P.parent.parent/'cache/lipsync-benchmark/matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
O=P.parent.parent/'outputs/lipsync-k01-k05-60s-20261028'
rows=[json.loads((O/k/'result.json').read_text(encoding='utf-8')) for k in ['K01','K02','K03','K04','K05']]
if not all(r.get('ok') for r in rows):raise RuntimeError('Five complete model runs are required for the final figure')
plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False,'figure.facecolor':'#edf2f7','axes.facecolor':'white','axes.spines.top':False,'axes.spines.right':False,'text.color':'#172f49','axes.labelcolor':'#172f49','svg.fonttype':'none'})
fig,axes=plt.subplots(2,1,figsize=(12,9),gridspec_kw={'height_ratios':[2,1]});pos=np.arange(5);left=np.zeros(5)
stages=[('feature_seconds','音频特征','#2459a5'),('inference_seconds','口型网络 / VAE','#7e99c8'),('read_preprocess_seconds','额外输入预处理','#aab7c7'),('affine_transform_video_seconds','仿射对齐','#b69a7b'),('restore_video_seconds','面部还原','#caad91'),('vae_encode_seconds','VAE编码','#a58bbf'),('decode_latents_seconds','扩散解码','#b5a1c8'),('blend_seconds','读取 / 解码 / 融合','#73a8a4'),('encoder_backpressure_seconds','编码阻塞','#c5a36d'),('render_resource_wait_seconds','资源等待','#ddd0c0')]
for key,name,color in stages:
    values=np.array([r.get(key,0) for r in rows]);axes[0].barh(pos,values,left=left,label=name,color=color,height=.5);left+=values
remaining=np.maximum(0,np.array([r['render_wall_seconds'] for r in rows])-left);axes[0].barh(pos,remaining,left=left,label='其他准备 / 编码收尾',height=.5,color='#d6dde6')
for i,r in enumerate(rows):axes[0].text(r['render_wall_seconds']+max(x['render_wall_seconds'] for x in rows)*.015,i,f"{r['render_wall_seconds']:.2f} s  /  RTF {r['render_rtf']:.2f}",va='center',fontsize=9)
axes[0].set_yticks(pos,[r['id'] for r in rows]);axes[0].invert_yaxis();axes[0].set_xlim(0,max(r['render_wall_seconds'] for r in rows)*1.34);axes[0].set_xlabel('同源60秒成片的生成墙钟 / 秒（不含下载、安装、人物训练和冷启动）');axes[0].legend(frameon=False,ncol=3,loc='upper left',bbox_to_anchor=(0,-.16),fontsize=9)
values=[r['cold_load_seconds'] for r in rows];axes[1].barh(pos,values,height=.5,color='#738db4');axes[1].set_yticks(pos,[r['id'] for r in rows]);axes[1].invert_yaxis();axes[1].set_xlim(0,max(values)*1.3)
for i,v in enumerate(values):axes[1].text(v+max(values)*.01,i,f'{v:.2f} s',va='center',fontsize=9)
axes[1].set_xlabel('各入口实际记录的网络 / 头像加载与预热时间 / 秒');fig.suptitle('K01—K05 · 五组60秒录播的实际处理成本',fontsize=16,x=.075,ha='left');fig.text(.075,.015,'各次后台负载不同，禁止将其解释为独占GPU速度排名。K05源转码另列；K03一次性教师准备/训练另列。',fontsize=9,color='#576e83');fig.subplots_adjust(left=.075,right=.98,bottom=.11,top=.91,hspace=.72)
for ext in ['svg','png']:fig.savefig(O/f'all-five-stage-times.{ext}',dpi=160)
plt.close(fig)
colors=['#2459a5','#3b8e83','#9477ac','#987b56','#d36e60'];fig,axes=plt.subplots(4,1,figsize=(12,11),sharex=True)
for row,color in zip(rows,colors):
    samples=json.loads((O/row['id']/'resources.json').read_text(encoding='utf-8'));offset=row['total_with_load_seconds']-row['render_wall_seconds'];samples=[s for s in samples if s['elapsed_seconds']>=offset];x=[s['elapsed_seconds']-offset for s in samples]
    for ax,key,scale in zip(axes,['gpu_util_percent','system_cpu_percent','gpu_total_used_mib','system_ram_used_mib'],[1,1,1024,1024]):ax.plot(x,[s.get(key,np.nan)/scale for s in samples],label=row['id'],color=color,lw=1)
for ax,title in zip(axes,['整卡GPU / %','系统CPU / %','整卡显存 / GiB','系统内存 / GiB']):ax.set_ylabel(title);ax.grid(axis='y',alpha=.16)
axes[0].legend(frameon=False,ncol=5,loc='lower right');axes[0].set_ylim(0,105);axes[1].set_ylim(0,105);axes[-1].set_xlabel('分别进入生成阶段后的时间 / 秒');fig.suptitle('资源曲线 · 包含各次运行时的其他项目',fontsize=16,x=.11,ha='left');fig.text(.11,.015,'原始1秒采样另附。曲线来自不同时间窗口；Python进程显存请看result.json，不能由整卡占用直接相减得到。',fontsize=9,color='#576e83');fig.tight_layout(rect=[.01,.04,.99,.95])
for ext in ['svg','png']:fig.savefig(O/f'all-five-resources.{ext}',dpi=160)
plt.close(fig)
history=json.loads((O/'K03/training-history.json').read_text(encoding='utf-8'));fig,axes=plt.subplots(1,2,figsize=(12,4.6))
for key in ['total','mouth','temp_mouth','mouth_grad']:axes[0].plot([r['epoch'] for r in history],[r['losses'][key] for r in history],label=key,lw=1.5)
axes[0].set_xlabel('实际训练轮次');axes[0].set_ylabel('原训练器记录的损失');axes[0].legend(frameon=False);axes[1].bar([r['epoch'] for r in history],[r['seconds'] for r in history],color='#738db4');axes[1].set_xlabel('实际训练轮次');axes[1].set_ylabel('每轮墙钟 / 秒');fig.suptitle('K03合成教师训练 · 损失下降不等于真人口型质量评分',x=.08,ha='left',fontsize=13);fig.tight_layout(rect=[0,.02,1,.92])
for ext in ['svg','png']:fig.savefig(O/f'K03-training-curves.{ext}',dpi=160)
plt.close(fig);print('Saved five-run and training figures from measured evidence.')
