"""Shared material controls used for both the visual comparison and live avatar."""
import cv2
import numpy as np

def native_detections(batch, landmark_function):
    """Reuse checked landmarks instead of running a second face detector."""
    boxes=[]
    for frame in batch:
        faces=landmark_function(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        if len(faces)!=1:raise RuntimeError('Expected exactly one stable face in source material')
        points=np.asarray(faces[0]['chin']+faces[0]['left_eyebrow']+faces[0]['right_eyebrow'])
        boxes.append((int(points[:,0].min()),int(points[:,1].min()),int(points[:,0].max()),int(points[:,1].max())))
    return boxes

def compact_mask(mask, crop_box, face_box, landmarks):
    """Limit replacement to the mouth/chin while retaining original cheek detail."""
    lips = np.asarray(landmarks['top_lip'] + landmarks['bottom_lip'], dtype=np.float32)
    center = lips.mean(axis=0)
    x1, y1, x2, y2 = face_box
    face_width, face_height = x2-x1, y2-y1
    cx = float(center[0])-crop_box[0]
    cy = float(center[1])-crop_box[1]+face_height*.045
    rx = max(float(np.ptp(lips[:,0]))*.88, face_width*.28)
    ry = max(float(np.ptp(lips[:,1]))*1.9, face_height*.18)
    shape = np.zeros(mask.shape[:2], dtype=np.uint8)
    cv2.ellipse(shape,(round(cx),round(cy)),(round(rx),round(ry)),0,0,360,255,-1)
    kernel=max(5,int(face_width*.10)//2*2+1)
    shape=cv2.GaussianBlur(shape,(kernel,kernel),0)
    return np.minimum(mask,shape)
