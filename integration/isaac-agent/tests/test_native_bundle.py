"""The full in-memory controller must compile on the game's Lua version."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools/python-libs')]
from lupa.lua53 import LuaRuntime
from build_native_controller import build


class NativeBundleTests(unittest.TestCase):
    def test_complete_native_controller_compiles_on_lua53(self):
        path=build()
        source=path.read_text(encoding='utf8')
        valid,error=LuaRuntime(unpack_returned_tuples=True).eval('function(source) local fn,err=load(source); return fn~=nil,err end')(source)
        self.assertTrue(valid,error)


if __name__=='__main__': unittest.main()
