package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.junit.jupiter.api.Assertions.*;

class InputLedgerTest {
    @Test void oneFailingReleaseDoesNotLeaveOtherKeysHeld() {
        Map<String, Boolean> keys = new HashMap<>(); var fail = new AtomicBoolean(false);
        var ledger = new InputLedger<String>((key, value) -> {
            if (fail.get() && key.equals("use")) throw new IllegalStateException("fixture"); keys.put(key, value);
        }, key -> false);
        ledger.press("use"); ledger.press("forward"); fail.set(true);
        assertThrows(IllegalStateException.class, ledger::release);
        assertFalse(keys.get("forward")); assertTrue(ledger.owns("use")); assertFalse(ledger.owns("forward"));
        fail.set(false); ledger.release(); assertTrue(ledger.empty());
    }
    @Test void pulseReleaseDoesNotClearAnotherHeldSyntheticKey() {
        Map<String, Boolean> keys = new HashMap<>(); var ledger = new InputLedger<String>(keys::put, key -> false);
        ledger.press("forward"); ledger.press("use"); ledger.release("use");
        assertTrue(keys.get("forward")); assertFalse(keys.get("use")); assertTrue(ledger.owns("forward")); assertFalse(ledger.owns("use"));
    }
    @Test void releasingAnUnownedPhysicalKeyDoesNotWriteIt() {
        var ledger = new InputLedger<String>((key, value) -> fail("unowned write"), key -> true); ledger.release("human");
    }
    @Test void singleKeyReleaseKeepsTheCurrentPhysicalHold() {
        Map<String, Boolean> keys = new HashMap<>(); var ledger = new InputLedger<String>(keys::put, key -> true);
        ledger.press("use"); ledger.release("use"); assertTrue(keys.get("use")); assertFalse(ledger.owns("use"));
    }
    @Test void releasePreservesAKeyTheHumanStillHolds() {
        Map<String, Boolean> keys = new HashMap<>(); Set<String> physical = new HashSet<>();
        var ledger = new InputLedger<String>(keys::put, physical::contains);
        ledger.press("use"); physical.add("use"); ledger.release(); assertTrue(keys.get("use")); assertTrue(ledger.empty());
    }
    @Test void onlyOwnedInputsAreRestoredAndReleased() {
        Map<String, Boolean> keys = new HashMap<>(Map.of("human_forward", true));
        var ledger = new InputLedger<String>(keys::put, key -> false); ledger.press("use"); ledger.release();
        assertTrue(keys.get("human_forward")); assertFalse(keys.get("use")); assertTrue(ledger.empty());
    }
    @Test void physicalStateIsReadAtReleaseRatherThanAtPress() {
        Map<String, Boolean> keys = new HashMap<>(); var physical = new AtomicBoolean(true);
        var ledger = new InputLedger<String>(keys::put, key -> physical.get()); ledger.press("use"); physical.set(false); ledger.release();
        assertFalse(keys.get("use"));
    }
    @Test void failedReleaseRemainsOwnedUntilRetried() {
        var failing = new AtomicBoolean(false); List<Boolean> writes = new ArrayList<>();
        var ledger = new InputLedger<String>((key, value) -> {
            if (failing.get()) throw new IllegalStateException("fixture"); writes.add(value);
        }, key -> false);
        ledger.press("use"); failing.set(true); assertThrows(IllegalStateException.class, ledger::release); assertFalse(ledger.empty());
        failing.set(false); ledger.release(); assertTrue(ledger.empty()); assertEquals(List.of(true, false), writes);
    }
    @Test void repeatedPressesDoNotDuplicateTheReleaseOrTouchKeysAgain() {
        List<String> restored = new ArrayList<>(); var ledger = new InputLedger<String>((key, value) -> { if (!value) restored.add(key); }, key -> false);
        ledger.press("use"); ledger.press("use"); ledger.release(); ledger.release(); assertEquals(List.of("use"), restored);
    }
}
