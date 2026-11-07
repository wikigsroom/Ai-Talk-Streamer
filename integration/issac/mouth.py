"""Original FlashHead oral projection and two-fang constraint, adapted for live use.

Derived from the frozen 2026-11-04 compose_speech.py recipe. Aperture, lips,
cavity and tongue come from actual FlashHead frames. PCM gates only sustained
silence; it never creates phonemes or controls an invented mouth aperture.
Prior output was not quality-accepted. Fresh mouth/teeth review is mandatory.
"""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image,ImageDraw,ImageFilter
from .common import AdmissionError,inside,file_hash,read_json

GEOMETRY={'M01':(259,201,.46),'M02':(259,201,.46),'M03':(263,258,.60)}

def gray(a):return a[...,0]*.25+a[...,1]*.60+a[...,2]*.15

class Tracker:
    def __init__(self,reference,mode):
        self.cx,self.cy,self.ratio=GEOMETRY[mode]
        self.x=round(self.cx);self.y=round(self.cy)
        self.box=(self.x-30,self.y-10,self.x+30,self.y+12)
        sample=np.asarray(Image.fromarray(reference).crop(self.box).resize((30,11)))
        self.template=gray(sample).astype(np.float32)
        self.template-=self.template.mean()
        self.norm=max(1,float(np.sqrt((self.template**2).sum())))
        self.last=np.array([self.cx,self.cy],np.float32)
    def locate(self,frame):
        bx,by=self.x-48,self.y-28
        region=np.asarray(Image.fromarray(frame).crop((bx,by,self.x+48,self.y+30)).resize((48,29)))
        windows=sliding_window_view(gray(region).astype(np.float32),(11,30))
        sums=windows.sum(axis=(-1,-2));sq=(windows**2).sum(axis=(-1,-2))
        norms=np.sqrt(np.maximum(1,sq-sums**2/330))
        scores=np.einsum('ijkl,kl->ij',windows,self.template,optimize=True)/(norms*self.norm)
        y,x=np.unravel_index(np.argmax(scores),scores.shape)
        measured=np.array([bx+x*2+30,by+y*2+10],np.float32)
        score=float(scores[y,x])
        if score<.4:measured=self.last
        # Limit improbable single-frame jumps; track plate motion independently of speech.
        delta=np.clip(measured-self.last,-3,3)
        self.last=self.last+delta*.75
        return tuple(self.last),score

def component(mask):
    # Largest central connected oral component; reject hair at the crop edges.
    h,w=mask.shape;visited=np.zeros_like(mask);best=None;best_score=-1e9
    for y,x in np.argwhere(mask):
        if visited[y,x]:continue
        stack=[(int(y),int(x))];visited[y,x]=True;points=[]
        while stack:
            yy,xx=stack.pop();points.append((yy,xx))
            for dy,dx in ((0,1),(0,-1),(1,0),(-1,0)):
                yn,xn=yy+dy,xx+dx
                if 0<=yn<h and 0<=xn<w and mask[yn,xn] and not visited[yn,xn]:
                    visited[yn,xn]=True;stack.append((yn,xn))
        if len(points)<45:continue
        points=np.asarray(points);y0,x0=points.min(axis=0);y1,x1=points.max(axis=0)
        width,height=x1-x0+1,y1-y0+1
        if width<15 or height<5 or width>120 or height>80:continue
        cx=(x0+x1)/2;cy=(y0+y1)/2
        if x0<10 or x1>w-10 or y0<24 or cy<40:continue
        score=len(points)-abs(cx-85)*15-abs(cy-58)*5
        if score>best_score:best_score=score;best=(x0,y0,x1+1,y1+1,len(points),points)
    return best

def hull(points):
    pts=sorted(set((int(x),int(y)) for y,x in points))
    def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    low=[]
    for p in pts:
        while len(low)>=2 and cross(low[-2],low[-1],p)<=0:low.pop()
        low.append(p)
    high=[]
    for p in reversed(pts):
        while len(high)>=2 and cross(high[-2],high[-1],p)<=0:high.pop()
        high.append(p)
    return low[:-1]+high[:-1]

def oral_crop(frame):
    region=frame[350:476,170:340]
    r,g,b=region[...,0],region[...,1],region[...,2]
    mask=(r<160)&(g<108)&(b<125)&(r.astype(np.float32)>b.astype(np.float32)*1.3+8)
    found=component(mask)
    if found is None:return None
    x0,y0,x1,y1,area,points=found
    if area<65 or y1-y0<7:return None
    # Keep the model's lips, tongue and upper fangs inside one contiguous crop.
    x0=max(0,x0-4);x1=min(region.shape[1],x1+4)
    y0=max(0,y0-4);y1=min(region.shape[0],y1+5)
    alpha=Image.new('L',(x1-x0,y1-y0),0)
    ImageDraw.Draw(alpha).polygon([(x-x0,y-y0) for x,y in hull(points)],fill=255)
    alpha=alpha.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.1))
    return region[y0:y1,x0:x1].copy(),(x0+170,y0+350,x1+170,y1+350),area,alpha

def paste_mouth(plate,source,center,ratio):
    found=oral_crop(source)
    if found is None:return plate.copy(),{'open':False}
    patch,box,area,source_alpha=found
    width=max(8,round(patch.shape[1]*ratio));height=max(5,round(patch.shape[0]*ratio))
    # The original opening is aligned to the closed plate's upper lip.
    cx,cy=center;left=round(cx-width/2);top=round(cy-3)
    patch=np.asarray(Image.fromarray(patch).resize((width,height),Image.Resampling.LANCZOS)).astype(np.float32)
    result=plate.copy();dest=result[top:top+height,left:left+width].astype(np.float32)
    # Match surrounding skin; retain the actual model's dark oral cavity and teeth.
    edge=np.concatenate([patch[0],patch[-1],patch[:,0],patch[:,-1]])
    skin=(edge[:,0]>180)&(edge[:,1]>95)&(edge[:,2]<160)
    if skin.sum()>4:
        dest_skin=np.concatenate([dest[0],dest[-1],dest[:,0],dest[:,-1]])
        delta=np.median(dest_skin,axis=0)-np.median(edge[skin],axis=0)
        yellow=(patch[...,0]>175)&(patch[...,1]>95)&(patch[...,2]<170)
        patch[yellow]=np.clip(patch[yellow]+delta,0,255)
    # Remove the whole original closed smile, including its raised corners.
    fill_x0=round(cx-33*ratio/.46);fill_x1=round(cx+33*ratio/.46)
    fill_y0=round(cy-13);fill_y1=round(cy+16)
    base=result[fill_y0:fill_y1,fill_x0:fill_x1].astype(np.float32)
    upper=result[fill_y0-2,fill_x0:fill_x1].astype(np.float32)
    lower=result[fill_y1+2,fill_x0:fill_x1].astype(np.float32)
    weight=np.linspace(0,1,len(base))[:,None,None]
    smooth=upper[None,:,:]*(1-weight)+lower[None,:,:]*weight
    yy,xx=np.mgrid[:len(base),:base.shape[1]]
    difference=gray(smooth)-gray(base)
    line=(difference>8).astype(np.uint8)*255
    fill_alpha=np.asarray(Image.fromarray(line).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(.85)),np.float32)/255
    result[fill_y0:fill_y1,fill_x0:fill_x1]=np.clip(base*(1-fill_alpha[...,None])+smooth*fill_alpha[...,None],0,255).astype(np.uint8)
    alpha=np.asarray(source_alpha.resize((width,height),Image.Resampling.LANCZOS),np.float32)/255
    dest=result[top:top+height,left:left+width].astype(np.float32)
    result[top:top+height,left:left+width]=np.clip(dest*(1-alpha[...,None])+patch*alpha[...,None],0,255).astype(np.uint8)
    return result,{'open':True,'source_box':list(map(int,box)),'oral_component_area':area,
                   'target_box':[left,top,width,height]}

class ConstrainedMouth:
    def __init__(self, root):
        config=read_json(inside(root,'state/issac-materials/runtime-bank.json'))['mouth_constraints']
        self.last=None
        self.fangs=[]
        for row in config['upper_fangs']:
            path=inside(root,row['path'])
            if file_hash(path)!=row['sha256']:
                raise AdmissionError('ORIGINAL_UPPER_FANG_TEXTURE_CHANGED')
            self.fangs.append(Image.open(path).convert('RGBA'))
        if len(self.fangs)!=2:
            raise AdmissionError('EXACT_TWO_ORIGINAL_UPPER_FANGS_REQUIRED')

    def project(self,plate,source,center,ratio,gated):
        found=oral_crop(source)
        if gated or found is None:
            self.last=None
            return plate.copy(),{'open':False,'silence_gated':gated,'postprocess':'identity-constrained-original-mouth-texture'}
        patch,box,area,alpha=found
        if patch.shape[1]<33 or patch.shape[0]<16:
            return plate.copy(),{'open':False,'postprocess':'reject incomplete oral fragment'}
        coverage=np.asarray(alpha,np.float32)/255
        white=(patch[...,0]>135)&(patch[...,1]>115)&(patch[...,2]>105)&(patch[...,2]>patch[...,0]*.48)&(coverage>.5)
        remove=np.asarray(Image.fromarray(white.astype(np.uint8)*255).filter(ImageFilter.MaxFilter(3)),np.float32)/255
        clean=patch.astype(np.float32)
        for y in range(len(clean)):
            candidates=(coverage[y]>.5)&(~white[y])&(patch[y,:,1]<115)&(patch[y,:,0]<210)
            color=np.median(patch[y,candidates],axis=0) if candidates.any() else np.array([63,13,19])
            amount=remove[y]*(coverage[y]>.5)
            clean[y]=clean[y]*(1-amount[:,None])+color[None,:]*amount[:,None]
        oral=(coverage>.55)&(clean[...,1]<135)&(clean[...,0]<225)
        for fraction,fang in zip((.23,.77),self.fangs):
            cx=round((patch.shape[1]-1)*fraction)
            rows=np.where(oral[:,cx])[0]
            if not len(rows):continue
            top=int(rows[0]);scale=(patch.shape[1]-8)/80
            fw=max(3,round(fang.width*scale));fh=max(4,round(fang.height*scale))
            left=cx-fw//2;fh=min(fh,patch.shape[0]-top)
            texture=np.asarray(fang.resize((fw,fh),Image.Resampling.LANCZOS),np.float32)
            opacity=texture[...,3]/255*oral[top:top+fh,left:left+fw]
            destination=clean[top:top+fh,left:left+fw]
            clean[top:top+fh,left:left+fw]=destination*(1-opacity[...,None])+texture[...,:3]*opacity[...,None]
        # Preserve the model's own lips, oral shape and tongue. Only tooth pixels are constrained.
        carrier=source.copy();x0,y0,x1,y1=box
        carrier[y0:y1,x0:x1]=np.clip(clean,0,255).astype(np.uint8)
        result,record=paste_mouth(plate,carrier,center,ratio)
        if record.get('open'):
            sx0,sy0,sx1,sy1=record['source_box']
            if sx1-sx0<30 or (sx1-sx0)/(sy1-sy0)<1.5:
                return plate.copy(),{'open':False,'postprocess':'reject unstable incomplete oral fragment'}
        record.update(postprocess='actual FlashHead mouth with original two-upper-fang constraint',raw_model_box=list(map(int,box)),
                      aperture_source='actual FlashHead lips, cavity and tongue',tooth_pixels_constrained=True)
        return result,record

class MouthProjector:
    def __init__(self,root,mode,reference_bgr):
        self.tracker=Tracker(reference_bgr[...,::-1].copy(),mode)
        self.mouth=ConstrainedMouth(root)
        self.quiet=0
        self.seen_voice=False

    def reset(self):
        self.quiet=0
        self.seen_voice=False
        self.mouth.last=None

    def project(self,body_bgr,model_bgr,paired_pcm):
        pcm=np.frombuffer(paired_pcm,dtype='<i2').astype(np.float32)
        rms=float(np.sqrt(np.mean(pcm*pcm))) if len(pcm) else 0
        if rms>=110:self.quiet=0;self.seen_voice=True
        else:self.quiet+=1
        body=body_bgr[...,::-1].copy()
        center,score=self.tracker.locate(body)
        if score<.4:
            raise AdmissionError('SAME_MODE_MOUTH_TRACKING_UNCERTAIN')
        result,record=self.mouth.project(body,model_bgr[...,::-1].copy(),center,self.tracker.ratio,
                                        not self.seen_voice or self.quiet>=6)
        record.update(tracker_score=score,center=list(map(float,center)),paired_pcm_rms=rms,
                      actual_flashhead_source=True,amplitude_driven_aperture=False)
        return result[...,::-1].copy(),record
