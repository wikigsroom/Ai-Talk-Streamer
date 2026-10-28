"""Archive the verified, reviewed bundle without normalizing raw evidence bytes."""
import json,hashlib,re,shutil
from pathlib import Path,PurePosixPath
P=Path(__file__).resolve().parent
repo=P.parent.parent/'Ai-Talk-Streamer'
if not (repo/'.git').exists():repo=P.parent.parent
if not (repo/'.git').exists():raise RuntimeError('Run from this project operations or benchmark source directory')
source=repo.parent/'outputs/lipsync-k01-k05-60s-20261028'
dest=repo/'docs/analysis/lipsync-k01-k05-20261028'
manifest=json.loads((source/'delivery-manifest.json').read_text(encoding='utf-8'))
if not manifest.get('complete'):raise RuntimeError('Do not archive an incomplete five-model result as complete')
verification=json.loads((source/'verification-summary.json').read_text(encoding='utf-8'))
if {r['id'] for r in verification if r.get('verified')}!={'K01','K02','K03','K04','K05'}:raise RuntimeError('All five video/audio/source verification records are required')

def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(4*1024*1024),b''):digest.update(block)
    return digest.hexdigest()

paths=[]
for item in manifest['files']:
    rel=PurePosixPath(item['path']);original=source.joinpath(*rel.parts);target=dest.joinpath(*rel.parts)
    if rel.is_absolute() or '..' in rel.parts or not target.resolve().is_relative_to(dest.resolve()):raise ValueError('Unsafe artifact path')
    if original.stat().st_size!=item['bytes'] or sha256(original)!=item['sha256']:raise RuntimeError('Input differs from received manifest: '+item['path'])
    if original.suffix in {'.json','.md','.csv','.log','.html','.txt','.py'}:
        text=original.read_text(encoding='utf-8-sig',errors='replace')
        if re.search(r'sk-[A-Za-z0-9_-]{20,}|X-Amz-Signature=|[?&](?:token|access_token|api_key)=[^&\s"<>]+',text,re.I):raise RuntimeError('Review possible private or signed token before publication: '+item['path'])
    paths.append((original,target,item))
dest.mkdir(parents=True,exist_ok=True)
# Scientific hashes refer to actual Windows bytes, including CRLF and CSV BOM.
# -text disables Git EOL conversion without disabling text review/diffs.
(dest/'.gitattributes').write_bytes(b'# Preserve verbatim hashed evidence bytes, including Windows CRLF.\n* -text -whitespace\n')
for original,target,item in paths:
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists() or target.stat().st_size!=item['bytes'] or sha256(target)!=item['sha256']:shutil.copy2(original,target)
    if sha256(target)!=item['sha256']:raise RuntimeError('Archive copy failed verification: '+item['path'])
shutil.copy2(source/'delivery-manifest.json',dest/'delivery-manifest.json')
for name in ['page-review.json','page-review-remote.json','page-review-desktop.png','page-review-desktop-remote.png','page-review-mobile.png','page-review-mobile-remote.png','full-report-first-page.png','full-report-first-page-remote.png','delivery-receipt.json']:
    if (source/name).exists():shutil.copy2(source/name,dest/name)
for name in ['browser-before-startup-fix','browser-after-startup-fix']:
 if (source/'diagnostics'/name).exists():shutil.copytree(source/'diagnostics'/name,dest/'diagnostics'/name,dirs_exist_ok=True)
if (source/'diagnostics/visual-review/final-review-above-fold.png').exists():shutil.copy2(source/'diagnostics/visual-review/final-review-above-fold.png',dest/'review-page.png')
(dest/'ARCHIVE.md').write_text('''# 测评归档 / Verified review archive

[浏览器报告](report.html) · [原始Markdown](report.md) · [同步对比页面](index.html) · [文件与SHA256清单](delivery-manifest.json) · [原生实验代码](../../../benchmarks/k01-k05-60s-20261028/README.md)

五组均为60秒、720×1280、25FPS，使用同一O07音频与同一动作序列。K03是合成教师初训与有记录的续训实验；K05为保留网络强度的原生执行适配。共享负载的离线耗时不能代表独占GPU或直播端到端延迟。历史测评与正式直播配置保持原样。

在本目录执行`python viewer_server.py --port 8039`，再访问`http://127.0.0.1:8039/`。原始MP4、WAV、JSON、来源抽样和图表按原结构归档；Git属性保留原始字节，避免换行转换破坏测评SHA256。

The portable archive preserves the measured evidence bytes. Run the standard-library viewer from this directory; Python3.10+ is enough and no GPU is needed for review. Large model weights, native environments and the8,000-frame training cache remain onA4090 and are referenced separately. No PDF, compressed archive, MCP records, account credentials or private memory database is included.

## 观看与验收 / Media and acceptance

[本机同步页面](http://127.0.0.1:8037/) · [A4090同步页面](http://192.168.196.209:8035/) · [五组60秒总览](K01-K05-comparison-60s.mp4) · [原始60秒WAV](audio/common-60s.wav)

![实际对比页面 / Review page](review-page.png)

![8—14秒嘴部预览 / Six-second silent preview](mouth-comparison-08s-14s.gif)

[本机17项检查](page-review.json) · [A4090入口17项检查](page-review-remote.json) · [初次起播失败](page-review-before-fix.json) · [修复前事件](startup-before-fix.json) · [修复后事件](startup-after-fix.json)

两个入口均要求音轨和视频实际向前播放，不能以seek后时间不为0冒充成功。首次起播竞态已修复并保留失败证据。All task-owned test browsers are closed; original model measurements remain unchanged.
''',encoding='utf-8')
print(json.dumps({'archive':str(dest),'manifest_files':manifest['file_count'],'manifest_bytes':manifest['bytes'],'all_payload_hashes_verified':True,'raw_bytes_preserved_in_git':True},ensure_ascii=False),flush=True)
