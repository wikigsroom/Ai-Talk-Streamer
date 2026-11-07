"""Fixed local control/status operations; no arbitrary process or shell action."""
import argparse
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from integration.issac.common import read_json,inside


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('action',choices=['status','stop','launch-game','pause','resume','observe','install','attach','model-prepare'])
    parser.add_argument('--pid',type=int);args=parser.parse_args();root=args.root.resolve()
    if args.action=='model-prepare':
        from integration.issac.deployment import require_candidate
        from integration.issac.local_model import LocalModel
        require_candidate(root);result=LocalModel(root).prepare()
    else:
        application=args.action in {'status','stop','launch-game'}
        port=9541 if application else 9534
        path='/status' if args.action=='status' else '/action' if application else '/control'
        body=None if args.action=='status' else {'action':'launch_game' if args.action=='launch-game' else args.action}
        if args.action=='attach':body['pid']=args.pid
        token=inside(root,'private/issac/bridge-token.txt').read_text('ascii').strip()
        request=urllib.request.Request(f'http://127.0.0.1:{port}'+path,
            data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Isaac-Token':token})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=30) as response:result=json.load(response)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
