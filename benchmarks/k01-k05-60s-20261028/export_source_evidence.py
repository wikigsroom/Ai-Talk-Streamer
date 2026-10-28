"""Export just this benchmark's source frames and task logs; CPU and read-only inputs."""
from bench_common import *
import shutil,pickle
def main():
 inp=manifest();paths=sorted((AV/'full_imgs').glob('*.png'),key=lambda p:int(p.stem));dest=O/'inputs/source-evidence';dest.mkdir(parents=True,exist_ok=True)
 frames=sorted(set(range(0,N,25))|{50,275,550,850,1150,1400})
 for frame in frames:
  target=dest/f'{frame:04d}.png'
  if not target.exists():shutil.copy2(paths[inp['test_frame_ids'][frame]],target)
 shutil.copy2(AV/'coords.pkl',dest/'coords.pkl')
 coords=pickle.loads((AV/'coords.pkl').read_bytes())
 save('inputs/source-evidence/frame-geometry.json',{'source':'existing avatar coords.pkl; exported as plain data','frames':[{'timeline_frame':frame,'source_frame':inp['test_frame_ids'][frame],'source_png':f'{frame:04d}.png','bbox':[int(v) for v in coords[inp['test_frame_ids'][frame]]]} for frame in frames]})
 logs=O/'diagnostics';logs.mkdir(exist_ok=True)
 for p in W.glob('*.log'):
  if p.stat().st_size<10*2**20:shutil.copy2(p,logs/p.name)
 save('inputs/source-evidence/export.json',{'ok':True,'original_frames':len(list(dest.glob('*.png'))),'selected_test_timeline_frames':True,'source_geometry':'Existing MuseTalk coords.pkl; binary private task artifact, not executed.'})
if __name__=='__main__':main()
