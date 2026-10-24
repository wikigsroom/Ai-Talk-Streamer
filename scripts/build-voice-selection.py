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
    parser.add_argument('--records',type=Path,required=True,help='Private render-results.json; private paths are not copied')
    parser.add_argument('--quality-dir',type=Path,required=True)
    args=parser.parse_args()
    records=read(args.records)['results'];profiles=read(ROOT/'assets/voices/female-a-v1/references.json')['profiles']
    refs={item['id']:item for item in profiles}
    assert len(records)==12 and all(item['ok'] for item in records),'Expected twelve complete actual renders'
    assert len({item['source_speaker_id'] for item in profiles})==10,'References must be ten different speakers'
    items=[]
    for case in records:
        report=read(args.quality_dir/(case['id']+'.json'));stats=report['audio_checks']
        assert stats['ok'] and stats['full_decode_passed'] and stats['natural_duration_preserved'],case['id']+' failed audio checks'
        audio=ROOT/report['audio'];assert digest(audio)==stats['sha256'],'Mastered audio hash differs'
        assert digest(ROOT/case['source_audio'])==stats['source_sha256'],'Raw audio hash differs'
        workflow='configs/voices/workflows/'+case['id']+'.api.json'
        item={'id':case['id'],'voice_id':case['voice_id'],'engine':case['engine'],'url':audio.relative_to(ROOT/'web').as_posix(),
              'repository_audio':audio.relative_to(ROOT).as_posix(),'source_audio':case['source_audio'],'sha256':stats['sha256'],
              'seconds':stats['seconds'],'wall_seconds':case['wall_seconds'],'precision':PRECISION[case['engine']],
              'reference':refs[case['voice_id']]['reference'],'reference_text':refs[case['voice_id']]['reference_text'],'workflow':workflow,
              'median_f0_hz_approx':stats['median_f0_hz_approx'],'waveform':stats['waveform'],'audio_checks':stats,'asr':report['asr']}
        items.append(item)
    voices=sorted([item.copy() for item in items if item['engine']=='SoulX'],key=lambda item:item['voice_id'])
    ranking=sorted(voices,key=lambda item:item['median_f0_hz_approx'] or 0)
    for index,item in enumerate(ranking):item['label']=LABELS[index]
    for item in voices:
        item['number']=item['voice_id'][1:]
        item['pitch_label']='偏低音区' if ranking.index(item)<3 else '偏高音区' if ranking.index(item)>=7 else '中间音区'
    benchmarks=[item for item in items if item['voice_id']=='v01']
    note='样片共 12 段：10 款 SoulX 独立参考音色，另加 01 号音色的 MOSS 与 FireRed 对照。风格为选角方向；音区由自动基频估计分组，不能代替听感判断。'
    catalog={'schema_version':1,'character':'female-a','character_name':'林知夏','text':TEXT,'voices':voices,'benchmarks':benchmarks,'benchmark_note':note,
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
            item={**item,'label':next(voice['label'] for voice in voices if voice['voice_id']==item['voice_id'])};writer.writerow(item)
    archive=ROOT/'outputs/voices/female-a-voice-selection-v1.zip';archive.parent.mkdir(parents=True,exist_ok=True)
    paths=[ROOT/'web'/name for name in ('voices.html','voices.css','voices.js')]
    for folder in ('web/voice-audio/female-a-v1','outputs/voices/female-a-v1','assets/voices/female-a-v1','configs/voices'):
        paths+=sorted(path for path in (ROOT/folder).rglob('*') if path.is_file())
    paths+=[ROOT/'scripts/voice_audio.py',ROOT/'scripts/build-voice-selection.py',ROOT/'scripts/render-voice-selection.py',ROOT/'scripts/verify-voice-speakers.py',ROOT/'docs/evidence/voice-audio-quality.json',ROOT/'LICENSE',ROOT/'THIRD_PARTY_NOTICES.md']
    for name in ('docs/VOICES.md','docs/media/voice-selection-desktop.png','docs/media/voice-selection-mobile.png','docs/evidence/voice-selection-browser.json','docs/evidence/voice-selection-browser-offline.json','docs/evidence/voice-speakers.json'):
        if (ROOT/name).is_file():paths.append(ROOT/name)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(set(paths)):bundle.write(path,path.relative_to(ROOT).as_posix())
        bundle.writestr('START-HERE.txt','Open web/voices.html to audition offline. Read docs/VOICES.md for generation and live integration. No model weights included.\n打开 web/voices.html 离线试听；生成、修改和直播接入方法见 docs/VOICES.md。不含模型权重。\n')
    with zipfile.ZipFile(archive) as bundle:
        failure=bundle.testzip()
        assert failure is None,'Voice bundle ZIP CRC failure: '+str(failure)
    release={'revision':'female-a-voices-v1','count':12,'voices':10,'archive':archive.relative_to(ROOT).as_posix(),'archive_bytes':archive.stat().st_size,'archive_sha256':digest(archive),
             'page':'web/voices.html','page_sha256':digest(page),'studio_sha256':digest(ROOT/'web/studio.html'),
             'static_files':{path.relative_to(ROOT/'web').as_posix():digest(path) for path in paths if path.is_relative_to(ROOT/'web')}}
    write(ROOT/'outputs/voices/release.json',release)
    print(json.dumps({'ok':True,'voices':10,'generated_clips':12,'archive_bytes':release['archive_bytes'],'max_asr_cer':max(item['asr']['normalized_character_error_rate'] for item in items),
          'voices_by_id':[{'number':item['number'],'label':item['label'],'f0':item['median_f0_hz_approx']} for item in voices]},ensure_ascii=False))


if __name__=='__main__':main()
