"""One original batch under a fixed allocator budget; never saves trained weights."""
from bench_common import *
import psutil,random
def main():
    native12='--native12' in sys.argv;budget=12288 if native12 else 4096;cpu_saved='--cpu-saved' in sys.argv
    proof='K03/native-fit-probe.json' if native12 else 'K03/gpu-fit-probe.json'
    previous=O/proof
    if previous.exists():
        saved=json.loads(previous.read_text(encoding='utf-8'));save('attempts/feather-memory-probe-'+str(saved.get('allocator_limit_mib','unknown'))+'-'+str(int(time.time()))+'.json',saved)
    while True:
        free=float(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],creationflags=subprocess.CREATE_NO_WINDOW).decode().splitlines()[0])
        cpu=psutil.cpu_percent(.5);ram=psutil.virtual_memory().available/2**30
        if free>=(20000 if native12 else 8500) and ram>=(12 if cpu_saved or native12 else 6) and cpu<80:break
        save(proof,{'ok':False,'status':'waiting for spare resources','gpu_free_mib':free,'ram_free_gib':ram,'system_cpu_percent':cpu})
        if native12:return  # Do not hold the task GPU lock while a larger probe waits.
        time.sleep(20)
    import torch
    mon=Monitor('K03-fit-probe');start=time.perf_counter();result={'ok':False,'probe_only':True,'not_a_60_second_test':True,'allocator_limit_mib':budget,'original_batchsize':16,'precision':'FP32','loss_weights':'original defaults','saved_activation_storage':'CPU' if cpu_saved else 'CUDA','steps':0}
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.backends.cudnn.benchmark=False
        torch.cuda.set_per_process_memory_fraction(budget*2**20/torch.cuda.get_device_properties(0).total_memory)
        random.seed(20261028);np.random.seed(20261028);torch.manual_seed(20261028);torch.cuda.manual_seed_all(20261028)
        src=R/'src/lipsync-benchmark/feather';sys.path.insert(0,str(src));os.chdir(src);import train
        original=train.train_one_epoch
        def one_batch(net,loader,*args,**kwargs):
            batch=next(iter(loader));torch.cuda.reset_peak_memory_stats();tick=time.perf_counter()
            if cpu_saved:
                with torch.autograd.graph.save_on_cpu(pin_memory=False):out=original(net,[batch],*args,**kwargs)
            else:out=original(net,[batch],*args,**kwargs)
            torch.cuda.synchronize();result.update(steps=1,step_seconds=time.perf_counter()-tick,torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,torch_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20);return out
        train.train_one_epoch=one_batch;train.save_checkpoint=lambda *a,**k:None
        sys.argv=['train.py','--dataset_dir',str(O/'training'),'--save_dir',str(W/'memory-probe-no-checkpoints'),'--model','feathertalk','--epochs','1','--batchsize','16','--num_workers','0','--save_every','1']
        train.main();result['ok']=True
    except Exception:result['error']=traceback.format_exc()
    finally:result.update(wall_seconds=time.perf_counter()-start,**mon.finish());save(proof,result);print(json.dumps(result),flush=True)
if __name__=='__main__':main()
