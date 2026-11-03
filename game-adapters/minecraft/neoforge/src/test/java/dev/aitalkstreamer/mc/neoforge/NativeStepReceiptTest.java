package dev.aitalkstreamer.mc.neoforge;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;

class NativeStepReceiptTest {
    private long clock; private boolean current=true;
    private final Point at=new Point(1,12,0);
    private final NativeStepReceipt receipt=new NativeStepReceipt(at,()->current,()->clock);
    @Test void predictionAloneCannotConfirm() { assertFalse(receipt.confirmed(true)); }
    @Test void serverUpdateNeedsMatchingLiveWorld() { receipt.packet(at,true);assertFalse(receipt.confirmed(false));assertTrue(receipt.confirmed(true)); }
    @Test void unrelatedBlockCannotConfirm() { receipt.packet(new Point(2,12,0),true);assertEquals(0,receipt.packets());assertFalse(receipt.confirmed(true)); }
    @Test void serverRefusalCannotConfirm() { receipt.packet(at,false);assertFalse(receipt.confirmed(true)); }
    @Test void serverReplacementInvalidatesEarlierAir() { receipt.packet(at,true);receipt.packet(at,false);assertFalse(receipt.confirmed(true)); }
    @Test void revokedContextRejectsLatePacketsAndAdvancement() { current=false;receipt.packet(at,true);assertEquals(0,receipt.packets());assertThrows(LocalTaskFailure.class,()->receipt.confirmed(true)); }
    @Test void cancellationRejectsLatePacketsAndAdvancement() { receipt.close();receipt.packet(at,true);assertEquals(0,receipt.packets());assertThrows(LocalTaskFailure.class,()->receipt.confirmed(true)); }
    @Test void missingOrLateAckTimesOut() { clock=15001;receipt.packet(at,true);assertThrows(LocalTaskFailure.class,()->receipt.confirmed(true)); }
}
