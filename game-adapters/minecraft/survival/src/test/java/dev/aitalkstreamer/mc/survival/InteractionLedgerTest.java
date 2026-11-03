package dev.aitalkstreamer.mc.survival;

import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.survival.InteractionLedger.Kind.*;

class InteractionLedgerTest {
    @Test void aRequestedActionPreservesItsReturnAndRecordsOwnershipBeforeExecution() {
        var ledger=new InteractionLedger(); var calls=new AtomicInteger();
        assertEquals(7,ledger.issue(BREAKING,()->{ assertTrue(ledger.owns(BREAKING)); calls.incrementAndGet(); return 7; }));
        assertEquals(1,calls.get()); assertFalse(ledger.owns(USING));
    }
    @Test void anExceptionCannotEraseAnActionWhichMayAlreadyHaveStarted() {
        var ledger=new InteractionLedger();
        assertThrows(IllegalArgumentException.class,()->ledger.issue(USING,()->{ throw new IllegalArgumentException("after effect"); }));
        assertTrue(ledger.owns(USING));
    }
    @Test void cancellingAnUnownedActionDoesNotTouchAnOperatorsCurrentAction() {
        var ledger=new InteractionLedger(); var writes=new AtomicInteger();
        ledger.stop(BREAKING,true,writes::incrementAndGet); ledger.stop(USING,true,writes::incrementAndGet);
        assertEquals(0,writes.get());
    }
    @Test void naturalStopCancelsOnlyItsRequestedActionOnce() {
        var ledger=new InteractionLedger(); var writes=new AtomicInteger();
        ledger.issue(BREAKING,()->true); ledger.issue(USING,()->true);
        ledger.stop(BREAKING,true,writes::incrementAndGet); ledger.stop(BREAKING,true,writes::incrementAndGet);
        assertEquals(1,writes.get()); assertTrue(ledger.owns(USING)); assertFalse(ledger.owns(BREAKING));
    }
    @Test void failedNaturalCleanupKeepsTheClaimForAnExplicitRetry() {
        var ledger=new InteractionLedger(); var writes=new AtomicInteger(); ledger.issue(BREAKING,()->true);
        assertThrows(IllegalStateException.class,()->ledger.stop(BREAKING,true,()->{ throw new IllegalStateException("network"); }));
        assertTrue(ledger.owns(BREAKING)); ledger.stop(BREAKING,true,writes::incrementAndGet);
        assertEquals(1,writes.get()); assertFalse(ledger.owns(BREAKING));
    }
    @Test void revokedCleanupCannotSendAPacketOrCancelThePhysicalOperatorsNewAction() {
        var ledger=new InteractionLedger(); var writes=new AtomicInteger(); ledger.issue(BREAKING,()->true); ledger.issue(USING,()->true);
        ledger.stop(BREAKING,false,writes::incrementAndGet); ledger.stop(USING,false,writes::incrementAndGet);
        assertEquals(0,writes.get()); assertFalse(ledger.owns(BREAKING)); assertFalse(ledger.owns(USING));
    }
    @Test void discardingAnOldRootsClaimsDoesNotClearANewRootsActions() {
        var old=new InteractionLedger(); var next=new InteractionLedger();
        old.issue(BREAKING,()->true); next.issue(BREAKING,()->true); old.discard();
        assertTrue(next.owns(BREAKING)); assertFalse(old.owns(BREAKING));
    }
    @Test void aNegativeImmediateResultStillRequiresCheckingForPartialInteractionState() {
        var ledger=new InteractionLedger(); var checks=new AtomicInteger();
        assertFalse(ledger.issue(BREAKING,()->false)); assertTrue(ledger.owns(BREAKING));
        ledger.stop(BREAKING,true,checks::incrementAndGet); assertEquals(1,checks.get());
    }
    @Test void aRevokedRealRootOnlyDropsClaimsAndNeverObtainsANewPermit() {
        var current=new AtomicBoolean(true); var writes=new AtomicInteger(); var ledger=new InteractionLedger();
        var context=new SurvivalAuthority.Context("task","controller","lease","world",1);
        var session=SurvivalAuthority.open(context,new SurvivalAuthority.Boundary() {
            public boolean current(SurvivalAuthority.Context c) { return current.get(); }
            public void actuate(SurvivalAuthority.Context c,java.util.function.BooleanSupplier open,Runnable write) {
                if (!current.get() || !open.getAsBoolean()) throw new SurvivalAuthority.Denied(); write.run();
            }
        });
        try {
            SurvivalAuthority.run(session,()->SurvivalAuthority.write(()->ledger.issue(USING,()->{ writes.incrementAndGet(); return true; })));
            current.set(false);
            session.close(()->{ SurvivalAuthority.requireOwnerScope(); ledger.stop(USING,SurvivalAuthority.inScope(),writes::incrementAndGet); },()->{});
            assertEquals(1,writes.get()); assertFalse(ledger.owns(USING));
        } finally { session.close(()->{},()->{}); }
    }
}
