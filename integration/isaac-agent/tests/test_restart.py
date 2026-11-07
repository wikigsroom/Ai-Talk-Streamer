"""Exercise the deployed Lua restart logic with a frozen simulation clock."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "python-libs"))
from lupa.lua53 import LuaRuntime


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        source = (ROOT / "mods" / "IsaacJev" / "main.lua").read_text(encoding="utf-8")
        self.assertTrue(self.lua.eval("function(s) return load(s) ~= nil end")(source))
        function = source.split("local function playerIsDead(player)", 1)[1]
        function = "local function playerIsDead(player)" + function.split("local function collectState()", 1)[0]
        self.api = self.lua.execute("""
            local now, commands = 0, 0
            local controllerEnabled, manualOverride = true, false
            local lastControlMessageAt = 0
            local deathDetectedFrame, deathDetectedAt, deathWaitTicks = -1, -1, 0
            local restartPhase, restartAttempted, restartCount = 'alive', false, 0
            local restartError, automatic = nil, false
            local player = {IsDead=function() return true end}
            game = {GetFrameCount=function() return 100 end}
            Isaac = {
                GetTime=function() return now end,
                ExecuteCommand=function(command)
                    assert(command == 'restart')
                    commands = commands + 1
                end,
            }
            Vector = function(x,y) return {X=x,Y=y} end
            resetRunObservations = function() end
        """ + function + """
            return {
                tick=function(ms, enabled, manual, fresh)
                    now = ms
                    controllerEnabled, manualOverride = enabled, manual
                    if fresh then lastControlMessageAt = now end
                    handleDeathAndRestart(player)
                    return commands, restartPhase
                end,
            }
        """)

    def test_frozen_simulation_restarts_after_real_time_once(self):
        self.assertEqual(self.api.tick(0, True, False, True), (0, "death_wait"))
        self.assertEqual(self.api.tick(1999, True, False, True), (0, "death_wait"))
        self.assertEqual(self.api.tick(2000, True, False, True), (1, "waiting_new_run"))
        self.assertEqual(self.api.tick(3000, True, False, True), (1, "waiting_new_run"))

    def test_observe_mode_never_restarts(self):
        self.api.tick(0, False, False, True)
        self.assertEqual(self.api.tick(5000, False, False, True), (0, "death_wait"))

    def test_manual_override_never_restarts(self):
        self.api.tick(0, True, True, True)
        self.assertEqual(self.api.tick(5000, True, True, True), (0, "death_wait"))

    def test_disconnected_controller_never_restarts(self):
        self.api.tick(0, True, False, True)
        self.assertEqual(self.api.tick(5000, True, False, False), (0, "death_wait"))


if __name__ == "__main__":
    unittest.main()
