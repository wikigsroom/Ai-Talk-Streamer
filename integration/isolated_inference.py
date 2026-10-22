"""Keep GPU dispatch separate from WebRTC, AV encoding and browser connections."""
from pathlib import Path
import atexit,json,os,secrets,subprocess,threading,time
from multiprocessing.connection import Client
import numpy as np
ROOT=Path(__file__).resolve().parents[3]

class GPUClient:
    def __init__(self):
        self.lock=threading.Lock();self.connection=None;self.token=secrets.token_hex(32)
        self.run_id=secrets.token_hex(12)
        env=os.environ.copy();env.update(AVATAR_GPU_WORKER_CHILD='1',AVATAR_GPU_WORKER_AUTH=self.token,AVATAR_GPU_WORKER_RUN=self.run_id,AVATAR_GPU_PARENT=str(os.getpid()))
        stdout=(ROOT/'logs/gpu-worker.stdout.log').open('a',encoding='utf-8');stderr=(ROOT/'logs/gpu-worker.stderr.log').open('a',encoding='utf-8')
        self.process=subprocess.Popen([str(ROOT/'runtime/livetalking/Scripts/python.exe'),'-X','utf8','-B',str(ROOT/'scripts/gpu_worker.py')],cwd=ROOT/'src/LiveTalking',env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
        state=ROOT/'.setup/gpu-worker.json'
        for attempt in range(600):
            if self.process.poll() is not None:raise RuntimeError('GPU worker exited; inspect logs/gpu-worker.stderr.log')
            try:
                info=json.loads(state.read_text(encoding='utf-8'))
                if info.get('run_id')==self.run_id and info.get('ready'):
                    self.connection=Client(info['pipe'],family='AF_PIPE',authkey=bytes.fromhex(self.token));break
            except (OSError,ValueError):pass
            time.sleep(.2)
        else:self.process.terminate();raise RuntimeError('GPU worker did not become ready within 120 seconds')
        atexit.register(self.close)
    def call(self,operation,**kwargs):
        with self.lock:
            self.connection.send({'operation':operation,**kwargs})
            if not self.connection.poll(45):raise RuntimeError('GPU operation timed out; inspect gpu-worker logs')
            result=self.connection.recv()
            if not result.get('ok'):raise RuntimeError(result.get('error','GPU inference failed'))
            return result.get('value')
    def close(self):
        if self.connection:
            try:self.connection.close()
            except OSError:pass
            self.connection=None

class AudioProxy:
    is_isolated=True
    def __init__(self,client):self.client=client;self.silent=np.zeros((128,5,384),dtype=np.float16)
    def audio2feat(self,wave):
        if not np.any(wave):return self.silent
        return self.client.call('features',wave=np.asarray(wave,dtype=np.float32))

_client=None
def load_proxy():
    global _client
    if _client is None:_client=GPUClient()
    return None,None,None,None,AudioProxy(_client)
