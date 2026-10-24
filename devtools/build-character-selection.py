"""Package the five reviewed nighttime portraits and an offline comparison page."""
from pathlib import Path
import argparse
import base64
import csv
import hashlib
import html
import json
import textwrap
import zipfile
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'output/imagegen/character-selection-angles-v3-20261024'
REVISION='night-camera-angles-v3'
BUNDLE='night-character-selection-v3.zip'
WEB=ROOT/'web/selection.html'
DELIVERY=ROOT/'outputs/character-selection'
FONT=Path('C:/Windows/Fonts/msyh.ttc')


def sha256(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def font(size):return ImageFont.truetype(str(FONT),size)


def overview(items):
    width,pad,gap,tile=1900,42,18,349
    canvas=Image.new('RGB',(width,1015),'#ece8e2')
    draw=ImageDraw.Draw(canvas)
    draw.text((pad,25),'夜间直播角色选型 · 机位修订 V3' if REVISION.endswith('v3') else '夜间直播角色选型',font=font(40),fill='#202936')
    draw.text((pad,84),'01 聊天近景 · 02 正面桌播 · 03 暮蝶 Cos 展示 · 全部为夜间封闭室内' if REVISION.endswith('v3') else '5 个不同人物 · 5 种机位与布景 · 全部为封闭室内、人工灯光',font=font(22),fill='#6d6a66')
    for i,item in enumerate(items):
        x=pad+i*(tile+gap)
        image=Image.open(ROOT/item['portrait']).convert('RGB').resize((tile,620),Image.Resampling.LANCZOS)
        canvas.paste(image,(x,140))
        draw.text((x,781),item['number']+'  '+item['category'],font=font(23),fill='#202936')
        draw.text((x,821),item['name']+'  /  '+str(item['age'])+' 岁',font=font(19),fill='#595a58')
        draw.text((x,857),item['tagline'],font=font(17),fill='#7b6350')
        for line_no,line in enumerate(textwrap.wrap(item['viewpoint'],width=17)):
            draw.text((x,897+line_no*26),line,font=font(16),fill='#686d72')
    draw.text((pad,975),'人物与场景概念图 / 选型阶段 · 原始大图、提示词与校验清单另附',font=font(17),fill='#73706c')
    target=FOLDER/'night-selection-overview.jpg';canvas.save(target,quality=94,subsampling=0)
    return target


def camera_trio(items):
    canvas=Image.new('RGB',(1740,1320),'#ece8e2');draw=ImageDraw.Draw(canvas)
    draw.text((36,24),'01 / 02 / 03 · 直播机位重新构图',font=font(38),fill='#202936')
    draw.text((36,84),'夜晚 · 封闭房间 · 真人风格 · 第 03 款指定「暮蝶 / Clove」',font=font(23),fill='#6d6a66')
    for index,item in enumerate(items[:3]):
        x=36+index*568
        image=Image.open(ROOT/item['portrait']).convert('RGB').resize((532,946),Image.Resampling.LANCZOS)
        canvas.paste(image,(x,136))
        draw.text((x,1102),item['number']+'  '+item['category']+' · '+item['name'],font=font(25),fill='#202936')
        draw.text((x,1148),item['tagline'],font=font(21),fill='#7b6350')
        for line_no,line in enumerate(textwrap.wrap(item['viewpoint'],width=22)):
            draw.text((x,1190+line_no*30),line,font=font(19),fill='#686d72')
    target=FOLDER/'camera-trio-overview.jpg';canvas.save(target,quality=94,subsampling=0)
    return target


def page(items):
    cards=[]
    for item in items:
        data='data:image/jpeg;base64,'+base64.b64encode((ROOT/item['preview']).read_bytes()).decode()
        record={key:item[key] for key in ('id','number','name','category','viewpoint')}
        record.update(revision=REVISION)
        if item.get('cosplay_character'):record['cosplay_character']=item['cosplay_character']
        desc=html.escape(json.dumps(record,ensure_ascii=False),quote=True)
        cards.append(f'''<article class="card" id="{item['id']}" data-id="{item['id']}"><button class="image-button" data-open="{item['id']}" aria-label="放大{item['number']} {item['name']}"><img src="{data}" alt="{item['category']} {item['name']}，{item['tagline']}" width="720" height="1280"><span class="image-hint">点击看大图 ↗</span></button><div class="card-body"><p class="card-kicker">{item['number']} / {item['category']}</p><h2>{item['name']}<small>{item['age']} 岁</small></h2><p class="scene">{item['tagline']}</p><p class="description">{item['background']}</p><dl><dt>直播视角</dt><dd>{item['viewpoint']}</dd><dt>人物气质</dt><dd>{item['character_note']}</dd></dl><div class="card-actions"><button class="pick" data-pick="{item['id']}" data-record="{desc}" aria-pressed="false">加入候选</button><a href="{data}" download="{item['id']}-night-preview.jpg">保存预览 ↓</a></div></div></article>''')
    document='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>夜间直播 · 5 款人物场景选型</title><style>
:root{--bg:#eeeae4;--ink:#202936;--muted:#77716a;--line:#d8d0c5;--accent:#945b3b}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--bg);font:15px/1.7 "Microsoft YaHei","PingFang SC",system-ui,sans-serif}button,a{font:inherit}button{cursor:pointer}a{color:inherit}header{display:flex;align-items:center;justify-content:space-between;padding:22px 4%;border-bottom:1px solid var(--line);gap:16px}.brand{font-size:17px;font-weight:700;letter-spacing:2px;text-decoration:none}.header-note{font-size:12px;letter-spacing:2px;color:var(--muted)}main{padding:48px 4% 140px;max-width:2050px;margin:auto}.intro{display:flex;gap:28px;align-items:end;justify-content:space-between;margin-bottom:32px}.eyebrow{font-size:12px;letter-spacing:3px;color:var(--accent);margin:0 0 14px}h1{font-size:clamp(30px,3vw,48px);font-weight:500;letter-spacing:-1px;margin:0 0 14px;line-height:1.3}.subtitle{margin:0;color:var(--muted)}.brief{font-size:13px;color:var(--muted);max-width:400px}.brief span{display:inline-block;margin-right:12px;border:1px solid var(--line);border-radius:30px;padding:3px 12px}.grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:18px;align-items:start}.card{background:#fffcf7;border:1px solid var(--line);border-radius:15px;overflow:hidden;transition:border-color .15s,box-shadow .15s}.card.selected{border-color:var(--accent);box-shadow:0 0 0 2px #945b3b20}.image-button{display:block;position:relative;width:100%;padding:0;border:0;background:#1c2028}.image-button img{display:block;width:100%;height:auto;aspect-ratio:9/16;object-fit:cover}.image-hint{position:absolute;bottom:12px;right:12px;color:white;background:#10141b88;border-radius:20px;padding:3px 10px;font-size:11px;backdrop-filter:blur(7px)}.card-body{padding:20px 18px}.card-kicker{margin:0 0 6px;font-size:11px;letter-spacing:1px;color:var(--accent)}h2{font-size:24px;font-weight:500;margin:0 0 8px}h2 small{font-size:12px;color:var(--muted);margin-left:12px}.scene{font-size:13px;margin:0 0 10px}.description{font-size:12px;color:var(--muted);margin:0;min-height:62px}dl{font-size:11px;border-top:1px solid var(--line);margin:14px 0 0;padding-top:12px}dt{color:var(--muted);margin-top:8px}dd{margin:2px 0 0;min-height:36px}.card-actions{display:flex;flex-wrap:wrap;gap:12px;align-items:center;border-top:1px solid var(--line);margin-top:16px;padding-top:16px}.pick,.export{background:var(--ink);color:white;border:0;padding:8px 13px;border-radius:7px;font-size:12px}.pick[aria-pressed="true"]{background:var(--accent)}.card-actions a{font-size:11px;text-decoration:none}.footnote{font-size:12px;color:var(--muted);margin-top:26px}.selection-bar{position:fixed;bottom:0;left:0;right:0;background:#fffcf7f2;backdrop-filter:blur(15px);border-top:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:20px;padding:16px 4%;z-index:5}.selection-bar b{font-size:13px;font-weight:500}.selection-bar small{display:block;color:var(--muted);font-size:11px}.actions{display:flex;align-items:center;gap:16px}.reset{background:none;border:0;color:var(--muted);font-size:12px}dialog{max-width:96vw;max-height:96vh;padding:0;background:#161a20;color:white;border:0;border-radius:12px}dialog::backdrop{background:#060a10dd}dialog img{display:block;max-height:86vh;width:auto;max-width:95vw;height:auto}dialog .caption{display:flex;justify-content:space-between;gap:20px;padding:12px 16px;font-size:12px}dialog button{background:none;border:0;color:white}button:focus-visible,a:focus-visible{outline:3px solid #ac7955;outline-offset:4px}@media(max-width:1380px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}.description{min-height:42px}}@media(max-width:850px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.intro{display:block}.brief{margin-top:20px}.header-note{display:none}main{padding-top:30px}}@media(max-width:520px){.grid{grid-template-columns:1fr}.card-body{padding:22px}.description,dd{min-height:0}.intro h1{font-size:32px}.selection-bar{gap:10px}.actions{gap:8px}.selection-bar b{font-size:12px}.export{padding:9px;font-size:11px}}@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body><header><a class="brand" href="/">映现场 · CASTING</a><a class="header-note" id="bundleDownload" href="night-character-selection-v2.zip">下载原图与提示词 ↓</a></header><main><section class="intro"><div><p class="eyebrow">人物 × 直播视角 × 配套场景</p><h1>同一个夜晚，五种直播气质。</h1><p class="subtitle">从人物、视角和房间氛围中，选出你想继续制作的一款。</p></div><div class="brief"><p><span>全部夜晚</span><span>封闭房间</span><span>人工灯光</span></p><p>每张图都可放大查看。可加入多款候选，并导出选型记录；选择会保存在当前浏览器。</p></div></section><section class="grid">__CARDS__</section><p class="footnote">本轮为人物与场景静态概念图选型。五位均为虚构成年角色，尚未制作对应动作视频与口型模型。现有「女A · 林知夏」直播配置继续使用。</p></main><aside class="selection-bar"><div><b id="selectionText">还没有加入候选</b><small>点击卡片中的“加入候选”即可开始比较。</small></div><div class="actions"><button class="reset" id="reset">清空</button><button class="export" id="export">导出选型记录 ↓</button></div></aside><dialog id="lightbox"><img id="largeImage" alt="放大的选型图"><div class="caption"><span id="largeCaption"></span><button id="closeDialog">关闭 ✕</button></div></dialog><script>
'use strict';if(location.protocol==='file:'){document.getElementById('bundleDownload').hidden=true;document.querySelector('.brand').href='#'}const key='avatar-night-selection-v2';let chosen=[];try{chosen=JSON.parse(localStorage.getItem(key)||'[]')}catch{}const buttons=Array.from(document.querySelectorAll('[data-pick]'));chosen=chosen.filter(id=>buttons.some(button=>button.dataset.pick===id));function render(){for(const button of buttons){const on=chosen.includes(button.dataset.pick);button.setAttribute('aria-pressed',String(on));button.textContent=on?'已加入 ✓':'加入候选';button.closest('.card').classList.toggle('selected',on)}const labels=chosen.map(id=>JSON.parse(buttons.find(button=>button.dataset.pick===id).dataset.record)).map(item=>item.number+' '+item.name);document.getElementById('selectionText').textContent=labels.length?'已选：'+labels.join(' / '):'还没有加入候选';try{localStorage.setItem(key,JSON.stringify(chosen))}catch{}}for(const button of buttons)button.onclick=()=>{const id=button.dataset.pick;chosen=chosen.includes(id)?chosen.filter(value=>value!==id):[...chosen,id];render()};const dialog=document.getElementById('lightbox');for(const button of document.querySelectorAll('[data-open]'))button.onclick=()=>{const image=button.querySelector('img');document.getElementById('largeImage').src=image.src;document.getElementById('largeCaption').textContent=image.alt;dialog.showModal()};document.getElementById('closeDialog').onclick=()=>dialog.close();dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close()});document.getElementById('reset').onclick=()=>{chosen=[];render()};document.getElementById('export').onclick=()=>{const data={brief:'nighttime / enclosed room / artificial lighting',selected:chosen.map(id=>JSON.parse(buttons.find(button=>button.dataset.pick===id).dataset.record))};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='夜间直播角色选型.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};render();
</script></body></html>'''.replace('__CARDS__',''.join(cards))
    if REVISION.endswith('v3'):
        document=document.replace('night-character-selection-v2.zip',BUNDLE).replace('avatar-night-selection-v2','avatar-night-selection-v3')
        document=document.replace('夜间直播 · 5 款人物场景选型','夜间直播 · 01/02/03 新机位与暮蝶 Cos')
        document=document.replace('同一个夜晚，五种直播气质。','换一个机位，重新认识她。')
        document=document.replace('从人物、视角和房间氛围中，选出你想继续制作的一款。','01 近景聊天 · 02 正面桌播 · 03 暮蝶 Cos 展示；04、05 保留上一版。')
        document=document.replace('<p class="footnote">','<p class="footnote">本次机位参考：<a href="https://www.bilibili.com/video/BV1AQ4y197JR/" target="_blank" rel="noopener">B站桌面直播回放</a> · <a href="https://www.bilibili.com/video/BV1Pb4y1D7Co/" target="_blank" rel="noopener">B站正面真人直播回放</a> · <a href="https://m.douyin.com/shipin/7616936639201331238" target="_blank" rel="noopener">抖音竖屏聊天截图出处</a> · <a href="https://playvalorant.com/en-us/agents/clove/" target="_blank" rel="noopener">暮蝶官方角色设定</a>。角度数值是本项目的构图目标，未对主播原片进行机位测量。</p><p class="footnote">')
    WEB.write_text(document,encoding='utf-8',newline='\n')


def main():
    global FOLDER,REVISION,BUNDLE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision',choices=('v2','v3'),default='v3')
    args=parser.parse_args()
    if args.revision=='v2':
        FOLDER=ROOT/'output/imagegen/character-selection-night-20261024'
        REVISION='night-closed-room-v2';BUNDLE='night-character-selection-v2.zip'
    generation_path=FOLDER/'generation-manifest.json'
    if generation_path.is_file():
        generation=json.loads(generation_path.read_text(encoding='utf-8'))
    else:
        catalog=json.loads((FOLDER/'catalog.json').read_text(encoding='utf-8'))
        generation={'all_generated':catalog['count']==5,'items':catalog['items'],'requirements':catalog['requirements']}
    reviews=json.loads((FOLDER/'reviews.json').read_text(encoding='utf-8'))
    if not generation.get('all_generated') or len(generation['items'])!=5:raise ValueError('Five completed images are required')
    notes={
        'c01-natural':'低马尾、自然素颜、棉质白 T，亲近松弛。',
        'c02-student':'短发、浅黄 T 恤，轻松的成年校园气质。',
        'c03-coser':'银紫假发、原创星月服装，真人 Cos 质感。',
        'c04-glamour':'长卷发、酒红针织与炭灰外套，成熟的夜聊氛围。',
        'c05-podcast':'短发、深绿衬衫，知性、沉稳的访谈气质。',
    }
    if REVISION.endswith('v3'):notes['c03-coser']='暮蝶 / Clove：蓝紫短发与银色发夹、粉色外套、紫色工装裤；真人 Coser。'
    items=[]
    for original in generation['items']:
        if not reviews.get(original['id'],{}).get('accepted'):raise ValueError('Image must be reviewed: '+original['id'])
        keep=['id','number','name','age','category','tagline','viewpoint','background','native','prompt','model','quality','time_of_day','enclosed_room']
        item={key:original[key] for key in keep}
        for key in ('camera_type','cosplay_character','retained_from_revision','identity_reference'):
            if key in original:item[key]=original[key]
        native=ROOT/item['native'];image=Image.open(native).convert('RGB')
        portrait=ImageOps.fit(image,(720,1280),method=Image.Resampling.LANCZOS)
        delivery=FOLDER/(item['id']+'-720x1280.png');portrait.save(delivery)
        preview=FOLDER/(item['id']+'-preview.jpg');portrait.save(preview,quality=94,subsampling=0)
        item.update(native_size=list(image.size),native_sha256=sha256(native),portrait=delivery.relative_to(ROOT).as_posix(),
                    portrait_sha256=sha256(delivery),preview=preview.relative_to(ROOT).as_posix(),character_note=notes[item['id']],review=reviews[item['id']])
        items.append(item)
    sheet=overview(items);page(items)
    trio=camera_trio(items) if REVISION.endswith('v3') else None
    manifest={'revision':REVISION,'count':5,'selection_only':True,'generator':'sub2-image-gen','model':'gpt-image-2.5','quality':'high',
              'requirements':generation['requirements'],'overview':sheet.relative_to(ROOT).as_posix(),'page':'web/selection.html','items':items}
    if trio:manifest['camera_trio']=trio.relative_to(ROOT).as_posix()
    (FOLDER/'catalog.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    with (FOLDER/'选型清单.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['编号','暂定名','年龄','类型','场景','机位','原图','原图SHA256'])
        for item in items:writer.writerow([item['number'],item['name'],item['age'],item['category'],item['background'],item['viewpoint'],item['native'],item['native_sha256']])
    README='''# 夜间直播人物与场景选型 / Nighttime casting concepts

本轮五款全部采用封闭室内、夜晚、人工照明。人物为五位不同的虚构成年女性；各自的直播机位、造型与背景不同。

All five concepts show different fictional adult women in enclosed rooms at night. The selected Sub2API gpt-image-2.5 high-quality route generated the images. Four nighttime edits use first-pass identity photographs as references; the evening fashion host is a fresh fully clothed generation after the gateway rejected the earlier edit. The earlier daytime concepts are superseded and omitted from this delivery.

打开 `selection.html` 可离线放大查看、加入候选、导出选型记录。`night-selection-overview.jpg` 是对比总览。每款包含生成原始 PNG、720×1280 竖屏交付版、JPG 预览和实际编辑提示词；`catalog.json` 和 CSV 包含机位、场景、审核说明与 SHA-256。

These are static character-and-scene concepts for selection. Matching body videos, voice designs and lip-sync preparation have not been produced for these five candidates. Current 女A / 林知夏 remains the active live character. Resized files and the contact sheet are derivatives of the five actual model outputs.
'''
    if REVISION.endswith('v3'):
        README=README.replace('Four nighttime edits use first-pass identity photographs as references; the evening fashion host is a fresh fully clothed generation after the gateway rejected the earlier edit. The earlier daytime concepts are superseded and omitted from this delivery.','Candidates 01–03 are newly generated camera recompositions of their V2 adult identity references. Candidate 03 specifically cosplays Clove (暮蝶) from VALORANT, using official Riot artwork as additional costume-only references. Candidates 04 and 05 retain their reviewed V2 image outputs. Platform references and access limitations are recorded in camera-research.json; framing angles are design targets, not measured camera calibration.')
        README+='\nV3：01 手机近景聊天、02 正面桌播半身、03 暮蝶 Cos 正面展示。`camera-trio-overview.jpg` 专门对比这三款。`camera-research.json` 记录公开参考页面、实际检查范围和本次机位取舍。\n'
    (FOLDER/'README.md').write_text(README,encoding='utf-8',newline='\n')
    DELIVERY.mkdir(parents=True,exist_ok=True);archive=DELIVERY/BUNDLE
    selected=[FOLDER/'catalog.json',FOLDER/'reviews.json',FOLDER/'选型清单.csv',FOLDER/'README.md',sheet]
    if trio:selected.extend([trio,FOLDER/'camera-research.json'])
    for item in items:selected.extend(ROOT/item[key] for key in ('native','portrait','preview','prompt'))
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as bundle:
        bundle.write(WEB,'selection.html')
        for path in selected:bundle.write(path,path.name)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip():raise ValueError('Archive CRC verification failed')
        for item in items:
            if hashlib.sha256(bundle.read(Path(item['native']).name)).hexdigest()!=item['native_sha256']:raise ValueError('Native image hash mismatch')
    result={'ok':True,'count':5,'revision':manifest['revision'],'archive':archive.relative_to(ROOT).as_posix(),
            'archive_bytes':archive.stat().st_size,'archive_sha256':sha256(archive),'page':WEB.relative_to(ROOT).as_posix(),
            'page_sha256':sha256(WEB),'page_bytes':WEB.stat().st_size,'overview':manifest['overview']}
    (FOLDER/'release.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
