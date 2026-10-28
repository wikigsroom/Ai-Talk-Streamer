"""Hidden native launcher: streams logs to files and records uncaught failures."""
import sys,runpy,traceback,os,subprocess,time,msvcrt
from pathlib import Path
W=Path(__file__).resolve().parent
target=sys.argv[1]
allowed={'prepare_audio.py','render_muse.py','render_wav2lip.py','render_feather.py','train_feather.py','render_latent.py','prepare_training.py','validate_outputs.py','build_report.py','preprocess_assets.py','run_suite.py','serve_remote_review.py','export_source_evidence.py'}
allowed|={'refresh_suite_waiter.py','prepare_environments.py','preflight.py','prepare_vgg.py'}
allowed|={'link_shared_runtime.py'}
allowed|={'prepare_offline_environments.py'}
allowed|={'inspect_benchmark_assets.py'}
allowed|={'cpu_landmark_probe.py'}
allowed|={'onnx_landmark_probe.py'}
allowed|={'reconfigure_preprocessing.py'}
allowed|={'plot_all.py','make_final_assets.py'}
allowed|={'probe_feather_memory.py'}
allowed|={'make_delivery_manifest.py'}
allowed|={'refresh_probe_waiter.py'}
allowed|={'render_latent_bounded.py'}
allowed|={'serialize_probe_jobs.py'}
allowed|={'audit_training_data.py'}
allowed|={'prepare_wav2lip_source.py'}
allowed|={'archive_failed_training.py'}
allowed|={'refresh_review_server.py','verify_atomic_progress.py'}
allowed|={'publish_review.py'}
if target not in allowed:raise RuntimeError('Unknown benchmark module')
args=sys.argv[2:];tag=target+('-'+'-'.join(args) if args else '')
if any('/' in arg or '\\' in arg or '..' in arg for arg in args):raise ValueError('Only simple benchmark arguments allowed')
if target in {'render_latent.py','preprocess_assets.py','train_feather.py','render_feather.py','plot_all.py','probe_feather_memory.py','render_latent_bounded.py','audit_training_data.py'}:
    name='latent' if target in {'render_latent.py','plot_all.py','render_latent_bounded.py'} else 'feather'
    isolated=W.parent.parent/f'runtime/lipsync-benchmark/{name}/Scripts/pythonw.exe'
    if not isolated.exists():raise RuntimeError(name+' isolated environment is not ready')
    if Path(sys.executable).resolve()!=isolated.resolve():
        sys.exit(subprocess.call([str(isolated),'-X','utf8','-B',str(__file__),target,*args],cwd=str(W.parent.parent),creationflags=subprocess.CREATE_NO_WINDOW))
sys.stdout=open(W/(tag+'.stdout.log'),'w',encoding='utf-8',buffering=1)
sys.stderr=open(W/(tag+'.stderr.log'),'w',encoding='utf-8',buffering=1)
sys.argv=[str(W/target),*args];sys.path.insert(0,str(W))
gpu_lock=None
if target in {'render_muse.py','render_wav2lip.py','render_feather.py','train_feather.py','render_latent.py','render_latent_bounded.py','probe_feather_memory.py'}:
    gpu_lock=(W/'benchmark-gpu.lock').open('a+b');gpu_lock.seek(0);gpu_lock.write(b'0');gpu_lock.flush();gpu_lock.seek(0)
    while True:
        try:msvcrt.locking(gpu_lock.fileno(),msvcrt.LK_NBLCK,1);break
        except OSError:time.sleep(5)
try:runpy.run_path(str(W/target),run_name='__main__')
except BaseException:traceback.print_exc();raise
finally:
    if gpu_lock is not None:gpu_lock.seek(0);msvcrt.locking(gpu_lock.fileno(),msvcrt.LK_UNLCK,1);gpu_lock.close()
