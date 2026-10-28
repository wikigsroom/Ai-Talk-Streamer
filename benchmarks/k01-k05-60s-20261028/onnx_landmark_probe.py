from bench_common import *
def main():
 code="""import sys,time,json,torch,cv2,numpy as np,onnxruntime as ort
from pathlib import Path
r=Path('C:/dev/虚拟数字人直播');w=r/'operations/k01-k05-60s-20261028';sys.path.insert(0,str(w));import bench_common
src=r/'src/lipsync-benchmark/feather/data_utils';sys.path.insert(0,str(src));import os;os.chdir(src)
torch.set_num_threads(2);torch.cuda.is_available=lambda:False;native=torch.load
torch.load=lambda *a,**k:native(*a,**dict(k,weights_only=False));cv2.setNumThreads(2)
from get_landmark import Landmark
detector=Landmark()
options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
session=ort.InferenceSession(str(src/'scrfd_2.5g_kps.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
class Net:
 def setInput(self,x):self.x=x
 def getUnconnectedOutLayersNames(self):return [o.name for o in session.get_outputs()]
 def forward(self,names):return session.run(list(names),{session.get_inputs()[0].name:self.x})
detector.det_net.net=Net();rows=[];diff=[]
for i in range(10):
 t=time.perf_counter()
 with torch.inference_mode():points,x,y=detector.detect(str(bench_common.O/'training/full_body_img'/f'{i}.jpg'))
 rows.append(time.perf_counter()-t);old=bench_common.O/'training/landmarks'/f'{i}.lms'
 if old.exists():diff.append(float(np.max(np.abs(np.loadtxt(old)-(points+np.array([x,y]))))))
with torch.inference_mode():
 x=torch.zeros(16,3,192,192);t=time.perf_counter();y=detector.pfld_backbone(x);batch_seconds=time.perf_counter()-t
bench_common.save('onnx-landmark-probe.json',{'threads':2,'seconds_per_frame':rows,'mean_after_first':float(np.mean(rows[1:])),'existing_landmark_max_difference':diff,'cuda_used':False,'pfld_batch16_seconds':batch_seconds,'pfld_batch_output_shape':list(y.shape)})
"""
 env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=''
 subprocess.run([str(R/'runtime/lipsync-benchmark/feather/Scripts/python.exe'),'-X','utf8','-c',code],env=env,check=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
if __name__=='__main__':main()
