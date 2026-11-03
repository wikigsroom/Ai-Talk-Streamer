package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PhysicalKeysTest {
    private final PhysicalKeys keys = new PhysicalKeys(42);
    @Test void knownKeyPollsTheActualCodeRatherThanTheScancode() {
        keys.event(42, 87, 17, 1); assertTrue(keys.held(17, code -> { assertEquals(87, code); return true; }));
        assertFalse(keys.held(17, code -> false));
    }
    @Test void unknownKeyUsesTheActualPressAndReleaseCallbacks() {
        keys.event(42, -1, 1001, 1); assertTrue(keys.held(1001, code -> fail("unknown code must not be polled")));
        keys.event(42, -1, 1001, 2); assertTrue(keys.held(1001, code -> false));
        keys.event(42, -1, 1001, 0); assertFalse(keys.held(1001, code -> false));
    }
    @Test void otherWindowsAndInvalidScancodesDoNotRegister() {
        keys.event(99, 87, 17, 1); keys.event(42, 87, -1, 1);
        assertFalse(keys.held(17, code -> fail("wrong window"))); assertFalse(keys.held(-1, code -> fail("invalid scancode")));
    }
    @Test void losingFocusClearsUnknownHeldKeys() {
        keys.event(42, -1, 1001, 1); keys.lostFocus(); assertFalse(keys.held(1001, code -> false));
    }
}
