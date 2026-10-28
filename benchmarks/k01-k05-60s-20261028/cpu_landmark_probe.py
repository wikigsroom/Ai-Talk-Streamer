from bench_common import *
import subprocess
def main():
    python=R/'runtime/lipsync-benchmark/feather/Scripts/python.exe'
    code="""import sys,time,json,torch,cv2,numpy as np
from pathlib import Path
r=Path('C:/dev/虚拟数字人直播');w=r/'operations/k01-k05-60s-20261028';sys.path.insert(0,str(w));import bench_common
src=r/'src/lipsync-benchmark/feather/data_utils';sys.path.insert(0,str(src));import os;os.chdir(src)
torch.set_num_threads(2);torch.cuda.is_available=lambda:False;native=torch.load
torch.load=lambda *a,**k:native(*a,**dict(k,weights_only=False))
cv2.setNumThreads(2)
from get_landmark import Landmark
detector=Landmark();rows=[];diff=[];profile={'scrfd':[],'pfld':[]}
for obj,attr,key in [(detector.det_net,'detect','scrfd'),(detector.pfld_backbone,'forward','pfld')]:
 fn=getattr(obj,attr)
 def measured(*a,_fn=fn,_key=key,**k):
  tick=time.perf_counter();out=_fn(*a,**k);profile[_key].append(time.perf_counter()-tick);return out
 setattr(obj,attr,measured)
for i in range(10):
 t=time.perf_counter()
 with torch.inference_mode():points,x,y=detector.detect(str(bench_common.O/'training/full_body_img'/f'{i}.jpg'))
 rows.append(time.perf_counter()-t);old=bench_common.O/'training/landmarks'/f'{i}.lms'
 if old.exists():diff.append(float(np.max(np.abs(np.loadtxt(old)-(points+np.array([x,y]))))))
bench_common.save('cpu-landmark-probe.json',{'threads':2,'seconds_per_frame':rows,'mean_after_first':float(np.mean(rows[1:])),'profile':profile,'existing_landmark_max_difference':diff,'cuda_used':False})
"""
    env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=''
    subprocess.run([str(python),'-X','utf8','-c',code],env=env,check=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
if __name__=='__main__':main()
