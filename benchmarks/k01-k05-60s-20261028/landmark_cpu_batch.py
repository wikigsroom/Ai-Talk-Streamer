"""Same SCRFD/PFLD weights and geometry, CPU ONNX detection + batched PFLD."""
from bench_common import *
def configure(detector,src):
    import onnxruntime as ort
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(src/'scrfd_2.5g_kps.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    class Net:
        def setInput(self,x):self.x=x
        def getUnconnectedOutLayersNames(self):return [x.name for x in session.get_outputs()]
        def forward(self,names):return session.run(list(names),{session.get_inputs()[0].name:self.x})
    detector.det_net.net=Net();cv2.setNumThreads(2)
def infer(detector,paths):
    import torch
    from get_landmark import face_det
    inputs=[];geometry=[]
    for path in paths:
        image=cv2.imread(str(path))
        if image is None:raise RuntimeError('Unreadable teacher frame '+str(path))
        cropped,boxes,_,_=face_det(image,detector.det_net)
        if not cropped:raise RuntimeError('Face not detected in '+str(path))
        patch=cropped[0];h,w=patch.shape[:2];x,y=boxes[0][:2]
        inputs.append((cv2.resize(patch,(192,192)).astype(np.float32)/255.).transpose(2,0,1));geometry.append((w,h,x,y))
    with torch.inference_mode():values=detector.pfld_backbone(torch.from_numpy(np.stack(inputs))).numpy()
    values=(values+detector.mean_face).reshape(len(inputs),-1,2);out=[]
    for points,(w,h,x,y) in zip(values,geometry):
        points=points.copy();points[:,0]*=w;points[:,1]*=h;out.append(points.astype(np.int32)+np.array([x,y]))
    return out
