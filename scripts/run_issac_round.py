"""Uniform frozen-candidate checks. This runner never patches the candidate."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integration.issac.common import FileLease,file_hash,inside,read_json,write_json
from integration.issac.deployment import require_candidate
from integration.issac.preparation import runtime_environment


def blocked_by_prerequisite(name,results,*,require_media_profile=False):
    dependencies={'local-model-qualification':'local-model-prepare'}
    if require_media_profile:dependencies['local-model-prepare']='media-capacity'
    required=dependencies.get(name)
    if required and not any(row['check']==required and row['passed'] is True for row in results):
        return {'check':name,'passed':False,'state':'blocked','reason':'PREREQUISITE_NOT_PASSED','requires':required,
                'actual_inference':False,'inference_requests_attempted':0}
    return None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--include-native-game',action='store_true')
    parser.add_argument('--include-model',action='store_true')
    parser.add_argument('--include-media-profile',action='store_true')
    parser.add_argument('--include-official-client',action='store_true')
    parser.add_argument('--capacity-wait-seconds',type=int,default=3600)
    args=parser.parse_args();root=args.root.resolve();candidate=require_candidate(root)
    if not 0<=args.capacity_wait_seconds<=3600:parser.error('capacity wait must be between 0 and 3600 seconds')
    folder=inside(root,'state/issac-acceptance/round-runs')/('round-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    config=read_json(inside(root,'configs/issac/runtime.json'))['native_paths']
    py=[str(inside(root,config['game_python'])),'-X','utf8','-B']
    diag=[*py,str(inside(root,'scripts/diagnose_issac.py')),'--root',str(root)]
    media_py=[str(inside(root,config['media_python'])),'-X','utf8','-B']
    commands=[('environment',[*diag,'environment'],60),('dependencies',[*diag,'dependencies'],660),
        ('regressions',[*media_py,'-m','integration.issac.acceptance','--root',str(root),'regressions'],1800),
        ('materials-scan',[*media_py,'-m','integration.issac.materials','--root',str(root),'scan'],180)]
    if args.include_native_game:commands.append(('native-game',[*diag,'native-game'],480))
    if args.include_media_profile:
        commands.append(('media-capacity',[*py,'-m','integration.issac.media_capacity','--root',str(root)],3000))
    if args.include_model:
        commands.extend([('local-model-prepare',[*diag,'model-prepare','--capacity-wait-seconds',str(args.capacity_wait_seconds)],7200),
            ('local-model-qualification',[*py,str(inside(root,'scripts/qualify_issac_model.py')),'--root',str(root)],420)])
    if args.include_official_client:
        official=[*py,'-m','integration.issac.livehime','--root',str(root)]
        commands.extend([('official-client-signature',[*official,'prepare'],90),('official-client-launch',[*official,'launch'],180)])
    results=[]
    with FileLease(inside(root,'state/issac-acceptance/round-runner.lock')):
        for name,command,timeout in commands:
            require_candidate(root,hardware=False)
            write_json(folder/'progress.json',{**candidate,'stage':'testing','current':name,'results':results,'source_mutations_allowed':False})
            log=folder/(name+'.log');started=time.monotonic()
            blocked=blocked_by_prerequisite(name,results,require_media_profile=args.include_media_profile)
            if blocked:
                log.write_text(json.dumps(blocked,ensure_ascii=False),'utf8');result=blocked
            else:
                with log.open('wb') as output:
                    try:
                        process=subprocess.run(command,cwd=root,env=runtime_environment(root,'studio'),stdout=output,
                            stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,timeout=timeout,creationflags=0x08000000)
                        result={'check':name,'passed':process.returncode==0,'exit_code':process.returncode}
                    except subprocess.TimeoutExpired:result={'check':name,'passed':False,'reason':'FIXED_CHECK_DEADLINE'}
            require_candidate(root,hardware=False)
            results.append({**result,'elapsed_seconds':time.monotonic()-started,
                            'log':log.relative_to(root).as_posix(),'log_sha256':file_hash(log)})
        report={**candidate,'passed':all(r['passed'] for r in results),'checks':results,
            'full_acceptance_passed':False,'all_18_gates_still_required':True,'source_verified_unchanged':True,
            'official_recording_created':False,'finished_unix':time.time()}
        write_json(folder/'report.json',report)
        write_json(folder/'progress.json',{**report,'stage':'complete'})
    print(json.dumps({'report':(folder/'report.json').relative_to(root).as_posix(),**report},ensure_ascii=False),flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
