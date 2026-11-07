"""Different entrances into one large native room must share one map node."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/python-libs"))
from lupa.lua53 import LuaRuntime


class RoomIdentityTests(unittest.TestCase):
    def test_large_room_aliases_and_special_rooms(self):
        source = (ROOT / "mods/IsaacJev/main.lua").read_text(encoding="utf-8")
        helper = "local function canonicalRoomIndex(level, index)" + source.split("local function canonicalRoomIndex(level, index)", 1)[1].split("local function currentRoomKey()", 1)[0]
        result = LuaRuntime(unpack_returned_tuples=True).execute("""
            local function currentDimension() return 0 end
        """ + helper + """
            local level = {GetCurrentRoomIndex=function() return 96 end,
                GetRoomByIdx=function(_,index) return {SafeGridIndex=(index==83 or index==84 or index==96 or index==97) and 83 or index} end}
            return {canonicalRoomIndex(level),canonicalRoomIndex(level,84),
                canonicalRoomIndex(level,97),canonicalRoomIndex(level,70),canonicalRoomIndex(level,-12)}
        """)
        self.assertEqual([result[i] for i in range(1,6)],[83,83,83,70,-12])


if __name__ == "__main__":
    unittest.main()
