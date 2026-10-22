"""Schedule whole reviewed clips and preserve identical face/body frame indices."""
from pathlib import Path
import json,random,threading

ROOT=Path(__file__).resolve().parents[3]

class MotionController:
    def __init__(self,manifest):
        self.clips=manifest['clips'];self.by_id={c['id']:c for c in self.clips}
        self.lock=threading.RLock();self.pending=None;self.turn=0;self.mode='auto'
        self.active=self.clips[0];self.offset=0
        self.random=random.Random(manifest.get('schedule_seed',20261022));self.decks={}
        self.last_speaking=False

    def request(self,clip_id):
        with self.lock:
            if clip_id=='auto':self.pending=None;self.mode='auto'
            elif clip_id=='calm':self.pending=None;self.mode='calm'
            elif clip_id in self.by_id:self.pending=clip_id
            else:raise ValueError('Unknown reviewed motion')
            return self.status()

    def choose(self,speaking):
        if self.pending:
            selected=self.by_id[self.pending];self.pending=None;return selected
        categories=('idle','listen','posture')
        if self.mode=='auto' and speaking and self.turn%3==1:categories=('explain','emphasis')
        candidates=[c for c in self.clips if c.get('category') in categories]
        if not candidates:candidates=self.clips
        key=tuple(categories)
        deck=self.decks.setdefault(key,[])
        if not deck or (len(deck)==1 and len(candidates)>1 and deck[0]['id']==self.active['id']):
            deck.clear()
            deck.extend(candidates);self.random.shuffle(deck)
        if len(deck)>1 and deck[-1]['id']==self.active['id']:
            deck[0],deck[-1]=deck[-1],deck[0]
        selected=deck.pop();self.turn+=1;return selected

    def next_indices(self,count,speaking=False):
        indices=[]
        with self.lock:
            self.last_speaking=speaking
            for _ in range(count):
                if self.offset>=self.active['frames']:
                    self.active=self.choose(speaking);self.offset=0
                indices.append(self.active['start_frame']+self.offset)
                self.offset+=1
        return indices

    def status(self):
        with self.lock:
            return {'available':True,'mode':self.mode,'active':self.active['id'],'active_title':self.active['title'],'pending':self.pending,'remaining_seconds':round(max(0,self.active['frames']-self.offset)/25,2),'clips':[{k:c[k] for k in ('id','title','category')} for c in self.clips]}

def load_motion(avatar_id):
    path=ROOT/'src/LiveTalking/data/avatars'/avatar_id/'motion-index.json'
    if not path.exists():return None
    return MotionController(json.loads(path.read_text(encoding='utf-8')))
