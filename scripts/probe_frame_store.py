"""Verify randomized decode, negative indices and bounded cache on real avatar data."""
from pathlib import Path
import json,os,sys,cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];repo=ROOT/'src/LiveTalking'
os.chdir(repo);sys.path.insert(0,str(repo))
from server.frame_store import FrameStore
paths=sorted((Path('data/avatars/student_dorm_vertical_v2/full_imgs')).glob('*.png'))
store=FrameStore([str(p) for p in paths],cache_size=8)
for index in [0,60,199,399,150,2,55,75,33,0,-1,300]:
 expected=cv2.imread(str(paths[index]));actual=store[index]
 if not np.array_equal(actual,expected):raise RuntimeError('Decoded frame differs from PNG source')
 if len(store.cache)>8:raise RuntimeError('Image cache exceeded its limit')
for index in [-len(paths)-1,len(paths)]:
 try:store[index]
 except IndexError:pass
 else:raise RuntimeError('Out-of-range access was accepted')
result={'ok':True,'frames':len(store),'cached_frames':len(store.cache),'cache_limit':8,'decoded_pixels_match_sources':True}
(ROOT/'.setup/frame-store-probe.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
