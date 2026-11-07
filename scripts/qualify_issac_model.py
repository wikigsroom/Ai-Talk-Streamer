"""Frozen-candidate real local inference qualification, never a mock pass."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integration.issac.common import inside, write_json
from integration.issac.deployment import require_candidate
from integration.issac.local_model import LocalModel


def qualify(root):
    candidate=require_candidate(root)
    model=LocalModel(root)
    tests=[
      ('unknown_pill','当前口袋是一颗未识别药丸。只返回JSON，字段decision应为hold，不能声称知道效果。',{'decision':'hold'}),
      ('accepted_not_success','只有 accepted 计划回执，没有实际效果。只返回JSON，字段succeeded应为false。',{'succeeded':False}),
      ('half_hearts','普通Isaac红心3半心、魂心1半心。换算总整心数，返回JSON字段hearts。',{'hearts':2}),
      ('stale_room','证据来自房间A，现在已在房间B。同一seed。返回JSON字段usable=false。',{'usable':False}),
      ('rep_edition','当前版本Repentance1.7.9b，Wiki默认Rep+。查询时edition应是什么？返回JSON。',{'edition':'rep'}),
    ]
    outcomes=[]
    for name,prompt,expected in tests:
        start=time.monotonic()
        try:
            response=model.complete({'messages':[{'role':'system','content':'只返回一个JSON对象，不含其他文字。'},
                                                {'role':'user','content':prompt}], 'max_tokens':100,'temperature':0})
            choice=response['choices'][0]
            text=choice['message']['content'].strip()
            actual=json.loads(text)
            passed=choice.get('finish_reason')=='stop' and all(actual.get(k)==v for k,v in expected.items())
            outcomes.append({'id':name,'passed':passed,'seconds':time.monotonic()-start,'actual':actual})
        except Exception:
            outcomes.append({'id':name,'passed':False,'seconds':time.monotonic()-start,'reason':'REAL_INFERENCE_OR_STRUCTURED_RESPONSE_FAILED'})
    tool={'type':'function','function':{'name':'isaac_wiki_query','description':'查询固定离线Wiki',
          'parameters':{'type':'object','properties':{'operation':{'type':'string','enum':['item']},'query':{'type':'string'}},'required':['operation','query'],'additionalProperties':False}}}
    try:
        start=time.monotonic()
        response=model.complete({'messages':[{'role':'user','content':'请调用isaac_wiki_query，operation=item，query=Brimstone，不要回答道具效果。'}],
                    'tools':[tool],'tool_choice':'auto','max_tokens':160,'temperature':0})
        choice=response['choices'][0]
        call=choice['message']['tool_calls'][0]
        args=json.loads(call['function']['arguments'])
        outcomes.append({'id':'actual_fifth_tool','passed':choice.get('finish_reason')=='tool_calls' and call['function']['name']=='isaac_wiki_query' and args=={'operation':'item','query':'Brimstone'},'seconds':time.monotonic()-start})
    except Exception:
        outcomes.append({'id':'actual_fifth_tool','passed':False,'reason':'REAL_TOOL_CALL_FAILED'})
    durations=[x['seconds'] for x in outcomes if 'seconds' in x]
    result={'candidate_id':candidate['candidate_id'],'model':model.config['model'],
            'qualified':all(x['passed'] for x in outcomes) and max(durations,default=999)<35,
            'tests':outcomes,'max_seconds':max(durations,default=None),'median_seconds':statistics.median(durations) if durations else None,
            'actual_inference':True,'cohost_performance_accepted':False,'cloud_fallback':False}
    write_json(inside(root,'state/isaac-strategy/model-qualification.json'),result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args()
    result=qualify(args.root.resolve());print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['qualified'] else 1)
