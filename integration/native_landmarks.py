"""CPU dlib landmarks using the native Windows wheel, without a dlib source build."""
import os
import dlib
import face_recognition_models

_detector = dlib.get_frontal_face_detector()
# A relative ASCII path also works with dlib builds whose C++ file loader cannot
# open a Unicode absolute path. The launcher sets cwd to the LiveTalking repo.
_model = os.path.relpath(face_recognition_models.pose_predictor_model_location())
_predictor = dlib.shape_predictor(_model)

def face_landmarks(image):
    regions = {'chin': (0,17), 'left_eyebrow': (17,22), 'right_eyebrow': (22,27),
               'nose_bridge': (27,31), 'nose_tip': (31,36),
               'left_eye': (36,42), 'right_eye': (42,48)}
    result = []
    for rectangle in _detector(image, 1):
        shape = _predictor(image, rectangle)
        points = [(shape.part(i).x, shape.part(i).y) for i in range(68)]
        landmarks = {key: points[start:end] for key,(start,end) in regions.items()}
        landmarks['top_lip'] = [points[i] for i in [48,49,50,51,52,53,54,64,63,62,61,60]]
        landmarks['bottom_lip'] = [points[i] for i in [54,55,56,57,58,59,48,60,67,66,65,64]]
        result.append(landmarks)
    return result
