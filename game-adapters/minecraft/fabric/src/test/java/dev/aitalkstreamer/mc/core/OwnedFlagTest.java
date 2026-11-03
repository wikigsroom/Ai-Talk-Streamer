package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

class OwnedFlagTest {
    @Test void temporaryChangesRestoreTheOriginalBoolean() {
        var value=new AtomicBoolean(true);var flag=new OwnedFlag(value::get,value::set);
        flag.replace(false);flag.release();assertTrue(value.get());assertFalse(flag.owned());
    }
    @Test void returningToTheOriginalEndsTheClaimBeforeLaterInputChanges() {
        var value=new AtomicBoolean(true);var flag=new OwnedFlag(value::get,value::set);
        flag.replace(false);flag.replace(true);assertFalse(flag.owned());value.set(false);flag.release();assertFalse(value.get());
    }
    @Test void unchangedRequestsNeverClaimOrInvokeTheSetter() {
        var value=new AtomicBoolean(false);var flag=new OwnedFlag(value::get, next -> fail("No flag effect expected"));
        flag.replace(false);assertFalse(flag.owned());flag.release(() -> {fail("No restore expected");return true;});
    }
    @Test void aPhysicalRestoreSupplierIsReadAtReleaseAndOverridesTheOldValue() {
        var value=new AtomicBoolean(true);var physical=new AtomicBoolean(true);var flag=new OwnedFlag(value::get,value::set);
        flag.replace(false);physical.set(false);flag.release(physical::get);assertFalse(value.get());assertFalse(flag.owned());
    }
    @Test void anInterveningChangeIsPreservedWithoutPollingOrWriting() {
        var value=new AtomicBoolean(true);var flag=new OwnedFlag(value::get,value::set);flag.replace(false);value.set(true);
        flag.release(() -> {fail("Foreign value must be retained");return false;});assertTrue(value.get());
    }
    @Test void aNextWriteCannotCrossAnObservedForeignChange() {
        var value=new AtomicBoolean(true);var flag=new OwnedFlag(value::get,value::set);flag.replace(false);value.set(true);
        assertThrows(IllegalStateException.class,()->flag.replace(false));assertTrue(value.get());
    }
    @Test void aSetterFailureAfterMutationRetainsARecoverableClaim() {
        var value=new AtomicBoolean(true);var fail=new AtomicBoolean(true);
        var flag=new OwnedFlag(value::get,next->{value.set(next);if(fail.getAndSet(false))throw new IllegalStateException("fixture");});
        assertThrows(IllegalStateException.class,()->flag.replace(false));assertTrue(flag.owned());flag.release();assertTrue(value.get());
    }
    @Test void aPhysicalReadFailureRetainsOwnershipForRetry() {
        var value=new AtomicBoolean(true);var flag=new OwnedFlag(value::get,value::set);flag.replace(false);
        assertThrows(IllegalStateException.class,()->flag.release(()->{throw new IllegalStateException("fixture physical unavailable");}));
        assertTrue(flag.owned());flag.release(()->false);assertFalse(value.get());assertFalse(flag.owned());
    }
    @Test void aFailedRestoreThatAlreadyMutatedIsNotBlindlyRepeated() {
        var value=new AtomicBoolean(true);var writes=new AtomicInteger();var fail=new AtomicBoolean();
        var flag=new OwnedFlag(value::get,next->{writes.incrementAndGet();value.set(next);if(fail.get())throw new IllegalStateException("fixture");});
        flag.replace(false);fail.set(true);assertThrows(IllegalStateException.class,flag::release);fail.set(false);
        flag.release();assertTrue(value.get());assertEquals(2,writes.get());assertFalse(flag.owned());
    }
}
