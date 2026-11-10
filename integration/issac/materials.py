"""Inspect retained candidates, retain real frames, and admit reviewed body loops."""
from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import re
import subprocess
import time

from .common import AdmissionError,digest,file_hash,inside,read_json,write_json
from .deployment import require_candidate

MATERIAL_ROOT='references/naimei-production-20261107'
REMOTE_MEDIA='references/remote-naimei-media-20261107'
OPEN_ANCHOR='assets/naimei/production-freeze-v1/snapshots/mouth/open-anchor-512.png'
OPEN_SHA='a3ccc15ee02bc3c80eb303757645a5a93570e6e2917d2a04a818e13d5564b6a4'
CHECKS={'same_locked_character','all_frames_anatomy','four_fingers_per_hand','one_tail','controller_stable',
        'closed_silent_mouth','natural_motion','first_last_real_frames','directed_join_at_actual_speed',
        'no_endpoint_replacement','same_mode_scene','no_mirroring'}


def generation(root,candidate):
    identity=candidate['candidate_id']
    if not re.fullmatch(r'issac-[0-9a-f]{12}-[0-9a-f]{8}',identity):
        raise AdmissionError('FROZEN_MATERIAL_GENERATION_REQUIRED')
    return inside(root,'state/issac-materials/generations/'+identity)


def ffmpeg(root,name='ffmpeg.exe'):
    candidates=list(inside(root,'tools/ffmpeg').rglob(name))
    if len(candidates)!=1:raise AdmissionError('ONE_PINNED_NATIVE_MEDIA_TOOL_REQUIRED')
    return str(candidates[0])


def scan(root):
    candidate=require_candidate(root,hardware=False)
    jobs=inside(root,MATERIAL_ROOT+'/assets/naimei/comfy-production-v1/jobs')
    source=inside(root,REMOTE_MEDIA+'/naimei-comfy-production-20261106')
    rows=[]
    for path in sorted(source.rglob('*.mp4')):
        job_file=jobs/(path.parent.name+'.json')
        if not job_file.is_file():continue
        job=read_json(job_file)
        if job.get('mode') not in {'M01','M02','M03'} or not job.get('start_state') or not job.get('end_state'):continue
        rows.append({'id':job['id'],'mode':job['mode'],'source':path.relative_to(root).as_posix(),
            'source_sha256':file_hash(path),'job':job_file.relative_to(root).as_posix(),'job_sha256':file_hash(job_file),
            'start_state':job['start_state'],'end_state':job['end_state'],'runtime_enabled':False})
    report={**candidate,'clips':rows,'retained_candidates':len(rows),'quality_accepted':False,'scanned_at':time.time()}
    write_json(inside(root,'state/issac-materials/candidates.json'),report)
    write_json(generation(root,candidate)/'candidates.json',report)
    return report


def inspect(root,clip_id):
    import cv2
    import numpy as np
    from PIL import Image,ImageDraw
    candidate=require_candidate(root,hardware=False)
    folder_root=generation(root,candidate)
    source_index=read_json(folder_root/'candidates.json')
    if source_index['candidate_id']!=candidate['candidate_id']:raise AdmissionError('CURRENT_MATERIAL_INDEX_REQUIRED')
    row=next((r for r in source_index['clips'] if r['id']==clip_id),None)
    if not row:raise AdmissionError('PINNED_EXISTING_CLIP_REQUIRED')
    source=inside(root,row['source'])
    if file_hash(source)!=row['source_sha256']:raise AdmissionError('BODY_SOURCE_CHANGED')
    destination=folder_root/'clips'/(clip_id+'.mp4')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():raise AdmissionError('MATERIAL_INSPECTION_ALREADY_EXISTS')
    capture=cv2.VideoCapture(str(source));frames=[]
    original_fps=capture.get(cv2.CAP_PROP_FPS)
    try:
        while True:
            ok,frame=capture.read()
            if not ok:break
            frames.append(cv2.resize(frame,(512,512),interpolation=cv2.INTER_AREA))
            if len(frames)>375:raise AdmissionError('BOUNDED_BODY_CANDIDATE_REQUIRED')
    finally:capture.release()
    if len(frames)<25:raise AdmissionError('REAL_MOTION_CLIP_REQUIRED')
    # Preserve every original decoded frame, once, in original order. Native
    # 24fps assets play ~4% faster at 25fps; no synthesized/interpolated endpoint.
    pipe=subprocess.Popen([ffmpeg(root),'-hide_banner','-v','error','-n','-f','rawvideo','-pix_fmt','bgr24',
        '-s','512x512','-r','25','-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','16',
        '-pix_fmt','yuv420p','-movflags','+faststart',str(destination)],stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,creationflags=0x08000000)
    try:
        for frame in frames:pipe.stdin.write(frame.tobytes())
        pipe.stdin.close();error=pipe.stderr.read();code=pipe.wait(120)
        if code:raise AdmissionError('BODY_FRAME_PRESERVING_ENCODE_FAILED')
    finally:
        if pipe.poll() is None:pipe.terminate();pipe.wait(10)
    folder=folder_root/'inspection'/clip_id;folder.mkdir(parents=True,exist_ok=True)
    images=[]
    for start in range(0,len(frames),48):
        sheet=Image.new('RGB',(1024,8*152),'#20252d');draw=ImageDraw.Draw(sheet)
        for offset,frame in enumerate(frames[start:start+48]):
            image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));image.thumbnail((170,128))
            x=(offset%6)*170;y=(offset//6)*152;sheet.paste(image,(x,y));draw.text((x+4,y+130),str(start+offset),fill='white')
        path=folder/f'all-frames-{start:04d}.jpg';sheet.save(path,quality=94)
        images.append({'path':path.relative_to(root).as_posix(),'sha256':file_hash(path)})
    seam=Image.new('RGB',(1024,512))
    seam.paste(Image.fromarray(cv2.cvtColor(frames[-1],cv2.COLOR_BGR2RGB)),(0,0));seam.paste(Image.fromarray(cv2.cvtColor(frames[0],cv2.COLOR_BGR2RGB)),(512,0))
    path=folder/'real-last-and-first.jpg';seam.save(path,quality=97)
    images.append({'path':path.relative_to(root).as_posix(),'sha256':file_hash(path)})
    differences=[float(np.abs(b.astype(np.int16)-a.astype(np.int16)).mean()) for a,b in zip(frames,frames[1:])]
    report={**row,'candidate_id':candidate['candidate_id'],'path':destination.relative_to(root).as_posix(),
        'sha256':file_hash(destination),'decoded_frames':len(frames),'source_fps':original_fps,'fps':25,
        'endpoint_replacement':False,'source_frames_preserved_once_in_order':True,
        'real_end_to_start_mae':float(np.abs(frames[-1].astype(np.int16)-frames[0].astype(np.int16)).mean()),
        'adjacent_mae_mean':sum(differences)/len(differences),'images':images,
        'quality_accepted':False,'all_frame_sheet_is_not_actual_speed_review':True}
    write_json(folder/'inspection.json',report)
    template={ 'id':clip_id,'candidate_id':candidate['candidate_id'],'inspection_sha256':digest(report),
        'reviewer':None,'reviewed_evidence':images,'accepted':False,'checks':{key:False for key in sorted(CHECKS)},
        'kind':None,'speech_safe':False,'safe_clear_only':False,'weight':1,'cooldown_seconds':12,
        'actual_speed_viewed':False,'cup_chain_complete':False,'rejection_reason':None}
    write_json(folder/'review-template.json',template)
    return report


def approve(root,review_file):
    current=require_candidate(root,hardware=False)
    review=read_json(inside(root,review_file));clip_id=review.get('id','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',clip_id):raise AdmissionError('PINNED_CLIP_ID_REQUIRED')
    folder=generation(root,current)/'inspection'/clip_id
    inspected=read_json(folder/'inspection.json')
    if (review.get('candidate_id')!=current['candidate_id'] or review.get('inspection_sha256')!=digest(inspected)
        or not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip()
        or review.get('accepted') is not True or review.get('actual_speed_viewed') is not True
        or set(review.get('checks',{}))!=CHECKS or not all(v is True for v in review['checks'].values())
        or review.get('reviewed_evidence')!=inspected['images']):
        raise AdmissionError('EXPLICIT_ACTUAL_SPEED_AND_ALL_FRAME_REVIEW_REQUIRED')
    for image in inspected['images']:
        if file_hash(inside(root,image['path']))!=image['sha256']:raise AdmissionError('MATERIAL_REVIEW_EVIDENCE_CHANGED')
    if review.get('kind') not in {'idle','controller','reaction','drink_segment'}:raise AdmissionError('REVIEWED_ACTION_KIND_REQUIRED')
    if review['kind']=='drink_segment' and review.get('cup_chain_complete') is not True:
        raise AdmissionError('WHOLE_REVIEWED_DRINK_CHAIN_REQUIRED')
    proof={**inspected,'accepted':True,'clip_sha256':inspected['sha256'],'decoded_seam_reviewed':True,
           'review':review,'reviewed_at':time.time()}
    destination=generation(root,current)/'reviews'/(clip_id+'.json')
    write_json(destination,proof)
    return {'review':destination.relative_to(root).as_posix(),'accepted':True,'id':clip_id}


def inherit_reviewed_bank(root):
    """Rebind only byte-identical approved media, without rescanning all jobs."""
    from copy import deepcopy
    candidate=require_candidate(root,hardware=False)
    path=inside(root,'state/issac-materials/runtime-bank.json');prior=read_json(path)
    if prior['candidate_id']==candidate['candidate_id']:return {'unchanged':True}
    if prior.get('body_reviewed') is not True:raise AdmissionError('PRIOR_REVIEWED_BODY_BANK_REQUIRED')
    bank=deepcopy(prior);records=[]
    binding=read_json(inside(root,'configs/issac/character-inheritance.json'))
    if set(bank['modes'])!={row['mode_id'] for row in binding['modes']}:
        raise AdmissionError('INHERITED_MODE_BINDING_CHANGED')
    for locked in binding['modes']:
        mode=bank['modes'][locked['mode_id']]
        expected_face=[170,155,190,134] if locked['mode_id']=='M03' else [175,125,173,110]
        if (mode['reference']!=locked['reference_image'] or mode['reference_sha256']!=locked['sha256']
                or mode['engine_reference']!=MATERIAL_ROOT+'/'+OPEN_ANCHOR
                or mode['engine_reference_sha256']!=OPEN_SHA or mode['face_region']!=expected_face
                or file_hash(inside(root,mode['engine_reference']))!=OPEN_SHA):
            raise AdmissionError('INHERITED_CHARACTER_BINDING_CHANGED')
    if bank.get('mouth_constraints',{}).get('original_closeup_sha256')!=OPEN_SHA:
        raise AdmissionError('INHERITED_ORAL_BINDING_CHANGED')
    for row in bank['clips']:
        proof_path=inside(root,row['review']);proof=read_json(proof_path)
        if (proof.get('accepted') is not True or proof.get('decoded_seam_reviewed') is not True
                or proof.get('candidate_id')!=prior['candidate_id'] or proof.get('clip_sha256')!=row['sha256']
                or proof.get('sha256')!=row['sha256'] or proof.get('mode')!=row['mode']
                or not proof.get('review',{}).get('actual_speed_viewed')
                or any(proof.get(k)!=row[k] for k in ('id','mode','path','sha256','start_state','end_state'))):
            raise AdmissionError('EXISTING_ACTUAL_SPEED_BODY_APPROVAL_REQUIRED')
        if file_hash(inside(root,row['path']))!=row['sha256'] or file_hash(inside(root,proof['source']))!=proof['source_sha256']:
            raise AdmissionError('INHERITED_BODY_BYTES_CHANGED')
        for image in proof['images']:
            if file_hash(inside(root,image['path']))!=image['sha256']:raise AdmissionError('INHERITED_BODY_FRAME_EVIDENCE_CHANGED')
        proof['inherited_approval']={'candidate_id':prior['candidate_id'],'path':row['review'],
            'sha256':file_hash(proof_path),'same_original_encoded_and_frame_evidence':True,'new_subjective_review_claimed':False}
        proof['candidate_id']=candidate['candidate_id']
        review=generation(root,candidate)/'reviews'/(row['id']+'.json');write_json(review,proof)
        row['review']=review.relative_to(root).as_posix();records.append(row['id'])
    for mode in bank['modes'].values():
        if file_hash(inside(root,mode['reference']))!=mode['reference_sha256']:raise AdmissionError('INHERITED_MODE_REFERENCE_CHANGED')
    for image in bank.get('mouth_constraints',{}).get('upper_fangs',[]):
        if file_hash(inside(root,image['path']))!=image['sha256']:raise AdmissionError('INHERITED_FANG_IMAGE_CHANGED')
    bank['candidate_id']=candidate['candidate_id'];bank['inherited_from_candidate']=prior['candidate_id']
    write_json(path,bank);write_json(generation(root,candidate)/'runtime-bank.json',bank)
    return {'candidate_id':candidate['candidate_id'],'verified_clips':records,'new_subjective_review_claimed':False}


def build_bank(root):
    candidate=require_candidate(root,hardware=False)
    binding=read_json(inside(root,'configs/issac/character-inheritance.json'))
    closeup=inside(root,MATERIAL_ROOT+'/'+OPEN_ANCHOR)
    if file_hash(closeup)!=OPEN_SHA:raise AdmissionError('ORIGINAL_FLASHHEAD_CLOSEUP_REQUIRED')
    modes={};clips=[]
    for mode in binding['modes']:
        reference=inside(root,mode['reference_image'])
        if file_hash(reference)!=mode['sha256']:raise AdmissionError('LOCKED_MODE_REFERENCE_CHANGED')
        face=[175,125,173,110] if mode['mode_id']!='M03' else [170,155,190,134]
        modes[mode['mode_id']]={'reference':mode['reference_image'],'reference_sha256':mode['sha256'],
            'face_region':face,'engine_reference':closeup.relative_to(root).as_posix(),'engine_reference_sha256':OPEN_SHA,
            'engine_closeup_is_oral_conditioning_only':True}
    for path in sorted((generation(root,candidate)/'reviews').glob('*.json')):
        proof=read_json(path)
        if not proof.get('accepted') or proof['candidate_id']!=candidate['candidate_id']:continue
        review=proof['review']
        clips.append({k:proof[k] for k in ('id','mode','path','sha256','start_state','end_state')}|
            {k:review[k] for k in ('kind','speech_safe','safe_clear_only','weight','cooldown_seconds')}|
            {'review':path.relative_to(root).as_posix(),'runtime_enabled':True})
    chains=[]
    for mode in modes:
        kinds={r['kind'] for r in clips if r['mode']==mode and r['start_state']==r['end_state']==mode+'-G0'}
        if not {'idle','controller','reaction'}.issubset(kinds):raise AdmissionError('THREE_REVIEWED_ACTION_TYPES_PER_MODE_REQUIRED')
        # A complete G0-to-G0 cup clip is a one-segment complete chain. Interior
        # states can form a directed chain; no cross-mode/cross-state shortcuts.
        edges=[r for r in clips if r['mode']==mode and r['kind']=='drink_segment']
        pending=deque([(mode+'-G0',[])])
        while pending:
            state,used=pending.popleft()
            if len(used)>=10:continue
            for row in edges:
                if row['id'] in used or row['start_state']!=state:continue
                sequence=used+[row['id']]
                if row['end_state']==mode+'-G0':
                    chains.append({'mode':mode,'clips':sequence,'runtime_enabled':True})
                else:pending.append((row['end_state'],sequence))
        if not any(c['mode']==mode for c in chains):raise AdmissionError('COMPLETE_REVIEWED_DRINK_CHAIN_PER_MODE_REQUIRED')
    fang_folder=MATERIAL_ROOT+'/assets/naimei/production-freeze-v1/snapshots/mouth'
    fangs=[{'path':f'{fang_folder}/original-upper-fang-{index}.png',
            'sha256':file_hash(inside(root,f'{fang_folder}/original-upper-fang-{index}.png'))} for index in (1,2)]
    registry={'candidate_id':candidate['candidate_id'],'modes':modes,'clips':clips,'drink_chains':chains,
        'mouth_constraints':{'upper_fangs':fangs,'original_closeup_sha256':OPEN_SHA},
        'body_reviewed':True,'mouth_quality_accepted':False,'historical_speech_is_not_admitted':True}
    write_json(inside(root,'state/issac-materials/runtime-bank.json'),registry)
    write_json(generation(root,candidate)/'runtime-bank.json',registry)
    return {'modes':len(modes),'accepted_clips':len(clips),'drink_chains':len(chains),'mouth_quality_accepted':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    sub=parser.add_subparsers(dest='action',required=True);sub.add_parser('scan');sub.add_parser('build-bank')
    sub.add_parser('inspect').add_argument('--id',required=True);sub.add_parser('approve').add_argument('--review',required=True)
    args=parser.parse_args();root=args.root.resolve()
    result=scan(root) if args.action=='scan' else inspect(root,args.id) if args.action=='inspect' else approve(root,args.review) if args.action=='approve' else build_bank(root)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
