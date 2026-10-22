from pathlib import Path
import os,subprocess,sys,json
ROOT=Path(__file__).resolve().parents[1]
env=os.environ.copy();env.update(UV_CACHE_DIR=str(ROOT/'cache/uv'),TEMP=str(ROOT/'cache/tmp'),TMP=str(ROOT/'cache/tmp'))
args=[str(ROOT/'tools/uv/uv.exe'),'pip','install','--python',str(ROOT/'runtime/livetalking/Scripts/python.exe'),'py-spy==0.4.1']
proc=subprocess.run(args,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace');print(proc.stdout,flush=True)
if proc.returncode:raise SystemExit(proc.returncode)
code="import psutil;from pathlib import Path;root=Path.cwd();print(next(p.pid for p in psutil.process_iter(['cmdline']) if str(root/'src/LiveTalking/app.py') in (p.info['cmdline'] or []) and p.pid!=__import__('os').getpid()))"
probe=subprocess.check_output([str(ROOT/'runtime/livetalking/Scripts/python.exe'),'-X','utf8','-B','-c',code],cwd=ROOT,text=True).strip()
# The native venv parent can wrap the actual CPython worker. Ask Windows for listener PID.
listener=subprocess.check_output(['powershell.exe','-NoProfile','-Command','(Get-NetTCPConnection -State Listen -LocalPort 8010 | Select-Object -First 1).OwningProcess'],text=True).strip()
proc=subprocess.run([str(ROOT/'runtime/livetalking/Scripts/py-spy.exe'),'dump','--pid',listener],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
(ROOT/'logs/avatar-thread-dump.log').write_text(proc.stdout,encoding='utf-8');print(proc.stdout,flush=True)
raise SystemExit(proc.returncode)
