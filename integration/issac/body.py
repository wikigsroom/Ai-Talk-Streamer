"""Real decoded same-mode body loops, with complete safe drink chains."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import random
import time

import cv2
import numpy as np

from .common import AdmissionError, file_hash, inside, read_json


class BodyBank:
    def __init__(self, root, mode='M03'):
        self.root=Path(root).resolve()
        self.registry=read_json(inside(root,'state/issac-materials/runtime-bank.json'))
        if self.registry['candidate_id']!=read_json(inside(root,'.setup/candidate.json'))['id']:
            raise AdmissionError('CURRENT_CANDIDATE_BODY_BANK_REQUIRED')
        self.mode=mode
        self.cache=OrderedDict()
        self.rows={row['id']:row for row in self.registry['clips'] if row.get('runtime_enabled') is True}
        self.selected=None
        self.frame_index=0
        self.last_drink=-1e9
        self.last_idle={}
        self.current_chain=[]
        self.random=random.SystemRandom()
        self.speaking=False
        self.last_kind=None
        self.event=None
        self.request_drink=False
        self.set_mode(mode)

    def set_mode(self, mode):
        row=self.registry['modes'].get(mode)
        if not row:
            raise AdmissionError('PREPARED_SAME_MODE_BANK_REQUIRED')
        self.mode=mode
        self.reference=cv2.resize(cv2.imdecode(np.fromfile(inside(self.root,row['reference']),np.uint8),cv2.IMREAD_COLOR),(512,512),interpolation=cv2.INTER_AREA)
        self.face_region=tuple(row['face_region'])
        self.mask=np.zeros((512,512),np.float32)
        x,y,w,h=self.face_region
        cv2.ellipse(self.mask,(x+w//2,y+h//2),(w//2,h//2),0,0,360,1,-1)
        self.mask=cv2.GaussianBlur(self.mask,(21,21),0)[...,None]
        self.selected=None
        self.frame_index=0
        self.current_chain=[]
        self.request_drink=False
        self.points=self.tracking_points()

    def tracking_points(self):
        gray=cv2.cvtColor(self.reference,cv2.COLOR_BGR2GRAY)
        mask=np.zeros((512,512),np.uint8)
        x,y,w,h=self.face_region
        mask[max(0,y-60):y+h,max(0,x-30):min(512,x+w+30)]=255
        mask[y+h//2:y+h,x:x+w]=0
        return cv2.goodFeaturesToTrack(gray,maxCorners=80,qualityLevel=.02,minDistance=6,mask=mask)

    def decode(self, row):
        if row['id'] in self.cache:
            frames=self.cache.pop(row['id']);self.cache[row['id']]=frames;return frames
        path=inside(self.root,row['path'])
        if file_hash(path)!=row['sha256']:
            raise AdmissionError('ACCEPTED_BODY_CLIP_CHANGED')
        proof=read_json(inside(self.root,row['review']))
        if (proof.get('accepted') is not True or proof.get('clip_sha256')!=row['sha256']
                or proof.get('mode')!=self.mode or proof.get('candidate_id')!=self.registry['candidate_id']
                or proof.get('endpoint_replacement') is not False or proof.get('decoded_seam_reviewed') is not True):
            raise AdmissionError('REAL_BODY_CONTINUITY_REVIEW_REQUIRED')
        capture=cv2.VideoCapture(str(path))
        frames=[]
        try:
            if abs(capture.get(cv2.CAP_PROP_FPS)-25)>.01:
                raise AdmissionError('BODY_MEDIA_MUST_BE_25FPS')
            while True:
                ok,frame=capture.read()
                if not ok:break
                if frame.shape[:2]!=(512,512):
                    raise AdmissionError('BODY_MEDIA_MUST_BE_512_SQUARE')
                frames.append(frame)
                if len(frames)>375:
                    raise AdmissionError('BODY_CLIP_EXCEEDS_BOUNDED_LENGTH')
        finally:
            capture.release()
        if len(frames)<25 or len(frames)!=proof.get('decoded_frames'):
            raise AdmissionError('BODY_DECODED_FRAME_COUNT_CHANGED')
        # Never replace, repeat, reverse, freeze or synthesize clip endpoints.
        self.cache[row['id']]=frames
        while len(self.cache)>4:self.cache.popitem(last=False)
        return frames

    def preload(self):
        rows=[row for row in self.rows.values() if row['mode']==self.mode]
        if len(rows)>4:raise AdmissionError('BODY_MODE_EXCEEDS_PRELOADED_CACHE_BUDGET')
        for row in rows:self.decode(row)
        return {'mode':self.mode,'decoded_clips':len(rows)}

    def eligible(self, row, now, speaking, safe):
        if row['mode']!=self.mode or row.get('kind')=='drink_segment':return False
        if speaking and row.get('speech_safe') is not True:return False
        if not safe and row.get('safe_clear_only'):return False
        if row.get('start_state')!=self.mode+'-G0' or row.get('end_state')!=self.mode+'-G0':return False
        return now-self.last_idle.get(row['id'],-1e9)>=row.get('cooldown_seconds',0)

    def choose(self, speaking, safe):
        now=time.monotonic()
        choices=[row for row in self.rows.values() if self.eligible(row,now,speaking,safe)]
        if not choices:
            raise AdmissionError('NO_ACCEPTED_CONTINUOUS_BODY_LOOP')
        if safe and not speaking and now-self.last_drink>=120:
            chains=[chain for chain in self.registry.get('drink_chains',[]) if chain['mode']==self.mode and chain.get('runtime_enabled')]
            if chains and (self.request_drink or self.random.random()<.22):
                self.request_drink=False
                chain=self.random.choice(chains)
                if any(x not in self.rows for x in chain['clips']):raise AdmissionError('INCOMPLETE_DRINK_CHAIN')
                self.current_chain=list(chain['clips'])
                self.last_drink=now
                return self.rows[self.current_chain.pop(0)]
        weights=[max(.01,float(x.get('weight',1))) for x in choices]
        row=self.random.choices(choices,weights=weights,k=1)[0]
        self.last_idle[row['id']]=now
        return row

    @property
    def drinking(self):
        return bool(self.current_chain or self.selected and self.selected.get('kind')=='drink_segment')

    @property
    def at_boundary(self):
        return not self.drinking and (self.selected is None or self.frame_index>=len(self.decode(self.selected)))

    def next(self, *, speaking=False, safe=False):
        if self.selected is None or self.frame_index>=len(self.decode(self.selected)):
            previous=self.selected
            if self.current_chain:
                self.selected=self.rows[self.current_chain.pop(0)]
                if previous and previous['end_state']!=self.selected['start_state']:
                    raise AdmissionError('DRINK_CHAIN_STATE_MISMATCH')
            else:self.selected=self.choose(speaking,safe)
            self.frame_index=0
            self.event={'id':self.selected['id'],'kind':self.selected['kind'],'mode':self.mode,'at_unix':time.time()}
        if self.drinking and speaking:
            raise AdmissionError('SPEECH_MUST_WAIT_FOR_COMPLETED_DRINK_CHAIN')
        frames=self.decode(self.selected)
        frame=frames[self.frame_index]
        self.frame_index+=1
        self.last_kind=self.selected['kind']
        return frame.copy()

    def composite_face(self, body, face):
        if self.drinking:
            raise AdmissionError('NO_SPEECH_WITH_CUP_OCCLUSION')
        transform=np.float32([[1,0,0],[0,1,0]])
        if self.points is not None and len(self.points)>=8:
            previous=cv2.cvtColor(self.reference,cv2.COLOR_BGR2GRAY)
            current=cv2.cvtColor(body,cv2.COLOR_BGR2GRAY)
            found,status,_=cv2.calcOpticalFlowPyrLK(previous,current,self.points,None,winSize=(25,25),maxLevel=3)
            mask=status[:,0]==1
            if mask.sum()<8:
                raise AdmissionError('BODY_FACE_ALIGNMENT_UNCERTAIN')
            estimated,inliers=cv2.estimateAffinePartial2D(self.points[mask],found[mask],method=cv2.RANSAC,ransacReprojThreshold=2)
            if estimated is None or inliers.sum()<8 or np.max(np.abs(estimated[:,2]))>18:
                raise AdmissionError('BODY_FACE_ALIGNMENT_OUT_OF_BOUNDS')
            transform=estimated.astype(np.float32)
        shifted=cv2.warpAffine(face,transform,(512,512),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
        alpha=cv2.warpAffine(self.mask,transform,(512,512),flags=cv2.INTER_LINEAR)
        if alpha.ndim==2:alpha=alpha[...,None]
        return np.rint(shifted*alpha+body*(1-alpha)).clip(0,255).astype(np.uint8)

    def status(self):
        return {'mode':self.mode,'clip':self.selected['id'] if self.selected else None,'clip_frame':self.frame_index,
                'drinking':self.drinking,'last_event':self.event,'accepted_clips':len([x for x in self.rows.values() if x['mode']==self.mode]),
                'endpoint_replacement':False,'body_is_audio_driven_mouth':False}
