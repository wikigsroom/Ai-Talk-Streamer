"""Run against the already started loopback worker; never attaches to the game."""
from pathlib import Path
import argparse
import importlib.util
import json
import math
import random
import socket
import statistics
import struct
import time

spec=importlib.util.spec_from_file_location('geometry',Path(__file__).resolve().parents[1]/'isaac_gpu_worker.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def validate(port=9536):
    rng=random.Random(20261110);results=[];max_error=0
    with socket.create_connection(('127.0.0.1',port),timeout=2) as client:
        client.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        sequence=0
        for count in (1,12,44,256):
            forecasts=[[[100+i*t*.15,150-i*t*.2] for t in range(11)] for i in range(9)]
            tracks=[]
            for index in range(count):
                x,y,vx,vy=[rng.uniform(-500,500),rng.uniform(-500,500),rng.uniform(-20,20),rng.uniform(-20,20)]
                tracks.append(([[x+t*vx,y+t*vy] for t in range(11)],index%11+1,index%3==0))
            values=[v for path in forecasts for xy in path for v in xy]
            values += [v for path,first,initial in tracks for v in [*[n for xy in path for n in xy],first,int(initial)]]
            body=struct.pack('<'+'d'*len(values),*values)
            expected=module.reference_distances(forecasts,tracks)
            times=[]
            for _ in range(50):
                sequence+=1
                header=module.HEADER.pack(b'IGP1',sequence,300,4126411572,1,2,count,10)
                started=time.perf_counter();client.sendall(header+body)
                reply=module.receive_exact(client,32+9*count*8)
                times.append((time.perf_counter()-started)*1000)
                assert reply[:32]==b'IGR1'+header[4:]
                actual=struct.unpack('<'+'d'*(9*count),reply[32:])
                for index,value in enumerate(actual):
                    reference=expected[index//count][index%count]
                    assert value==reference or abs(value-reference)<1e-8,(value,reference)
                    if math.isfinite(value):max_error=max(max_error,abs(value-reference))
            times.sort()
            results.append({'tracks':count,'requests':len(times),'persistent_tcp_roundtrip_median_ms':statistics.median(times),
                'persistent_tcp_roundtrip_p95_ms':times[math.ceil(len(times)*.95)-1],'max_ms':max(times)})
    return {'protocol_and_scalar_oracle_passed':True,'fp64_max_absolute_error':max_error,'measurements':results,
        'scope':'synthetic bounded loopback batches; excludes Lua extraction and actual game callback',
        'real_game_and_joint_recording_still_required':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=9536);args=parser.parse_args()
    print(json.dumps(validate(args.port),ensure_ascii=False))
