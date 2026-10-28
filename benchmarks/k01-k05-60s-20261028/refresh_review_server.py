"""Reload this experiment's static viewer only; never touches MCP/model jobs."""
import json,subprocess,sys,time,psutil
from pathlib import Path
W=Path(__file__).resolve().parent;O=W.parent.parent/'outputs/lipsync-k01-k05-60s-20261028'
target=str(W/'serve_remote_review.py');stopped=[]
for process in psutil.process_iter(['pid','cmdline']):
 try:
  args=process.info['cmdline'] or []
  if target not in args or '--serve' not in args:continue
  process.terminate();process.wait(timeout=8);stopped.append(process.pid)
 except (psutil.NoSuchProcess,psutil.AccessDenied):continue
subprocess.run([sys.executable,'-X','utf8','-B',target],cwd=str(W.parent.parent),check=True,creationflags=subprocess.CREATE_NO_WINDOW)
records=[]
for name in ['K03/progress.json','K03/training-history.json']:
 p=O/name;stat=p.stat();records.append({'path':name,'windows_attributes':getattr(stat,'st_file_attributes',None),'bytes':stat.st_size,'modified_at':stat.st_mtime})
result={'ok':True,'stopped_only_matching_review_server_pids':stopped,'observed_at':time.time(),'files':records,'no_mcp_or_gpu_job_changed':True}
(O/'viewer-reload.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
