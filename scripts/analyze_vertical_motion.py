"""Measure actual source-video blinking and head movement with local landmarks."""
from pathlib import Path
import datetime, json, os, sys
import cv2, dlib, face_recognition_models, numpy as np
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / 'src/LiveTalking')
predictor = dlib.shape_predictor(os.path.relpath(face_recognition_models.pose_predictor_model_location()))
detector = dlib.get_frontal_face_detector()
out = ROOT / 'outputs/vertical/review'; out.mkdir(parents=True, exist_ok=True)

def ear(points):
    return float((np.linalg.norm(points[1]-points[5])+np.linalg.norm(points[2]-points[4]))/(2*np.linalg.norm(points[0]-points[3])))

results = []
for name in sys.argv[1:] or ['idle_a', 'idle_b']:
    video = ROOT / 'outputs/vertical/source' / (name + '.mp4')
    capture = cv2.VideoCapture(os.path.relpath(video))
    fps = capture.get(cv2.CAP_PROP_FPS); count = 0; rows = []; rectangle = None
    while True:
        ret, frame = capture.read()
        if not ret: break
        small = cv2.resize(frame, (368, 656))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        if rectangle is None:
            faces = detector(rgb, 1)
            if len(faces) != 1: raise RuntimeError('Expected one clear face: '+name)
            rectangle = faces[0]
        shape = predictor(rgb, rectangle)
        points = np.asarray([(shape.part(i).x, shape.part(i).y) for i in range(68)], dtype=np.float32)
        rows.append({'frame':count,'seconds':count/fps,'eye_ratio':(ear(points[36:42])+ear(points[42:48]))/2,'nose_xy':points[30].tolist(),'mouth_xy':points[48:68].mean(axis=0).tolist()})
        if count in (0,36,72,96,132,168,191): cv2.imwrite(os.path.relpath(out/f'{name}-{count:03d}.png'),frame)
        count += 1
    capture.release()
    if count < 150: raise RuntimeError('Incomplete source video: '+name)
    eyes = np.asarray([row['eye_ratio'] for row in rows]); nose = np.asarray([row['nose_xy'] for row in rows])
    threshold = min(.20,float(np.median(eyes))*.7)
    closed = eyes < threshold
    blink_onsets = np.where(closed & ~np.r_[False,closed[:-1]])[0]
    result = {'name':name,'frames':count,'fps':fps,'duration':count/fps,'eye_ratio_min':float(eyes.min()),'eye_ratio_median':float(np.median(eyes)),'closed_eye_threshold':threshold,'blink_onsets_seconds':(blink_onsets/fps).tolist(),'nose_range_at_368x656':np.ptp(nose,axis=0).tolist(),'rows':rows}
    (out/(name+'.motion.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    results.append({key:value for key,value in result.items() if key!='rows'})
    print(json.dumps(results[-1]),flush=True)
(out/'motion-summary.json').write_text(json.dumps({'at':datetime.datetime.now().astimezone().isoformat(),'sources':results,'limitations':'Landmark measurements confirm movement; visual review remains necessary.'},ensure_ascii=False,indent=2),encoding='utf-8')
