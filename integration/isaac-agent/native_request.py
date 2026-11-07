"""Send a local request to the single Isaac bridge, with a bounded response wait."""
import argparse
import json
from pathlib import Path
import time
import uuid
import msvcrt
from native_ipc import atomic_json

ROOT = Path(__file__).resolve().parent

def request(source=None, *, op='evaluate', timeout=20, name=None, hwnd=None):
    deadline=time.monotonic()+timeout
    with (ROOT/'native-request.lock').open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0: lock.write(b'0'); lock.flush()
        while True:
            lock.seek(0)
            try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1); break
            except OSError:
                if time.monotonic()>=deadline: raise TimeoutError('Native request lock timed out')
                time.sleep(.02)
        try: return _request(source,op=op,timeout=max(.1,deadline-time.monotonic()),name=name,hwnd=hwnd)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def _request(source=None, *, op='evaluate', timeout=20, name=None, hwnd=None):
    identity = uuid.uuid4().hex
    payload = {'id':identity,'op':op,'source':source}
    if op=='key': payload.update(name=name,hwnd=hwnd)
    target = ROOT/'native-request.json'
    atomic_json(target,payload,timeout=min(3,timeout))
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        try:
            response = json.loads((ROOT/'native-response.json').read_text(encoding='utf-8'))
            if response.get('id') == identity:
                if not response['ok']: raise RuntimeError(response['error'])
                return response['result']
        # Windows may briefly deny opening the reply while its atomic rename
        # completes. Keep the same request identity and bounded deadline.
        except (FileNotFoundError,PermissionError,json.JSONDecodeError): pass
        time.sleep(.05)
    raise TimeoutError('Native bridge response timed out')

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--status',action='store_true')
    parser.add_argument('--source')
    parser.add_argument('--file')
    args=parser.parse_args()
    source=Path(args.file).read_text(encoding='utf-8') if args.file else args.source
    print(json.dumps(request(source,op='status' if args.status else 'evaluate'),ensure_ascii=True))
