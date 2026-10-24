"""Build a portable audition page from real renders and independent audio checks."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TEXT='你好，我是林知夏。欢迎来到直播间，今天过得怎么样？别着急，我们慢慢聊。'
PRECISION={'MOSS':'LLM NF4 4-bit / BF16 compute · codec FP32 CPU','FireRed':'LLM BF16 · codec FP32 CUDA','SoulX':'LLM BF16 · Flow FP32'}
LABELS=['沉静知性','低柔陪伴','圆润温和','温柔舒缓','自然邻家','清爽利落','明朗亲和','清亮轻盈','元气轻快','轻甜明亮']


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records',type=Path,help='Optional render-results.json for newly generated clips; otherwise rebuild from the published catalog')
    parser.add_argument('--quality-dir',type=Path,help='Required with --records; otherwise use published audio checks')
    args=parser.parse_args()
    archived={}
    if args.records:
        if not args.quality_dir:parser.error('--quality-dir is required with --records')
        records=read(args.records)['results']
    else:
        existing=read(ROOT/'configs/voices/female-a-v1.json')
        archived={item['id']:item for item in [*existing['benchmarks'],*existing['voices']]}
        records=[{**item,'ok':True} for item in archived.values()]
    profiles=read(ROOT/'assets/voices/female-a-v1/references.json')['profiles']
    refs={item['id']:item for item in profiles}
    assert len(records)==21 and all(item['ok'] for item in records),'Expected twenty-one complete actual renders'
    assert {engine:sum(item['engine']==engine for item in records) for engine in PRECISION}=={'MOSS':10,'FireRed':1,'SoulX':10},'Expected ten MOSS, ten SoulX, one FireRed'
    assert len({item['source_speaker_id'] for item in profiles})==10,'References must be ten different speakers'
    items=[]
    for case in records:
        report=read(args.quality_dir/(case['id']+'.json')) if args.records else {**archived[case['id']],'audio':archived[case['id']]['repository_audio']}
        stats=report['audio_checks']
        assert stats['ok'] and stats['full_decode_passed'] and stats['natural_duration_preserved'],case['id']+' failed audio checks'
        audio=ROOT/report['audio'];assert digest(audio)==stats['sha256'],'Mastered audio hash differs'
        assert digest(ROOT/case['source_audio'])==stats['source_sha256'],'Raw audio hash differs'
        workflow='configs/voices/workflows/'+case['id']+'.api.json'
        item={'id':case['id'],'voice_id':case['voice_id'],'engine':case['engine'],'url':audio.relative_to(ROOT/'web').as_posix(),
              'repository_audio':audio.relative_to(ROOT).as_posix(),'source_audio':case['source_audio'],'sha256':stats['sha256'],
              'seconds':stats['seconds'],'wall_seconds':case['wall_seconds'],'precision':PRECISION[case['engine']],
              'reference':refs[case['voice_id']]['reference'],'reference_text':refs[case['voice_id']]['reference_text'],'workflow':workflow,
              'median_f0_hz_approx':stats['median_f0_hz_approx'],'waveform':stats['waveform'],'audio_checks':stats,'asr':report['asr']}
        if case.get('engine_details'):
            details=json.loads(case['engine_details'][0])
            item['worker_metrics']={key:details[key] for key in ('precision','load_seconds','conditioning_seconds','language_generation_seconds','codec_decode_seconds','peak_allocated_bytes','worker_wall_seconds','comfy_node_seconds','ok') if key in details}
        elif case.get('worker_metrics'):item['worker_metrics']=case['worker_metrics']
        items.append(item)
    ranking=sorted([item for item in items if item['engine']=='SoulX'],key=lambda item:item['median_f0_hz_approx'] or 0)
    labels={item['voice_id']:LABELS[index] for index,item in enumerate(ranking)}
    voices=sorted([item for item in items if item['engine'] in ('SoulX','MOSS')],key=lambda item:(0 if item['engine']=='MOSS' else 1,item['voice_id']))
    for item in voices:
        item['number']=item['voice_id'][1:]
        item['label']=labels[item['voice_id']]
        item['pitch_label']=str(round(item['median_f0_hz_approx']))+' Hz · 估算' if item['median_f0_hz_approx'] else '音区待估算'
    benchmarks=[item for item in items if item['voice_id']=='v01']
    note='样片共 21 段：MOSS 10 款、SoulX 10 款，01 号另有 FireRed 对照。同号使用相同参考音频与逐字稿；选角名称固定，模型输出听感可能不同。基频为自动估算，不能代替听感判断。'
    catalog={'schema_version':2,'revision':'female-a-voices-v2','default_engine':'MOSS','engine_counts':{'MOSS':10,'SoulX':10,'FireRed':1},'character':'female-a','character_name':'林知夏','text':TEXT,'voices':voices,'benchmarks':benchmarks,'benchmark_note':note,
             'live_integration':'Audition and export only. The running avatar retains GPT-SoVITS until a voice is chosen and its adapter is implemented/tested.',
             'quality_scope':'Full decoding, duration preservation, clipping/loudness and offline CPU Whisper transcription; no human MOS or blind listening score.'}
    write(ROOT/'configs/voices/female-a-v1.json',catalog)
    write(ROOT/'docs/evidence/voice-audio-quality.json',{'ok':True,'count':len(items),'voices':10,'distinct_reference_speakers':10,'checks':[{'id':item['id'],'audio_checks':item['audio_checks'],'asr':item['asr']} for item in items],
          'scope':catalog['quality_scope']})
    page=ROOT/'web/voices.html'
    replacement='<script id="voiceCatalog" type="application/json">'+json.dumps(catalog,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+'</script>'
    value=re.sub(r'<script id="voiceCatalog" type="application/json">[\s\S]*?</script>',lambda _:replacement,page.read_text(encoding='utf-8'))
    page.write_text(value,encoding='utf-8',newline='\n')
    inventory=ROOT/'assets/voices/female-a-v1/inventory.csv'
    with inventory.open('w',encoding='utf-8',newline='') as stream:
        fields=['id','voice_id','engine','label','seconds','wall_seconds','median_f0_hz_approx','repository_audio','reference','workflow','sha256']
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for item in items:
            item={**item,'label':labels[item['voice_id']]};writer.writerow(item)
    rows=['# MOSS / SoulX 同号试听对照','',
          '十位独立参考说话人，各用 MOSS 与 SoulX 生成同一句台词。编号固定、参考 WAV 与逐字稿相同；名称为选角方向。 / Ten references, matched content and reference transcripts across both engines.','',
          '| 编号 / ID | 选角方向 / Casting | MOSS WAV | SoulX WAV | MOSS 总耗时 / Wall | SoulX 总耗时 / Wall |',
          '| --- | --- | --- | --- | ---: | ---: |']
    for profile in profiles:
        pair={item['engine']:item for item in voices if item['voice_id']==profile['id']}
        moss,soulx=pair['MOSS'],pair['SoulX']
        rows.append('| '+profile['id'][1:]+' | '+labels[profile['id']]+' | ['+str(moss['seconds'])+'s](../'+moss['repository_audio']+') | ['+str(soulx['seconds'])+'s](../'+soulx['repository_audio']+') | '+str(moss['wall_seconds'])+'s | '+str(soulx['wall_seconds'])+'s |')
    rows+=['','[FireRed 01 对照 / Reference comparison](../web/'+next(item['url'] for item in items if item['engine']=='FireRed')+') · [完整说明 / Guide](VOICES.md)',
           '', 'Total wall time includes loading, polling and transfer; it is not pure inference or first-chunk latency. 总耗时包含加载、轮询及回传，不是纯推理或首包延迟。','']
    (ROOT/'docs/VOICE_COMPARISON.md').write_text('\n'.join(rows),encoding='utf-8')
    archive=ROOT/'outputs/voices/female-a-voice-selection-v2.zip';archive.parent.mkdir(parents=True,exist_ok=True)
    paths=[ROOT/'web'/name for name in ('voices.html','voices.css','voices.js')]
    for folder in ('web/voice-audio/female-a-v1','outputs/voices/female-a-v1','assets/voices/female-a-v1','configs/voices'):
        paths+=sorted(path for path in (ROOT/folder).rglob('*') if path.is_file())
    paths+=[ROOT/'scripts/voice_audio.py',ROOT/'scripts/build-voice-selection.py',ROOT/'scripts/render-voice-selection.py',ROOT/'scripts/verify-voice-speakers.py',ROOT/'docs/evidence/voice-audio-quality.json',ROOT/'LICENSE',ROOT/'THIRD_PARTY_NOTICES.md']
    for name in ('docs/VOICES.md','docs/VOICE_COMPARISON.md','docs/media/voice-selection-desktop.png','docs/media/voice-selection-mobile.png','docs/evidence/voice-selection-browser.json','docs/evidence/voice-selection-browser-offline.json','docs/evidence/voice-speakers.json','docs/evidence/voice-speakers-moss.json'):
        if (ROOT/name).is_file():paths.append(ROOT/name)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(set(paths)):bundle.write(path,path.relative_to(ROOT).as_posix())
        bundle.writestr('START-HERE.txt','Open web/voices.html to audition offline. Read docs/VOICES.md for generation and live integration. No model weights included.\n打开 web/voices.html 离线试听；生成、修改和直播接入方法见 docs/VOICES.md。不含模型权重。\n')
    with zipfile.ZipFile(archive) as bundle:
        failure=bundle.testzip()
        assert failure is None,'Voice bundle ZIP CRC failure: '+str(failure)
    moss_archive=ROOT/'outputs/voices/female-a-moss-10-v2.zip'
    moss_items=[item for item in items if item['engine']=='MOSS']
    moss_paths=[ROOT/name for item in moss_items for name in (item['repository_audio'],item['source_audio'],item['workflow'])]
    moss_paths+=sorted(path for path in (ROOT/'assets/voices/female-a-v1').rglob('*') if path.is_file() and path.name!='inventory.csv')
    moss_paths+=[ROOT/'LICENSE',ROOT/'THIRD_PARTY_NOTICES.md']
    if (ROOT/'docs/evidence/voice-speakers-moss.json').is_file():moss_paths.append(ROOT/'docs/evidence/voice-speakers-moss.json')
    with zipfile.ZipFile(moss_archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(set(moss_paths)):bundle.write(path,path.relative_to(ROOT).as_posix())
        bundle.writestr('MOSS-ONLY-README.txt','女A / 林知夏 · MOSS 十款音色\n\n试听 WAV：web/voice-audio/female-a-v1/*moss*.wav\n原始 FLAC：outputs/voices/female-a-v1/*moss*.flac\n参考声及逐字稿：assets/voices/female-a-v1/\n实际 API 工作流：configs/voices/workflows/*moss*.api.json\n\nTen real MOSS-TTSD-v1.0 renders, ten distinct registered female speakers, identical audition text. Existing RTX 3080 10 GB: NF4 4-bit LLM / BF16 compute, FP32 CPU codec. No pitch/formant shifts. No model weights or live TTS activation included. References are registered CC0-1.0; model terms: https://github.com/OpenMOSS/MOSS-TTSD\n')
        bundle.writestr('moss-inventory.json',json.dumps({'count':10,'engine':'MOSS-TTSD-v1.0','text':TEXT,'items':moss_items},ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(moss_archive) as bundle:assert bundle.testzip() is None,'MOSS-only archive CRC failure'
    release={'revision':'female-a-voices-v2','count':len(items),'voices':10,'engine_counts':catalog['engine_counts'],'archive':archive.relative_to(ROOT).as_posix(),'archive_bytes':archive.stat().st_size,'archive_sha256':digest(archive),
             'moss_archive':moss_archive.relative_to(ROOT).as_posix(),'moss_archive_bytes':moss_archive.stat().st_size,'moss_archive_sha256':digest(moss_archive),
             'page':'web/voices.html','page_sha256':digest(page),'studio_sha256':digest(ROOT/'web/studio.html'),
             'static_files':{path.relative_to(ROOT/'web').as_posix():digest(path) for path in paths if path.is_relative_to(ROOT/'web')}}
    write(ROOT/'outputs/voices/release.json',release)
    print(json.dumps({'ok':True,'voices':10,'generated_clips':len(items),'archive_bytes':release['archive_bytes'],'max_asr_cer':max(item['asr']['normalized_character_error_rate'] for item in items),
          'voices_by_id':[{'number':item['number'],'label':item['label'],'f0':item['median_f0_hz_approx']} for item in voices]},ensure_ascii=False))


if __name__=='__main__':main()
