"""Schedule whole reviewed clips and preserve identical face/body frame indices."""
from pathlib import Path
import json,random,threading,time

ROOT=Path(__file__).resolve().parents[3]

class MotionController:
    def __init__(self,manifest):
        self.clips=manifest['clips'];self.by_id={c['id']:c for c in self.clips}
        self.lock=threading.RLock();self.pending=None;self.turn=0;self.mode='auto'
        self.active=self.clips[0];self.offset=0
        self.random=random.Random(manifest.get('schedule_seed',20261022));self.decks={}
        self.last_speaking=False
        self.expression='attentive';self.expression_until=0;self.generated=0;self.history=[]
        self.idle_turn=0;self.fps=manifest.get('fps',25)

    def express(self,expression):
        if expression not in ('attentive','thoughtful','pleased','concerned'):return
        with self.lock:
            self.expression=expression;self.expression_until=time.monotonic()+24

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
        expression=self.expression if time.monotonic()<self.expression_until else 'attentive'
        # Full original clips keep face/body indices aligned. Visible head and
        # eye movement also works when hand gestures fall outside a circle.
        preferred={
            'thoughtful':('m25_listen_tilt_right','m26_listen_tilt_left','m32_listen_thoughtful_return'),
            'pleased':('m28_listen_double_nod','m32_listen_thoughtful_return','m33_posture_settle_shoulders'),
            'concerned':('m27_listen_slow_nod','m31_listen_lean_listen'),
            'attentive':('idle_a','idle_b','m25_listen_tilt_right','m26_listen_tilt_left','m33_posture_settle_shoulders','m38_posture_sit_taller'),
        }
        if self.mode=='auto' and not speaking:
            self.idle_turn+=1
            ids=('m26_listen_tilt_left',) if self.idle_turn%2==0 else preferred[expression]
            candidates=[self.by_id[k] for k in ids if k in self.by_id and k!=self.active['id']]
            if candidates:
                self.turn+=1;return self.random.choice(candidates)
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
                    self.history.append({'id':self.active['id'],'frame':self.generated,'speaking':bool(speaking),'expression':self.expression})
                    self.history=self.history[-16:]
                indices.append(self.active['start_frame']+self.offset)
                self.offset+=1
                self.generated+=1
        return indices

    def status(self):
        with self.lock:
            return {'available':True,'mode':self.mode,'active':self.active['id'],'active_title':self.active['title'],'pending':self.pending,'expression':self.expression,'generated_frames':self.generated,'history':list(self.history),'remaining_seconds':round(max(0,self.active['frames']-self.offset)/self.fps,2),'clips':[{k:c[k] for k in ('id','title','category')} for c in self.clips]}

def load_motion(avatar_id):
    path=ROOT/'src/LiveTalking/data/avatars'/avatar_id/'motion-index.json'
    if not path.exists():return None
    return MotionController(json.loads(path.read_text(encoding='utf-8')))
