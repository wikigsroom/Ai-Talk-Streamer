"""Real Windows sharing-denial regression; no model or GPU is loaded."""
import ast,ctypes,hashlib,json,os,sys,threading,time,platform,datetime
import functools,http.server,io,urllib.request,urllib.error
from pathlib import Path

base=Path(__file__).resolve().parent
root=base/'atomic-progress-check';root.mkdir(exist_ok=True)
tree=ast.parse((base/'bench_common.py').read_text(encoding='utf-8'))
save_node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='save')
scope={'O':root,'os':os,'threading':threading,'time':time,'json':json,'sys':sys,'_progress_write_warning':False}
exec(compile(ast.Module(body=[save_node],type_ignores=[]),'<actual-benchmark-save>','exec'),scope)
save=scope['save'];checks={}
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
kernel.CreateFileW.restype=ctypes.c_void_p;kernel.CloseHandle.argtypes=[ctypes.c_void_p]
def lock_file(path):
 handle=kernel.CreateFileW(str(path),0x80000000,1,None,3,128,None)
 if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
 return handle

save('progress.json',{'step':1});handle=lock_file(root/'progress.json')
try:
 start=time.perf_counter();accepted=save('progress.json',{'step':2});elapsed=time.perf_counter()-start
 checks['locked_telemetry_returns_without_aborting']=accepted is False and elapsed<1
 checks['previous_complete_snapshot_retained']=json.loads((root/'progress.json').read_text())=={'step':1}
 fallback=root/f'progress-fallback-{os.getpid()}.json'
 checks['fallback_snapshot_retained']=json.loads(fallback.read_text())=={'step':2}
finally:kernel.CloseHandle(handle)
checks['unlocked_telemetry_recovers']=save('progress.json',{'step':3}) is True and json.loads((root/'progress.json').read_text())=={'step':3}
save('result.json',{'ok':False});handle=lock_file(root/'result.json')
timer=threading.Timer(.3,lambda:kernel.CloseHandle(handle));timer.start()
start=time.perf_counter();save('result.json',{'ok':True});strict_elapsed=time.perf_counter()-start;timer.join()
checks['measured_result_waits_for_real_lock_release']=strict_elapsed>=.25 and json.loads((root/'result.json').read_text())=={'ok':True}
checks['no_temporary_files_left']=not list(root.glob('*.tmp'))
from range_http import MediaHandler
arrived=threading.Event();release=threading.Event();read_state={}
class DelayedHandler(MediaHandler):
 def log_message(self,*args):pass
 def copyfile(self,source,output):
  if self.path=='/progress.json':
   read_state['buffered_snapshot']=isinstance(source,io.BytesIO);arrived.set();release.wait(timeout=5)
  return super().copyfile(source,output)
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(DelayedHandler,directory=str(root)))
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
op=urllib.request.build_opener(urllib.request.ProxyHandler({}));url=f'http://127.0.0.1:{server.server_port}'
try:
 with op.open(url+'/progress.json',timeout=6) as response:
  if not arrived.wait(timeout=2):raise RuntimeError('HTTP copy barrier was not entered')
  checks['http_reader_releases_disk_before_slow_transfer']=read_state.get('buffered_snapshot') and save('progress.json',{'step':4}) is True
  release.set();checks['inflight_http_snapshot_is_complete']=json.load(response)=={'step':3}
 payload=bytes(range(100));(root/'range.bin').write_bytes(payload)
 for label,header,expected in [('middle','bytes=10-19',payload[10:20]),('suffix','bytes=-7',payload[-7:])]:
  with op.open(urllib.request.Request(url+'/range.bin',headers={'Range':header}),timeout=3) as response:
   checks['range_'+label]=response.status==206 and response.read()==expected
 try:
  with op.open(urllib.request.Request(url+'/range.bin',headers={'Range':'bytes=100-'}),timeout=3):checks['invalid_range_is_416']=False
 except urllib.error.HTTPError as error:checks['invalid_range_is_416']=error.code==416;error.close()
finally:
 release.set();server.shutdown();server.server_close();thread.join(timeout=2)
result={'ok':all(checks.values()),'checks':checks,'telemetry_seconds':elapsed,'strict_result_seconds':strict_elapsed,'source_sha256':hashlib.sha256((base/'bench_common.py').read_bytes()).hexdigest(),'save_function_ast_sha256':hashlib.sha256(ast.dump(save_node,include_attributes=False).encode()).hexdigest(),'execution_host':platform.node(),'execution_platform':platform.platform(),'observed_at':datetime.datetime.now().astimezone().isoformat(),'scope':'Local B-device regression, separate from A4090 render measurements.','method':'Real Win32 FILE_SHARE_READ-only handle; executes actual save() extracted without loading CUDA.'}
(base/'atomic-progress-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result));assert result['ok']
