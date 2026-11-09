"""Nested diagnostic spans must stay bounded and not double-count update time."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class RuntimeProfileTests(unittest.TestCase):
    def test_nested_measurements_do_not_inflate_totals_and_old_rows_expire(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('clock=0;Isaac={GetTime=function()return clock end}')
        profile=lua.execute((ROOT/'mods/IsaacJev/runtime_profile.lua').read_text('utf8'))['new']()
        for i in range(130):
            profile['begin'](profile)
            profile['detail'](profile,'forecast',3)
            profile['detail'](profile,'forecast',2)
            lua.globals().clock+=10 if i>=10 else 500
            profile['mark'](profile,'movement')
            profile['finish'](profile)
        result=profile['snapshot'](profile)
        self.assertEqual(result['updates'],130)
        self.assertEqual(result['window_updates'],120)
        self.assertEqual(result['update_mean_ms'],10)
        self.assertEqual(result['update_p95_ms'],10)
        self.assertEqual(result['details']['forecast']['mean_ms'],5)
        profile['detail'](profile,'forecast',1000)
        self.assertEqual(profile['snapshot'](profile)['details']['forecast']['mean_ms'],5)


if __name__=='__main__':unittest.main()
