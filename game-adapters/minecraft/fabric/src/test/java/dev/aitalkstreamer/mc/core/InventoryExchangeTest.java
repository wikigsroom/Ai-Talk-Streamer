package dev.aitalkstreamer.mc.core;

import java.util.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.Test;
import static dev.aitalkstreamer.mc.core.InventoryExchange.*;
import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import static org.junit.jupiter.api.Assertions.*;

/** Real exchange state machine; slot contents and packet delivery are explicit fixtures. */
class InventoryExchangeTest {
    final AtomicLong now = new AtomicLong(1000);
    final AtomicBoolean allowed = new AtomicBoolean(true);
    final InventoryExchange exchange = new InventoryExchange(now::get, allowed::get);
    State state() { var slots = new ArrayList<Stack>(Collections.nCopies(46, Stack.EMPTY)); slots.set(9, new Stack(1, 3)); return new State(slots, Stack.EMPTY); }
    State before = state(), after = before.swap(9, 36);
    void send() { exchange.send(before, after, before, 7, () -> assertEquals(-1, exchange.revision(7))); }
    @Test void interruptedUseResolvesTheExactZeroEffectStateBeforeAnotherAttempt() {
        exchange.sendAlternatives(before,List.of(before,after),before,7,()->exchange.revision(7));
        assertThrows(Json.Rejected.class,exchange::confirmedState); exchange.confirm(before,8);
        assertEquals(before,exchange.confirmedState());
    }
    @Test void interruptedUseCanResolveTheExactOneEffectAlternative() {
        exchange.sendAlternatives(before,List.of(before,after),before,7,()->exchange.revision(7));
        exchange.confirm(after,8); assertEquals(after,exchange.confirmedState());
    }
    @Test void alternativesDoNotAdmitAnUnrelatedInventoryDelta() {
        exchange.sendAlternatives(before,List.of(before,after),before,7,()->exchange.revision(7));
        exchange.confirm(after.slot(10,new Stack(4,1)),8);assertThrows(Json.Rejected.class,exchange::confirmedState);
    }
    @Test void unboundedOrDuplicateAlternativesAreRejectedBeforeAnyClick() {
        for(var states:List.of(List.<State>of(),List.of(before,before),List.of(before,after,before.slot(9,Stack.EMPTY)))) {
            var c=new InventoryExchange(now::get,allowed::get);
            assertThrows(Json.Rejected.class,()->c.sendAlternatives(before,states,before,7,()->fail("unexpected click")));
        }
    }
    @Test void staleRevisionsCannotWinAndFifteenBitWrapCanConfirm() {
        exchange.sendAlternatives(before,List.of(before,after),before,32767,()->exchange.revision(32767));
        exchange.confirm(before,32766);assertFalse(exchange.confirmed()); exchange.confirm(after,0);assertEquals(after,exchange.confirmedState());
    }
    @Test void revokedAlternativePacketsCannotResolveOrReopenAnExchange() {
        exchange.sendAlternatives(before,List.of(before,after),before,7,()->exchange.revision(7));allowed.set(false);
        exchange.confirm(after,8);assertThrows(Json.Rejected.class,exchange::confirmedState);exchange.close();
        allowed.set(true);exchange.confirm(before,9);assertThrows(Json.Rejected.class,exchange::confirmedState);
    }
    @Test void exactServerStateIsRequiredAfterTheAuthorizedClick() {
        send(); assertFalse(exchange.confirmed()); exchange.confirm(after, 8); assertTrue(exchange.confirmed()); assertEquals(8, exchange.confirmedRevision());
    }
    @Test void fullStateChecksOtherSlotsAndComponentIdentity() {
        send(); exchange.confirm(after.slot(36, new Stack(2, 3)), 8);
        assertThrows(Json.Rejected.class, exchange::check); assertEquals(-1, exchange.confirmedRevision());
    }
    @Test void cursorAndCraftResultAreIncludedInTheFullState() {
        send(); exchange.confirm(after.slot(0, new Stack(3, 1)), 8); assertThrows(Json.Rejected.class, exchange::check);
        var second = new InventoryExchange(now::get, allowed::get);
        second.send(before, after, before, 1, () -> second.revision(1));
        second.confirm(new State(after.slots(), new Stack(1, 1)), 2); assertThrows(Json.Rejected.class, second::check);
    }
    @Test void sameRevisionAndAnUnsolicitedPreSendPacketDoNotConfirm() {
        exchange.confirm(after, 8); send(); exchange.confirm(after, 7); assertFalse(exchange.confirmed());
    }
    @Test void aSecondClickCannotReplaceAnOutstandingOne() {
        send(); AtomicInteger calls = new AtomicInteger();
        assertThrows(Json.Rejected.class, () -> exchange.send(before, after, before, 7, calls::incrementAndGet)); assertEquals(0, calls.get());
    }
    @Test void aMissingOrRepeatedRevisionHookCannotBeReportedAsSent() {
        assertThrows(Json.Rejected.class, () -> exchange.send(before, after, before, 7, () -> {}));
        assertThrows(Json.Rejected.class, exchange::check);
        var second = new InventoryExchange(now::get, allowed::get);
        assertThrows(Json.Rejected.class, () -> second.send(before, after, before, 7, () -> { second.revision(7); second.revision(7); }));
    }
    @Test void theOriginalDeadlineIsInclusiveAndDoesNotRetry() {
        send(); now.addAndGet(TIMEOUT_MS); exchange.confirm(after, 8); assertThrows(Json.Rejected.class, exchange::check);
        assertEquals(-1, exchange.confirmedRevision());
    }
    @Test void revocationAndCloseRejectLateFacts() {
        send(); allowed.set(false); exchange.confirm(after, 8); assertEquals(-1, exchange.confirmedRevision());
        allowed.set(true); exchange.close(); exchange.confirm(after, 9); assertThrows(Json.Rejected.class, exchange::check);
    }
    @Test void packetDeliveryDuringTheClickCannotConfirmIt() {
        exchange.send(before, after, before, 7, () -> { exchange.revision(7); exchange.confirm(after, 8); });
        assertFalse(exchange.confirmed()); exchange.confirm(after, 9); assertTrue(exchange.confirmed());
    }
    @Test void plannedStatesAreImmutableAndInvalidSwapsAreRejected() {
        var slots = new ArrayList<>(before.slots()); var frozen = new State(slots, Stack.EMPTY); slots.set(9, Stack.EMPTY);
        assertEquals(new Stack(1, 3), frozen.slots().get(9)); assertThrows(UnsupportedOperationException.class, () -> frozen.slots().clear());
        assertThrows(Json.Rejected.class, () -> before.swap(0, 36)); assertThrows(Json.Rejected.class, () -> before.swap(9, 9));
    }
    @Test void changedPreStateRejectsBeforeAnyClick() {
        AtomicInteger calls = new AtomicInteger();
        assertThrows(Json.Rejected.class, () -> exchange.send(before, after, after, 7, calls::incrementAndGet)); assertEquals(0, calls.get());
    }
    @Test void anotherThreadCannotSendOrConfirm() throws Exception {
        send(); var error = new AtomicReference<Throwable>();
        Thread thread = new Thread(() -> { try { exchange.confirm(after, 8); } catch (Throwable failure) { error.set(failure); } });
        thread.start(); thread.join(); assertInstanceOf(Json.Rejected.class, error.get()); assertFalse(exchange.confirmed());
    }
}
