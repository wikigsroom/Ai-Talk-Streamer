"""Render this controlled report's Markdown as portable, dependency-free HTML."""
import html,re

def inline(text):
    pattern=re.compile(r'!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*')
    parts=[];position=0
    for match in pattern.finditer(text):
        parts.append(html.escape(text[position:match.start()]))
        if match.group(1) is not None:
            parts.append('<img loading="lazy" alt="'+html.escape(match.group(1),quote=True)+'" src="'+html.escape(match.group(2),quote=True)+'">')
        elif match.group(3) is not None:
            parts.append('<a href="'+html.escape(match.group(4),quote=True)+'">'+html.escape(match.group(3))+'</a>')
        elif match.group(5) is not None:parts.append('<code>'+html.escape(match.group(5))+'</code>')
        else:parts.append('<strong>'+html.escape(match.group(6))+'</strong>')
        position=match.end()
    parts.append(html.escape(text[position:]));return ''.join(parts)

def render_report(markdown):
    lines=markdown.splitlines();body=[];toc=[];index=0;section=0
    while index<len(lines):
        text=lines[index].strip()
        if not text:index+=1;continue
        heading=re.match(r'^(#{1,4})\s+(.+)$',text)
        if heading:
            level=len(heading.group(1));section+=1;anchor=f'section-{section}'
            body.append(f'<h{level} id="{anchor}">'+inline(heading.group(2))+f'</h{level}>')
            if level==2:toc.append((anchor,heading.group(2)))
            index+=1;continue
        if text.startswith('```'):
            code=[];index+=1
            while index<len(lines) and not lines[index].strip().startswith('```'):code.append(lines[index]);index+=1
            body.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>');index+=1;continue
        if text.startswith('|') and index+1<len(lines) and re.fullmatch(r'[| :\-]+',lines[index+1].strip()):
            headers=[c.strip() for c in text.strip('|').split('|')];rows=[];index+=2
            while index<len(lines) and lines[index].strip().startswith('|'):
                rows.append([c.strip() for c in lines[index].strip().strip('|').split('|')]);index+=1
            body.append('<div class="table-wrap"><table><thead><tr>'+''.join('<th scope="col">'+inline(c)+'</th>' for c in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>');continue
        list_match=re.match(r'^(?:([-*])\s+|(\d+)\.\s+)(.*)$',text)
        if list_match:
            ordered=list_match.group(2) is not None;tag='ol' if ordered else 'ul';values=[]
            while index<len(lines):
                match=re.match(r'^(?:([-*])\s+|(\d+)\.\s+)(.*)$',lines[index].strip())
                if not match or (match.group(2) is not None)!=ordered:break
                values.append('<li>'+inline(match.group(3))+'</li>');index+=1
            body.append('<'+tag+'>'+''.join(values)+'</'+tag+'>');continue
        paragraph=[text];index+=1
        while index<len(lines) and lines[index].strip() and not re.match(r'^(?:#|\||```|[-*]\s|\d+\.\s)',lines[index].strip()):paragraph.append(lines[index].strip());index+=1
        body.append('<p>'+inline(' '.join(paragraph))+'</p>')
    nav=''.join('<a href="#'+anchor+'">'+html.escape(label)+'</a>' for anchor,label in toc)
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>女A K01—K05 · 完整测评报告</title>
<style>:root{color-scheme:light;--ink:#172f49;--muted:#576e83;--blue:#2459a5;--line:#cad6e3}*{box-sizing:border-box}body{margin:0;background:#edf2f7;color:var(--ink);font:15px/1.85 "Microsoft YaHei UI","PingFang SC",sans-serif}header,main,footer{max-width:1160px;margin:auto;padding:22px 30px}header{display:flex;gap:24px;flex-wrap:wrap;border-bottom:1px solid var(--line)}header span{color:var(--muted);margin-left:auto}a{color:var(--blue)}a:focus-visible{outline:3px solid #4896ef;outline-offset:3px}h1{font-size:clamp(27px,4vw,39px);line-height:1.4;letter-spacing:-.6px;margin:22px 0}h2{font-size:24px;margin:40px 0 16px;padding-top:12px;border-top:1px solid var(--line)}h3{font-size:19px}h1,h2,h3,h4{scroll-margin-top:20px}p{margin:15px 0}nav{display:flex;gap:8px 20px;flex-wrap:wrap;background:#e5edf6;padding:18px;margin:20px 0}nav a{font-size:13px}.table-wrap{overflow:auto;border:1px solid var(--line);margin:18px 0}table{width:100%;border-collapse:collapse;background:#fff;font-size:13px}th,td{text-align:left;vertical-align:top;padding:11px 12px;border-bottom:1px solid var(--line);min-width:90px}th{background:#e5edf6;font-size:12px}td:first-child{font-weight:600}code{font:13px Consolas,monospace;overflow-wrap:anywhere}pre{background:#fff;padding:18px;overflow:auto}img{display:block;max-width:100%;height:auto;margin:20px auto}li{margin:8px 0}footer{border-top:1px solid var(--line);color:var(--muted);font-size:12px}@media(max-width:650px){header,main,footer{padding:18px 14px}header span{margin-left:0}nav{padding:12px}th,td{padding:9px}h2{font-size:22px}}</style>
<header><a href="index.html">同步观看与选型</a><a href="report.md">原始Markdown</a><a href="results.csv">原始CSV</a><a href="audio/common-60s.wav">共用WAV</a><span>原生Windows · 4090 · 同源60秒</span></header><main>'''+(body[0] if body else '')+'<nav aria-label="报告目录">'+nav+'</nav>'+''.join(body[1:])+'''</main><footer>生成自同目录report.md。原始MP4、WAV、JSON、资源记录和复现协议单独保留；本页不调用外部脚本或云端接口。</footer></html>'''
