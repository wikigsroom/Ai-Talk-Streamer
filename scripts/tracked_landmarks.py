"""Detect periodically at half size; fit every frame at native image resolution."""
import cv2

class TrackedLandmarks:
    def __init__(self,native):self.native=native;self.rectangle=None;self.counter=0
    def __call__(self,image):
        native=self.native
        if self.rectangle is None or self.counter%25==0:
            scale=min(1,640/image.shape[0])
            small=cv2.resize(image,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
            found=native._detector(small,0)
            if len(found)!=1:
                if self.rectangle is None:raise RuntimeError('Motion clip must have one detectable face')
            else:
                r=found[0]
                self.rectangle=native.dlib.rectangle(round(r.left()/scale),round(r.top()/scale),round(r.right()/scale),round(r.bottom()/scale))
        self.counter+=1
        shape=native._predictor(image,self.rectangle)
        points=[(shape.part(i).x,shape.part(i).y) for i in range(68)]
        regions={'chin':(0,17),'left_eyebrow':(17,22),'right_eyebrow':(22,27),'nose_bridge':(27,31),'nose_tip':(31,36),'left_eye':(36,42),'right_eye':(42,48)}
        landmarks={key:points[start:end] for key,(start,end) in regions.items()}
        landmarks['top_lip']=[points[i] for i in [48,49,50,51,52,53,54,64,63,62,61,60]]
        landmarks['bottom_lip']=[points[i] for i in [54,55,56,57,58,59,48,60,67,66,65,64]]
        if not all(0<=x<image.shape[1] and 0<=y<image.shape[0] for x,y in points):raise RuntimeError('Landmarks leave the picture')
        return [landmarks]
