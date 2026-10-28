"""Read-only resource snapshot, without unrelated command lines or credentials."""
from bench_common import *
import psutil,urllib.request
def main():
 if '--hardware' in sys.argv:
  import platform,winreg
  with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:cpu_name=winreg.QueryValueEx(key,'ProcessorNameString')[0].strip()
  gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader,nounits'],timeout=10,creationflags=subprocess.CREATE_NO_WINDOW).decode().strip()
  save('benchmark-hardware.json',{'observed_at':time.time(),'gpu_name_driver_vram_mib_csv':gpu,'physical_ram_gib':psutil.virtual_memory().total/2**30,'cpu_name':cpu_name,'physical_cpu_cores':psutil.cpu_count(logical=False),'logical_cpu_threads':psutil.cpu_count(),'platform':platform.platform(),'native_windows':True,'virtualization_used':False,'snapshot_is_not_an_exclusive_resource_window':True,'resource_time_series':'K01-K05/resources.json','model_jobs_run_serially_within_this_task':True,'other_projects_preserved':True,'torch_cpu_threads':{'K01':1,'K02':1,'K03_inference':1,'K03_training':2,'K03_preprocessing':2,'K04':1,'K05':2},'ffmpeg_encoder_threads':4});return
 if '--task-status' in sys.argv:
  rows=[]
  for p in psutil.process_iter(['pid','cmdline','memory_info','create_time','cpu_times']):
   try:
    args=p.info['cmdline'] or []
    if not any(str(W/'bench_launch.py').lower()==s.lower() for s in args):continue
    at=next(i for i,s in enumerate(args) if str(W/'bench_launch.py').lower()==s.lower());tag='-'.join(args[at+1:]);tag=tag.replace('--','')
    row={'pid':p.pid,'task':args[at+1:],'rss_mib':p.info['memory_info'].rss/2**20,'age_seconds':time.time()-p.info['create_time'],'cpu_seconds':sum(p.info['cpu_times'][:2])}
    name=args[at+1]+('-'+'-'.join(args[at+2:]) if args[at+2:] else '')
    for stream in ['stdout','stderr']:
     log=W/(name+'.'+stream+'.log')
     if log.exists():row[stream+'_tail']=log.read_text(encoding='utf-8',errors='replace')[-2400:]
    rows.append(row)
   except (psutil.NoSuchProcess,psutil.AccessDenied):continue
  save('diagnostics/task-status.json',{'timestamp':time.time(),'tasks':rows,'available_ram_gib':psutil.virtual_memory().available/2**30,'gpu':subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],creationflags=subprocess.CREATE_NO_WINDOW).decode().strip()});return
 d={'timestamp':time.time(),'physical_ram_gib':psutil.virtual_memory().total/2**30,'available_ram_gib':psutil.virtual_memory().available/2**30,'cpu_percent':psutil.cpu_percent(.5),'disk_free_gib':psutil.disk_usage(str(R)).free/2**30}
 d['gpu']=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],creationflags=subprocess.CREATE_NO_WINDOW).decode().strip();d['comfy_processes']=[]
 for p in psutil.process_iter(['pid','cmdline','memory_info']):
  try:
   args=p.info['cmdline'] or [];command=' '.join(args).lower()
   if 'comfyui' in command and 'main.py' in command:
    conn=p.net_connections(kind='tcp');d['comfy_processes'].append({'pid':p.pid,'rss_gib':p.info['memory_info'].rss/2**30,'listen_ports':[c.laddr.port for c in conn if c.status=='LISTEN']})
  except (psutil.NoSuchProcess,psutil.AccessDenied):continue
 for folder in [R/'runtime/lipsync-benchmark/feather',R/'runtime/lipsync-benchmark/latent']:
  d[folder.name+'_environment_created']=(folder/'Scripts/python.exe').exists()
 save('preflight.json',d);print(json.dumps(d,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
