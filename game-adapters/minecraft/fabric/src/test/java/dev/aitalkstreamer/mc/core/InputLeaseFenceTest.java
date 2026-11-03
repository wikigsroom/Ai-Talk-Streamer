package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

class InputLeaseFenceTest {
    @Test void delayedTaskReleaseCannotClearALaterTasksSameKey() {
        var keys = new HashMap<String, Boolean>(); var ledger = new InputLedger<String>(keys::put, key -> false);
        var fence = new InputLeaseFence(ledger::release); var old = fence.ticket();
        old.check(); ledger.press("use"); old.release();
        var next = fence.ticket(); next.check(); ledger.press("use");
        old.release(); assertTrue(keys.get("use")); assertTrue(ledger.owns("use"));
        next.release(); assertFalse(keys.get("use"));
    }
    @Test void manualGlobalRestorationInvalidatesOldTaskWrites() {
        var writes = new AtomicInteger(); var fence = new InputLeaseFence(writes::incrementAndGet); var old = fence.ticket();
        fence.releaseAll(); assertThrows(IllegalStateException.class, old::check);
        old.release(); assertEquals(1, writes.get()); fence.ticket().check();
    }
    @Test void failedReleaseKeepsTheOriginalTicketForRetry() {
        var fail = new AtomicBoolean(true); var releases = new AtomicInteger();
        var fence = new InputLeaseFence(() -> { if (fail.get()) throw new IllegalStateException("fixture"); releases.incrementAndGet(); });
        var ticket = fence.ticket(); assertThrows(IllegalStateException.class, ticket::release); ticket.check();
        fail.set(false); ticket.release(); assertEquals(1, releases.get());
        assertThrows(IllegalStateException.class, ticket::check);
    }
    @Test void repeatedOldCleanupDoesNotRestoreTheMovementObjectTwice() {
        Object original = new Object(), synthetic = new Object(), foreign = new Object(); var state = new AtomicReference<>(original);
        var value = new OwnedValue<Object>(state::get, state::set); var fence = new InputLeaseFence(value::release); var ticket = fence.ticket();
        value.replace(synthetic); ticket.release(); assertSame(original, state.get());
        value.replace(foreign); ticket.release(); assertSame(foreign, state.get()); fence.ticket().release(); assertSame(original, state.get());
    }
    @Test void physicalHoldSurvivesTaskReleaseAndTheOldTicketBecomesInvalid() {
        var keys = new HashMap<String, Boolean>(); var ledger = new InputLedger<String>(keys::put, key -> true);
        var fence = new InputLeaseFence(ledger::release); var ticket = fence.ticket(); ledger.press("use"); ticket.release();
        assertTrue(keys.get("use")); assertTrue(ledger.empty()); assertThrows(IllegalStateException.class, ticket::check);
    }
    @Test void aPartiallyFailedReleaseStillRestoresOtherKeysBeforeRetry() {
        var keys = new HashMap<String, Boolean>(); var fail = new AtomicBoolean(false);
        var ledger = new InputLedger<String>((key, value) -> {
            if (key.equals("use") && fail.get()) throw new IllegalStateException("fixture"); keys.put(key, value);
        }, key -> false);
        var fence = new InputLeaseFence(ledger::release); var ticket = fence.ticket(); ledger.press("use"); ledger.press("forward"); fail.set(true);
        assertThrows(IllegalStateException.class, ticket::release); assertFalse(keys.get("forward")); ticket.check();
        fail.set(false); ticket.release(); assertTrue(ledger.empty());
    }
}
