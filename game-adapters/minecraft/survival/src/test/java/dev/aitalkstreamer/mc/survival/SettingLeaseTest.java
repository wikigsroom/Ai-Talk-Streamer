package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

class SettingLeaseTest {
    @Test void repeatedChangesRestoreTheActualOriginalValue() {
        var value = new AtomicReference<>(.4); var lease = new SettingLease<>(value::get, value::set);
        lease.replace(.6); lease.replace(.8); lease.release(); assertEquals(.4, value.get()); lease.release();
    }
    @Test void nativeClampingUsesTheObservedValueForOwnership() {
        var value = new AtomicReference<>(.4); var lease = new SettingLease<>(value::get, next -> value.set(Math.min(.7, next)));
        lease.replace(.9); assertEquals(.7, value.get()); lease.check(); lease.release(); assertEquals(.4, value.get());
    }
    @Test void unchangedRequestsDoNotClaimOrWriteASetting() {
        var writes = new AtomicInteger(); var value = new AtomicReference<>(true);
        var lease = new SettingLease<>(value::get, next -> { writes.incrementAndGet(); value.set(next); });
        lease.replace(true); value.set(false); lease.release(); assertFalse(value.get()); assertEquals(0, writes.get());
    }
    @Test void anInterveningChangeRejectsFurtherWritesAndIsPreservedAtRelease() {
        var value = new AtomicReference<>(.4); var lease = new SettingLease<>(value::get, value::set);
        lease.replace(.6); value.set(.8);
        assertEquals("GAME_OPTION_OWNER_CHANGED", assertThrows(IllegalStateException.class, () -> lease.replace(.5)).getMessage());
        lease.release(); assertEquals(.8, value.get());
    }
    @Test void aSetterThatMutatesThenThrowsStillLeavesARecoverableClaim() {
        var value = new AtomicReference<>(.4); var fail = new AtomicBoolean(true);
        var lease = new SettingLease<>(value::get, next -> { value.set(next); if (fail.getAndSet(false)) throw new IllegalStateException("fixture callback failed"); });
        assertThrows(IllegalStateException.class, () -> lease.replace(.6)); lease.release(); assertEquals(.4, value.get());
    }
    @Test void failedRestoreCanBeConfirmedOnRetryWithoutRepeatingItsCallback() {
        var value = new AtomicReference<>(.4); var fail = new AtomicBoolean(); var writes = new AtomicInteger();
        var lease = new SettingLease<>(value::get, next -> { value.set(next); writes.incrementAndGet(); if (fail.getAndSet(false)) throw new IllegalStateException("fixture restore callback"); });
        lease.replace(.6); fail.set(true); assertThrows(IllegalStateException.class, lease::release);
        lease.release(); assertEquals(.4, value.get()); assertEquals(2, writes.get());
    }
    @Test void anUnobservedSetterResultCannotAuthorizeAWriteOrBlindRestore() {
        var value = new AtomicReference<>(.4); var unreadable = new AtomicBoolean();
        var lease = new SettingLease<>(() -> { if (unreadable.get()) throw new IllegalStateException("fixture read unavailable"); return value.get(); },
                next -> { value.set(next); unreadable.set(true); });
        assertThrows(IllegalStateException.class, () -> lease.replace(.6)); unreadable.set(false);
        assertEquals("GAME_OPTION_RESULT_UNKNOWN", assertThrows(IllegalStateException.class, lease::release).getMessage());
        assertEquals(.6, value.get()); lease.discard();
    }
    @Test void anUnconfirmedRestoreRetainsItsClaimUntilTheOriginalValueIsObserved() {
        var value = new AtomicReference<>(.4); var clamp = new AtomicBoolean();
        var lease = new SettingLease<>(value::get, next -> value.set(clamp.get() ? .5 : next));
        lease.replace(.6); clamp.set(true);
        assertEquals("GAME_OPTION_RESTORE_UNCONFIRMED", assertThrows(IllegalStateException.class, lease::release).getMessage());
        clamp.set(false); lease.release(); assertEquals(.4, value.get());
    }
}
