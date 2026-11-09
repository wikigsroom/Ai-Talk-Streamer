import importlib.util
from pathlib import Path
import struct
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/python-libs'))
from lupa.lua53 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('geometry_worker', ROOT/'isaac_gpu_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class GeometryContractTests(unittest.TestCase):
    def test_crossing_between_samples_and_initial_immunity(self):
        forecasts = [[[0., 0.]]*11 for _ in range(9)]
        crossing = [[-10., 0.], [10., 0.]] + [[30., 0.]]*9
        self.assertEqual(worker.reference_distances(forecasts, [(crossing, 1, True)])[0][0], 0)
        self.assertEqual(worker.reference_distances(forecasts, [(crossing, 2, False)])[0][0], 10)
        self.assertEqual(worker.reference_distances(forecasts, [(crossing, 11, False)])[0][0], float('inf'))

    def test_zero_length_and_first_position_are_retained(self):
        forecasts = [[[0., 0.]]*11 for _ in range(9)]
        self.assertEqual(worker.reference_distances(forecasts, [([[3., 4.]]*11, 1, True)])[8][0], 5)

    def test_protocol_count_boundaries_and_identity_are_explicit(self):
        header = worker.HEADER.pack(b'IGP1', 19, 300, 4126411572, -1, 2, 256, 10)
        self.assertEqual(len(header), 32)
        self.assertEqual(worker.unpack_header(header), (19, 300, 4126411572, -1, 2, 256))
        for count in (0, 257, 2**32-1):
            with self.assertRaises(ValueError):
                worker.unpack_header(worker.HEADER.pack(b'IGP1', 19, 300, 3, 1, 2, count, 10))
        with self.assertRaises(ValueError): worker.unpack_header(b'BAD1'+header[4:])


class LuaClientFailureTests(unittest.TestCase):
    def client(self, mode):
        lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
        module = lua.execute((ROOT/'mods/IsaacJev/gpu_geometry.lua').read_bytes())
        factory = lua.execute(b'''
            return function(module,mode)
                local now,closed,sent=0,false,nil
                local client={}
                function client:settimeout(_) return 1 end
                function client:connect(_,_) return 1 end
                function client:setoption(_,_) return 1 end
                function client:close() closed=true end
                function client:send(body) sent=body;return #body end
                function client:receive(size)
                    if mode=='disconnect' then return nil,'closed' end
                    if mode=='deadline' then now=.02 end
                    local header=sent:sub(1,32)
                    if mode=='stale' then header=header:sub(1,4)..string.pack('<I4',999)..header:sub(9) end
                    local value=mode=='nan' and 0/0 or 5
                    return 'IGR1'..header:sub(5)..string.rep(string.pack('<d',value),9)
                end
                local socket={gettime=function() return now end,tcp=function() return client end}
                local item=module.new(socket,{enabled=true,deadline_ms=8})
                local forecasts,point={}, {X=0,Y=0}
                for i=1,9 do forecasts[i]={};for t=0,10 do forecasts[i][t]=point end end
                local path={};for t=0,10 do path[t]={X=3,Y=4} end
                local result=item:distances({frame=9,seed=4126411572,room=1,stage=2},forecasts,
                    {{path=path,first=1,initial=true}})
                return result,item:snapshot(),closed,item:available()
            end
        ''')
        return factory(module, mode.encode())

    def test_current_result_accepted(self):
        result, status, closed, available = self.client('ok')
        self.assertEqual(result[1][1], 5)
        self.assertEqual(status[b'successes'], 1)
        self.assertFalse(closed)
        self.assertTrue(available)

    def test_stale_nan_timeout_and_disconnect_close_and_cool_down(self):
        for mode in ('stale', 'nan', 'deadline', 'disconnect'):
            with self.subTest(mode=mode):
                result, status, closed, available = self.client(mode)
                self.assertIsNone(result)
                self.assertEqual(status[b'fallbacks'], 1)
                self.assertTrue(closed)
                self.assertFalse(available)


if __name__ == '__main__': unittest.main()
